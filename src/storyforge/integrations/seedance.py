from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from storyforge.core.config import SeedanceConfig
from storyforge.domains.video.contracts import SeedanceClipTask, SeedanceManifest


DEFAULT_SEEDANCE_BASE_URL = "https://operator.las.cn-beijing.volces.com/api/v1"
SEEDANCE_BASE_URL_ENV = "SEEDANCE_BASE_URL"
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "rejected"}
SEEDANCE_MIN_DURATION_SECONDS = 2
SEEDANCE_MAX_DURATION_SECONDS = 12


@dataclass(slots=True)
class SeedanceSubmission:
    submitted: bool
    manifest_title: str
    clip_results: list[dict[str, Any]]
    note: str


@dataclass(slots=True)
class SeedanceClipExecution:
    segment_id: str
    title: str
    output_path: str
    remote_task_id: str = ""
    submit_status: str = "planned"
    remote_status: str = "planned"
    video_url: str = ""
    cover_url: str = ""
    error: str = ""
    status_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SeedanceExecutionReport:
    submitted: bool
    manifest_title: str
    completed_count: int
    failed_count: int
    pending_count: int
    note: str
    clip_results: list[SeedanceClipExecution] = field(default_factory=list)


class SeedanceSubmitError(RuntimeError):
    def __init__(self, endpoint: str, attempts: list[dict[str, Any]]) -> None:
        self.endpoint = endpoint
        self.attempts = attempts
        self.status_payload = {
            "status": "submit_failed",
            "endpoint": endpoint,
            "attempts": attempts,
        }
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        summaries: list[str] = []
        for attempt in self.attempts:
            variant = str(attempt.get("variant", "default"))
            status_code = attempt.get("status_code")
            error_message = (
                attempt.get("response_message")
                or attempt.get("response_text")
                or attempt.get("error")
                or "Unknown error"
            )
            if status_code:
                summaries.append(f"[{variant}] HTTP {status_code}: {error_message}")
            else:
                summaries.append(f"[{variant}] {error_message}")
        detail = " | ".join(summaries) if summaries else "Unknown error"
        return f"Seedance task submit failed at {self.endpoint}: {detail}"


class SeedanceClient:
    def __init__(self, config: SeedanceConfig) -> None:
        self.config = config
        self.api_key = os.getenv(config.api_key_env, "")

    async def submit_manifest(
        self,
        manifest: SeedanceManifest,
        force_submit: bool = False,
        segment_ids: set[str] | None = None,
    ) -> SeedanceSubmission:
        target_clips = self._resolve_target_clips(manifest, segment_ids)
        if not self.config.enabled:
            return SeedanceSubmission(
                submitted=False,
                manifest_title=manifest.title,
                clip_results=[],
                note="Seedance is disabled; manifest generated only.",
            )
        if not (force_submit or self.config.auto_submit):
            return SeedanceSubmission(
                submitted=False,
                manifest_title=manifest.title,
                clip_results=[],
                note="Seedance execution skipped; manifest generated only.",
            )
        if not self.api_key:
            return SeedanceSubmission(
                submitted=False,
                manifest_title=manifest.title,
                clip_results=[],
                note="Seedance API key is missing; manifest generated only.",
            )

        clip_results: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=120) as client:
            for clip in target_clips:
                payload, resolved_prompt, reference_bindings = self._build_payload_with_metadata(clip)
                clip.submit_variant = "timeline_only"
                clip.submitted_prompt = resolved_prompt
                clip.submitted_reference_bindings = reference_bindings
                clip.submitted_request_info = self._build_submitted_request_info(
                    endpoint=self._task_creation_endpoint(),
                    variant="timeline_only",
                    payload=payload,
                    reference_bindings=reference_bindings,
                )
                response = await client.post(
                    self._task_creation_endpoint(),
                    json=payload,
                    headers=self._request_headers(),
                )
                response.raise_for_status()
                body = response.json()
                task_id = self._extract_task_id(body)
                if task_id:
                    clip.remote_task_id = task_id
                    clip.submit_status = "submitted"
                    clip.remote_status = "submitted"
                clip_results.append(
                    {
                        "segment_id": clip.segment_id,
                        "status_code": response.status_code,
                        "task_id": task_id,
                        "response": body,
                    }
                )

        return SeedanceSubmission(
            submitted=True,
            manifest_title=manifest.title,
            clip_results=clip_results,
            note="Seedance tasks submitted successfully.",
        )

    async def fetch_task_status(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                self._task_status_endpoint(task_id),
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return response.json()

    def execute_manifest(
        self,
        manifest: SeedanceManifest,
        force_submit: bool = False,
        segment_ids: set[str] | None = None,
    ) -> SeedanceExecutionReport:
        """
        Submit each clip, poll it to a terminal status, and optionally download the
        generated mp4 back into the project output directory.
        """
        target_clips = self._resolve_target_clips(manifest, segment_ids)
        if not self.config.enabled:
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(target_clips),
                note="Seedance is disabled; manifest generated only.",
            )
        if not (force_submit or self.config.auto_submit):
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(target_clips),
                note="Seedance execution skipped; manifest generated only.",
            )
        if not self.api_key:
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(target_clips),
                note="Seedance API key is missing; manifest generated only.",
            )

        clip_results: list[SeedanceClipExecution] = []
        completed_count = 0
        failed_count = 0
        pending_count = 0

        with httpx.Client(timeout=120) as client:
            for clip in target_clips:
                execution = SeedanceClipExecution(
                    segment_id=clip.segment_id,
                    title=clip.title,
                    output_path=clip.output_path,
                )
                try:
                    if self._clip_is_completed_locally(clip):
                        self._copy_clip_state_to_execution(clip, execution)
                        completed_count += 1
                        clip_results.append(execution)
                        continue

                    task_id = self._resolve_existing_task_id(clip)
                    if not task_id:
                        task_id = self._submit_clip(client, clip)
                    execution.remote_task_id = task_id
                    execution.submit_status = clip.submit_status
                    execution.remote_status = clip.remote_status

                    status_payload = self._resolve_clip_status_payload(client, clip, task_id)
                    execution.status_payload = status_payload
                    remote_status = self._extract_status(status_payload)
                    execution.remote_status = remote_status
                    clip.remote_status = remote_status

                    if remote_status == "succeeded":
                        self._complete_succeeded_clip(client, clip, execution, status_payload)
                        completed_count += 1
                    elif remote_status == "timeout":
                        message = "Seedance polling timed out before the task reached a terminal status."
                        clip.submit_status = "timeout"
                        clip.error = message
                        execution.submit_status = "timeout"
                        execution.error = message
                        pending_count += 1
                    else:
                        message = self._extract_error_message(status_payload)
                        clip.submit_status = "failed"
                        clip.error = message
                        execution.submit_status = "failed"
                        execution.error = message
                        failed_count += 1
                except Exception as exc:
                    clip.submit_status = "failed"
                    clip.remote_status = clip.remote_status or "failed"
                    clip.error = str(exc)
                    execution.remote_task_id = clip.remote_task_id
                    execution.remote_status = clip.remote_status
                    execution.submit_status = "failed"
                    execution.error = str(exc)
                    status_payload = getattr(exc, "status_payload", None)
                    if isinstance(status_payload, dict):
                        execution.status_payload = status_payload
                    failed_count += 1
                clip_results.append(execution)

        note = "Seedance clip execution completed successfully."
        if failed_count:
            note = "Seedance clip execution completed with partial failures."
        elif pending_count:
            note = "Seedance clip execution submitted, but some clips are still pending."

        return SeedanceExecutionReport(
            submitted=True,
            manifest_title=manifest.title,
            completed_count=completed_count,
            failed_count=failed_count,
            pending_count=pending_count,
            note=note,
            clip_results=clip_results,
        )

    def _resolve_target_clips(
        self,
        manifest: SeedanceManifest,
        segment_ids: set[str] | None,
    ) -> list[SeedanceClipTask]:
        if not segment_ids:
            return list(manifest.clips)
        target_clips = [clip for clip in manifest.clips if clip.segment_id in segment_ids]
        missing_segments = sorted(segment_ids - {clip.segment_id for clip in target_clips})
        if missing_segments:
            raise ValueError(
                "Requested video segments are not present in seedance_manifest.json: "
                + ", ".join(missing_segments)
            )
        return target_clips

    def _clip_is_completed_locally(self, clip: SeedanceClipTask) -> bool:
        if clip.submit_status != "completed" or clip.remote_status != "succeeded":
            return False
        return Path(clip.downloaded_path or clip.output_path).exists()

    def _copy_clip_state_to_execution(
        self,
        clip: SeedanceClipTask,
        execution: SeedanceClipExecution,
    ) -> None:
        execution.remote_task_id = clip.remote_task_id
        execution.remote_status = "succeeded"
        execution.submit_status = "completed"
        execution.video_url = clip.video_url
        execution.cover_url = clip.cover_url
        execution.error = ""

    def _resolve_existing_task_id(self, clip: SeedanceClipTask) -> str:
        if not clip.remote_task_id:
            return ""
        if clip.remote_status in {"failed", "cancelled", "canceled", "rejected"}:
            return ""
        return clip.remote_task_id

    def _resolve_clip_status_payload(
        self,
        client: httpx.Client,
        clip: SeedanceClipTask,
        task_id: str,
    ) -> dict[str, Any]:
        if clip.remote_status == "succeeded" and clip.video_url:
            payload: dict[str, Any] = {
                "status": "succeeded",
                "content": {"video_url": clip.video_url},
            }
            if clip.cover_url:
                payload["content"]["cover_url"] = clip.cover_url
            return payload
        return self.fetch_task_status_sync(client, task_id)

    def _complete_succeeded_clip(
        self,
        client: httpx.Client,
        clip: SeedanceClipTask,
        execution: SeedanceClipExecution,
        status_payload: dict[str, Any],
    ) -> None:
        video_url = self._extract_video_url(status_payload) or clip.video_url
        cover_url = self._extract_cover_url(status_payload) or clip.cover_url
        execution.video_url = video_url
        execution.cover_url = cover_url
        clip.video_url = video_url
        clip.cover_url = cover_url
        clip.submit_status = "completed"
        clip.error = ""
        execution.submit_status = "completed"
        execution.error = ""
        output_path = Path(clip.output_path)
        if self.config.download_outputs and video_url and not output_path.exists():
            self._download_video(client, video_url, output_path)
        if output_path.exists():
            clip.downloaded_path = clip.output_path

    def fetch_task_status_sync(
        self,
        client: httpx.Client,
        task_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.max_wait_seconds
        last_payload: dict[str, Any] | None = None

        while time.monotonic() < deadline:
            response = client.get(
                self._task_status_endpoint(task_id),
                headers=self._request_headers(include_content_type=False),
            )
            response.raise_for_status()
            payload = response.json()
            last_payload = payload
            status = self._extract_status(payload)
            if status in TERMINAL_STATUSES:
                return payload
            time.sleep(self.config.poll_interval_seconds)

        if last_payload is None:
            raise RuntimeError(f"Seedance polling returned no payload for task {task_id}.")

        last_payload["status"] = "timeout"
        return last_payload

    def build_payload(
        self,
        clip: SeedanceClipTask,
        *,
        include_mid_frame_reference: bool = True,
        include_start_frame: bool = True,
        include_end_frame: bool = True,
    ) -> dict[str, Any]:
        payload, _, _ = self._build_payload_with_metadata(
            clip,
            include_mid_frame_reference=include_mid_frame_reference,
            include_start_frame=include_start_frame,
            include_end_frame=include_end_frame,
        )
        return payload

    def _build_payload_with_metadata(
        self,
        clip: SeedanceClipTask,
        *,
        include_mid_frame_reference: bool = True,
        include_start_frame: bool = True,
        include_end_frame: bool = True,
    ) -> tuple[dict[str, Any], str, list[dict[str, str]]]:
        if not SEEDANCE_MIN_DURATION_SECONDS <= clip.duration_seconds <= SEEDANCE_MAX_DURATION_SECONDS:
            raise ValueError(
                "Seedance duration must be between "
                f"{SEEDANCE_MIN_DURATION_SECONDS} and {SEEDANCE_MAX_DURATION_SECONDS} seconds, "
                f"got {clip.duration_seconds} for segment {clip.segment_id}."
            )
        reference_bindings = self._resolve_reference_bindings(
            clip,
            include_mid_frame_reference=include_mid_frame_reference,
            include_start_frame=include_start_frame,
            include_end_frame=include_end_frame,
        )
        resolved_prompt = self._build_multimodal_reference_prompt(
            clip,
            reference_bindings,
        )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": resolved_prompt,
            }
        ]
        for _, url in reference_bindings:
            content.append(
                {
                    "role": "reference_image",
                    "type": "image_url",
                    "image_url": {"url": url},
                }
            )

        payload = {
            "model": self.config.model,
            "content": content,
            "ratio": clip.aspect_ratio,
            "duration": clip.duration_seconds,
            "watermark": self.config.watermark,
        }
        payload["generate_audio"] = bool(clip.with_audio)
        return payload, resolved_prompt, self._describe_reference_bindings(reference_bindings)

    def _resolve_reference_bindings(
        self,
        clip: SeedanceClipTask,
        *,
        include_mid_frame_reference: bool,
        include_start_frame: bool,
        include_end_frame: bool,
    ) -> list[tuple[str, str]]:
        ordered_sources: list[tuple[str, str]] = []
        if include_start_frame and clip.start_frame_url:
            ordered_sources.append(("start", clip.start_frame_url))
        if include_mid_frame_reference and clip.mid_frame_url:
            ordered_sources.append(("mid", clip.mid_frame_url))
        if include_end_frame and clip.end_frame_url:
            ordered_sources.append(("end", clip.end_frame_url))

        deduped: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for kind, url in ordered_sources:
            normalized = str(url).strip()
            if not normalized or normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            deduped.append((kind, normalized))
        return deduped

    def _build_multimodal_reference_prompt(
        self,
        clip: SeedanceClipTask,
        reference_bindings: list[tuple[str, str]],
    ) -> str:
        base_prompt = clip.prompt.strip()
        if not reference_bindings:
            return base_prompt

        lines: list[str] = [base_prompt, "", "实际提交图片绑定："]
        for index, (kind, _) in enumerate(reference_bindings, start=1):
            label = f"图片{index}"
            if kind == "start":
                lines.append(f"- {label} 对应起步画面。")
            elif kind == "mid":
                lines.append(f"- {label} 对应中段状态。")
            elif kind == "end":
                lines.append(f"- {label} 对应收束画面。")
        timeline_indexes = [
            index
            for index, (kind, _) in enumerate(reference_bindings, start=1)
            if kind in {"start", "mid", "end"}
        ]
        if len(timeline_indexes) >= 3:
            first_label = f"图片{timeline_indexes[0]}"
            middle_labels = " -> ".join(f"图片{index}" for index in timeline_indexes[1:-1])
            final_label = f"图片{timeline_indexes[-1]}"
            lines.append(
                f"- 严格按 {first_label} -> {middle_labels} -> {final_label} 的顺序推进画面，不要跳帧，不要只在结尾突然跳到收束图。"
            )
        elif len(timeline_indexes) == 2:
            first_label = f"图片{timeline_indexes[0]}"
            final_label = f"图片{timeline_indexes[1]}"
            lines.append(
                f"- 严格按 {first_label} -> {final_label} 的顺序推进画面，不要长时间停在开场图后于片尾突然跳到收束图。"
            )
        elif len(timeline_indexes) == 1:
            lines.append(
                f"- 图片{timeline_indexes[0]} 是唯一时间锚点，整段都围绕它建立稳定构图和连续微动作。"
            )
        lines.append("- 如果相邻关键图的人数、站位或景别不同，必须拍出可见的切入、入画、靠近、让位或镜头重构过程，禁止瞬间换人或瞬间换构图。")
        lines.append("- 除非文本明确要求插入镜头，否则不要丢失既定角色，不要替换服装，不要改变已给定的空间关系与镜头方向。")
        return "\n".join(line for line in lines if line is not None)

    def _describe_reference_bindings(
        self,
        reference_bindings: list[tuple[str, str]],
    ) -> list[dict[str, str]]:
        descriptions: list[dict[str, str]] = []
        for index, (kind, url) in enumerate(reference_bindings, start=1):
            if kind == "start":
                description = "开场视觉锚点，视频必须从这张图对应的构图、角色关系与动作状态自然起步。"
            elif kind == "mid":
                description = "中段视觉锚点，镜头推进过程中必须自然经过这张图对应的中间状态，不要跳过或弱化。"
            else:
                description = "收束视觉锚点，片尾必须落到这张图对应的构图、角色关系与动作结果。"
            descriptions.append(
                {
                    "label": f"图片{index}",
                    "kind": kind,
                    "description": description,
                    "url": str(url).strip(),
                }
            )
        return descriptions

    def _build_submitted_request_info(
        self,
        *,
        endpoint: str,
        variant: str,
        payload: dict[str, Any],
        reference_bindings: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "provider": "seedance",
            "endpoint": endpoint,
            "variant": variant,
            "payload": payload,
            "reference_bindings": reference_bindings,
        }

    def _submit_clip(self, client: httpx.Client, clip: SeedanceClipTask) -> str:
        endpoint = self._task_creation_endpoint()
        attempts: list[dict[str, Any]] = []
        candidates = self._submit_payload_candidates(clip)
        for index, (variant, payload, resolved_prompt, reference_bindings) in enumerate(candidates):
            clip.submit_variant = variant
            clip.submitted_prompt = resolved_prompt
            clip.submitted_reference_bindings = reference_bindings
            clip.submitted_request_info = self._build_submitted_request_info(
                endpoint=endpoint,
                variant=variant,
                payload=payload,
                reference_bindings=reference_bindings,
            )
            try:
                response = client.post(
                    endpoint,
                    json=payload,
                    headers=self._request_headers(),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                attempts.append(
                    self._build_submit_attempt_debug(
                        variant=variant,
                        payload=payload,
                        response=exc.response,
                    )
                )
                if (
                    exc.response.status_code == 400
                    and index < len(candidates) - 1
                ):
                    continue
                raise SeedanceSubmitError(endpoint, attempts) from exc
            except httpx.HTTPError as exc:
                attempts.append(
                    {
                        "variant": variant,
                        "error": str(exc),
                        "request_summary": self._summarize_payload(payload),
                    }
                )
                raise SeedanceSubmitError(endpoint, attempts) from exc

            body = response.json()
            task_id = self._extract_task_id(body)
            if not task_id:
                attempts.append(
                    {
                        "variant": variant,
                        "status_code": response.status_code,
                        "response_json": body,
                        "response_message": "Seedance task id missing from response.",
                        "request_summary": self._summarize_payload(payload),
                    }
                )
                raise SeedanceSubmitError(endpoint, attempts)
            clip.remote_task_id = task_id
            clip.submit_status = "submitted"
            clip.remote_status = "submitted"
            return task_id
        raise SeedanceSubmitError(endpoint, attempts)

    def _download_video(self, client: httpx.Client, video_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = client.get(video_url)
        response.raise_for_status()
        output_path.write_bytes(response.content)

    def _request_headers(self, include_content_type: bool = True) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _task_creation_endpoint(self) -> str:
        base = (
            os.getenv(SEEDANCE_BASE_URL_ENV)
            or self.config.base_url
            or DEFAULT_SEEDANCE_BASE_URL
        ).rstrip("/")
        if base.endswith("/api/v3"):
            return f"{base}/contents/generations/tasks"
        if base.endswith("/contents/generations/tasks"):
            return base
        if base.endswith("/api/v1"):
            return f"{base}/contents/generations/tasks"
        return f"{base}/api/v1/contents/generations/tasks"

    def _task_status_endpoint(self, task_id: str) -> str:
        base = (
            os.getenv(SEEDANCE_BASE_URL_ENV)
            or self.config.base_url
            or DEFAULT_SEEDANCE_BASE_URL
        ).rstrip("/")
        if base.endswith("/api/v3"):
            return f"{base}/contents/generations/tasks/{task_id}"
        if base.endswith("/api/v1"):
            return f"{base}/contents/generations/tasks/{task_id}"
        return f"{base}/api/v1/contents/generations/tasks/{task_id}"

    def _extract_task_id(self, payload: dict[str, Any]) -> str:
        data = payload.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        if isinstance(payload.get("id"), str):
            return str(payload["id"])
        return ""

    def _extract_status(self, payload: dict[str, Any]) -> str:
        if isinstance(payload.get("status"), str):
            return str(payload["status"])
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("status"), str):
            return str(data["status"])
        return "unknown"

    def _extract_video_url(self, payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, dict) and content.get("video_url"):
            return str(content["video_url"])
        data = payload.get("data")
        if isinstance(data, dict):
            nested_content = data.get("content")
            if isinstance(nested_content, dict) and nested_content.get("video_url"):
                return str(nested_content["video_url"])
            if data.get("video_url"):
                return str(data["video_url"])
        return ""

    def _extract_cover_url(self, payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, dict) and content.get("cover_url"):
            return str(content["cover_url"])
        data = payload.get("data")
        if isinstance(data, dict):
            nested_content = data.get("content")
            if isinstance(nested_content, dict) and nested_content.get("cover_url"):
                return str(nested_content["cover_url"])
            if data.get("cover_url"):
                return str(data["cover_url"])
        return ""

    def _extract_error_message(self, payload: dict[str, Any]) -> str:
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested_message = value.get("message") or value.get("detail")
                if isinstance(nested_message, str) and nested_message:
                    return nested_message

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("message", "detail", "error"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return f"Seedance task ended with status={self._extract_status(payload)}"

    def _submit_payload_candidates(
        self,
        clip: SeedanceClipTask,
    ) -> list[tuple[str, dict[str, Any], str, list[dict[str, str]]]]:
        candidates = [
            (
                "timeline_only",
                *self._build_payload_with_metadata(
                    clip,
                    include_mid_frame_reference=True,
                    include_start_frame=True,
                    include_end_frame=True,
                ),
            ),
            (
                "start_mid_only",
                *self._build_payload_with_metadata(
                    clip,
                    include_mid_frame_reference=True,
                    include_start_frame=True,
                    include_end_frame=False,
                ),
            ),
            (
                "start_end_only",
                *self._build_payload_with_metadata(
                    clip,
                    include_mid_frame_reference=False,
                    include_start_frame=True,
                    include_end_frame=True,
                ),
            ),
            (
                "start_only",
                *self._build_payload_with_metadata(
                    clip,
                    include_mid_frame_reference=False,
                    include_start_frame=True,
                    include_end_frame=False,
                ),
            ),
        ]
        unique_candidates: list[tuple[str, dict[str, Any], str, list[dict[str, str]]]] = []
        seen_signatures: set[str] = set()
        for variant, payload, resolved_prompt, reference_bindings in candidates:
            signature = repr(payload)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            unique_candidates.append((variant, payload, resolved_prompt, reference_bindings))
        return unique_candidates

    def _build_submit_attempt_debug(
        self,
        *,
        variant: str,
        payload: dict[str, Any],
        response: httpx.Response,
    ) -> dict[str, Any]:
        response_json = self._safe_response_json(response)
        response_message = ""
        if isinstance(response_json, dict):
            response_message = self._extract_error_message(response_json)
        response_text = self._safe_response_text(response)
        return {
            "variant": variant,
            "status_code": response.status_code,
            "response_json": response_json,
            "response_text": response_text,
            "response_message": response_message,
            "request_summary": self._summarize_payload(payload),
        }

    def _safe_response_json(self, response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else {"payload": payload}

    def _safe_response_text(self, response: httpx.Response, limit: int = 1000) -> str:
        try:
            text = response.text.strip()
        except Exception:
            return ""
        if len(text) > limit:
            return text[: limit - 1] + "…"
        return text

    def _summarize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        content_summary: list[dict[str, Any]] = []
        for item in payload.get("content", []):
            summary: dict[str, Any] = {
                "type": item.get("type", ""),
                "role": item.get("role", "text"),
            }
            if item.get("type") == "text":
                summary["text_length"] = len(str(item.get("text", "")))
            elif item.get("type") == "image_url":
                summary["image_url"] = self._sanitize_image_url(
                    item.get("image_url", {}).get("url", "")
                )
            content_summary.append(summary)
        return {
            "model": payload.get("model"),
            "ratio": payload.get("ratio"),
            "duration": payload.get("duration"),
            "watermark": payload.get("watermark"),
            "content_count": len(content_summary),
            "content": content_summary,
        }

    def _sanitize_image_url(self, raw_url: str) -> str:
        if not raw_url:
            return ""
        parsed = urlparse(raw_url)
        if not parsed.netloc:
            return raw_url
        tail = parsed.path.split("/")[-1]
        return f"{parsed.scheme}://{parsed.netloc}/.../{tail}"
