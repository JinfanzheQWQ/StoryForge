from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import time
from typing import Any

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


class SeedanceClient:
    def __init__(self, config: SeedanceConfig) -> None:
        self.config = config
        self.api_key = os.getenv(config.api_key_env, "")

    async def submit_manifest(
        self,
        manifest: SeedanceManifest,
        force_submit: bool = False,
    ) -> SeedanceSubmission:
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
            for clip in manifest.clips:
                payload = self.build_payload(clip)
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
    ) -> SeedanceExecutionReport:
        """
        Submit each clip, poll it to a terminal status, and optionally download the
        generated mp4 back into the project output directory.
        """
        if not self.config.enabled:
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(manifest.clips),
                note="Seedance is disabled; manifest generated only.",
            )
        if not (force_submit or self.config.auto_submit):
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(manifest.clips),
                note="Seedance execution skipped; manifest generated only.",
            )
        if not self.api_key:
            return SeedanceExecutionReport(
                submitted=False,
                manifest_title=manifest.title,
                completed_count=0,
                failed_count=0,
                pending_count=len(manifest.clips),
                note="Seedance API key is missing; manifest generated only.",
            )

        clip_results: list[SeedanceClipExecution] = []
        completed_count = 0
        failed_count = 0
        pending_count = 0

        with httpx.Client(timeout=120) as client:
            for clip in manifest.clips:
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

    def build_payload(self, clip: SeedanceClipTask) -> dict[str, Any]:
        if not SEEDANCE_MIN_DURATION_SECONDS <= clip.duration_seconds <= SEEDANCE_MAX_DURATION_SECONDS:
            raise ValueError(
                "Seedance duration must be between "
                f"{SEEDANCE_MIN_DURATION_SECONDS} and {SEEDANCE_MAX_DURATION_SECONDS} seconds, "
                f"got {clip.duration_seconds} for segment {clip.segment_id}."
            )
        content: list[dict[str, Any]] = [{"type": "text", "text": clip.prompt}]

        # Live endpoint validation showed that image-conditioned requests must use
        # `first_frame` / `last_frame` for image roles, while text items carry no role.
        if clip.start_frame_url:
            content.append(
                {
                    "role": "first_frame",
                    "type": "image_url",
                    "image_url": {"url": clip.start_frame_url},
                }
            )
        if clip.end_frame_url:
            content.append(
                {
                    "role": "last_frame",
                    "type": "image_url",
                    "image_url": {"url": clip.end_frame_url},
                }
            )

        return {
            "model": self.config.model,
            "content": content,
            "ratio": clip.aspect_ratio,
            "duration": clip.duration_seconds,
            "watermark": self.config.watermark,
        }

    def _submit_clip(self, client: httpx.Client, clip: SeedanceClipTask) -> str:
        payload = self.build_payload(clip)
        endpoint = self._task_creation_endpoint()
        try:
            response = client.post(
                endpoint,
                json=payload,
                headers=self._request_headers(),
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Seedance task submit failed at {endpoint}: {exc}") from exc
        body = response.json()
        task_id = self._extract_task_id(body)
        if not task_id:
            raise RuntimeError(f"Seedance task id missing from response: {body}")
        clip.remote_task_id = task_id
        clip.submit_status = "submitted"
        clip.remote_status = "submitted"
        return task_id

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
