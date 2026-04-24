from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import os
import shutil
from typing import Any

import httpx

from storyforge.core.config import SeedreamConfig
from storyforge.domains.video.contracts import CharacterImageTask, SceneImageTask, VideoProjectPackage, VideoScene


DEFAULT_SEEDREAM_BASE_URL = "https://operator.las.cn-beijing.volces.com/api/v1"
SEEDREAM_BASE_URL_ENV = "SEEDREAM_BASE_URL"
SEEDREAM_MAX_FRAME_REFERENCE_IMAGES = 4
SEEDREAM_MAX_CHARACTER_REFERENCE_IMAGES = 2


@dataclass(slots=True)
class SeedreamExecutionReport:
    submitted: bool
    generated_count: int
    failed_count: int
    note: str


@dataclass(slots=True)
class SeedreamPayloadAttempt:
    label: str
    payload: dict[str, Any]
    reference_images: list[str]


class SeedreamClient:
    def __init__(self, config: SeedreamConfig) -> None:
        self.config = config
        self.api_key = os.getenv(config.api_key_env, "")
        self._last_request_info: dict[str, Any] = {}

    def generate_character_images(
        self,
        project_package: VideoProjectPackage,
        force_submit: bool = False,
    ) -> SeedreamExecutionReport:
        preflight = self._build_preflight_report(force_submit=force_submit)
        if preflight is not None:
            return preflight

        generated_count = 0
        failed_count = 0
        with httpx.Client(timeout=120) as client:
            for task in project_package.character_images:
                success = self._generate_character_image(client, task)
                generated_count += int(success)
                failed_count += int(not success)

        note = (
            "Seedream character image tasks executed successfully."
            if failed_count == 0
            else "Seedream character image generation completed with partial failures."
        )
        return SeedreamExecutionReport(
            submitted=True,
            generated_count=generated_count,
            failed_count=failed_count,
            note=note,
        )

    def generate_scene_images(
        self,
        project_package: VideoProjectPackage,
        force_submit: bool = False,
        segment_ids: set[str] | None = None,
    ) -> SeedreamExecutionReport:
        preflight = self._build_preflight_report(force_submit=force_submit)
        if preflight is not None:
            return preflight

        target_scene_tasks = self._select_scene_tasks(project_package, segment_ids)
        missing_references = [
            item.character_name
            for item in project_package.character_images
            if item.use_as_reference and not item.generated_url
        ]
        if missing_references:
            return SeedreamExecutionReport(
                submitted=False,
                generated_count=0,
                failed_count=len(target_scene_tasks),
                note=(
                    "Seedream scene generation requires completed character reference images first: "
                    + ", ".join(missing_references)
                ),
            )

        generated_count = 0
        failed_count = 0
        scene_map = {
            item.segment_id: item
            for item in project_package.scene_images
        }
        scene_lookup = {
            item.scene_id: item
            for item in project_package.scenes
            if item.scene_id
        }
        selected_scene_ids = {
            task.scene_id
            for task in target_scene_tasks
            if task.scene_id
        }
        failed_scene_ids: set[str] = set()

        with httpx.Client(timeout=120) as client:
            for scene_id in sorted(selected_scene_ids):
                scene = scene_lookup.get(scene_id)
                if scene is None:
                    continue
                success, generated_now = self._ensure_scene_master_frame(client, scene)
                self._sync_scene_master_to_scene_tasks(project_package.scene_images, scene)
                if generated_now:
                    generated_count += 1
                if not success:
                    failed_scene_ids.add(scene_id)

            for task in target_scene_tasks:
                scene = scene_lookup.get(task.scene_id)
                self._sync_scene_master_to_task(task, scene)
                if task.scene_id and task.scene_id in failed_scene_ids:
                    task.status = "failed"
                    task.error = (
                        scene.scene_master_frame_error
                        if scene is not None and scene.scene_master_frame_error
                        else "scene_master_frame generation failed."
                    )
                    failed_count += 1
                    continue
                success = self._generate_scene_frames(
                    client,
                    task,
                    project_package.character_images,
                    scene_map,
                    scene_lookup,
                )
                generated_count += self._planned_scene_frame_count(task) if success else 0
                failed_count += int(not success)

        self._apply_scene_urls_to_seedance_manifest(project_package)
        note = (
            "Seedream scene image tasks executed successfully."
            if failed_count == 0
            else "Seedream scene image generation completed with partial failures."
        )
        return SeedreamExecutionReport(
            submitted=True,
            generated_count=generated_count,
            failed_count=failed_count,
            note=note,
        )

    def generate_scene_master_frames(
        self,
        project_package: VideoProjectPackage,
        force_submit: bool = False,
        scene_ids: set[str] | None = None,
        force_regenerate: bool = False,
    ) -> SeedreamExecutionReport:
        preflight = self._build_preflight_report(force_submit=force_submit)
        if preflight is not None:
            return preflight

        target_scenes = self._select_scenes(project_package, scene_ids)
        generated_count = 0
        failed_count = 0

        with httpx.Client(timeout=120) as client:
            for scene in target_scenes:
                success, generated_now = self._ensure_scene_master_frame(
                    client,
                    scene,
                    force_regenerate=force_regenerate,
                )
                self._sync_scene_master_to_scene_tasks(project_package.scene_images, scene)
                generated_count += int(generated_now)
                failed_count += int(not success)

        self._apply_scene_urls_to_seedance_manifest(project_package)
        note = (
            "Seedream scene master frame tasks executed successfully."
            if failed_count == 0
            else "Seedream scene master frame generation completed with partial failures."
        )
        return SeedreamExecutionReport(
            submitted=True,
            generated_count=generated_count,
            failed_count=failed_count,
            note=note,
        )

    def generate_project_images(
        self,
        project_package: VideoProjectPackage,
        force_submit: bool = False,
    ) -> SeedreamExecutionReport:
        """
        Execute the actual Seedream image-generation API for both character portraits
        and scene start/end frames, then write the returned URLs back onto the task
        objects so later steps can consume them.
        """
        character_report = self.generate_character_images(
            project_package=project_package,
            force_submit=force_submit,
        )
        scene_report = self.generate_scene_images(
            project_package=project_package,
            force_submit=force_submit,
        )
        return self._merge_execution_reports(character_report, scene_report)

    def _select_scene_tasks(
        self,
        project_package: VideoProjectPackage,
        segment_ids: set[str] | None,
    ) -> list[SceneImageTask]:
        if not segment_ids:
            return list(project_package.scene_images)
        selected_tasks = [
            task
            for task in project_package.scene_images
            if task.segment_id in segment_ids
        ]
        missing_segments = sorted(segment_ids - {task.segment_id for task in selected_tasks})
        if missing_segments:
            raise ValueError(
                "Requested scene segments are not present in scene_image_manifest.json: "
                + ", ".join(missing_segments)
            )
        return selected_tasks

    def _select_scenes(
        self,
        project_package: VideoProjectPackage,
        scene_ids: set[str] | None,
    ) -> list[VideoScene]:
        if not scene_ids:
            return list(project_package.scenes)
        selected_scenes = [
            scene
            for scene in project_package.scenes
            if scene.scene_id in scene_ids
        ]
        missing_scenes = sorted(scene_ids - {scene.scene_id for scene in selected_scenes})
        if missing_scenes:
            raise ValueError(
                "Requested scenes are not present in scene_plan.json: "
                + ", ".join(missing_scenes)
            )
        return selected_scenes

    def _generate_character_image(self, client: httpx.Client, task: CharacterImageTask) -> bool:
        task.status = "running"
        try:
            image_url = self._create_image(client, prompt=task.prompt)
            task.generated_url = image_url
            task.status = "completed"
            if self.config.download_outputs and image_url:
                self._download_image(client, image_url, Path(task.output_path))
            return True
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            return False

    def _generate_scene_frames(
        self,
        client: httpx.Client,
        task: SceneImageTask,
        character_images: list[CharacterImageTask],
        scene_map: dict[str, SceneImageTask],
        scene_lookup: dict[str, VideoScene],
    ) -> bool:
        task.status = "running"
        try:
            scene = scene_lookup.get(task.scene_id)
            self._sync_scene_master_to_task(task, scene)
            scene_master_reference_urls = (
                [task.scene_master_frame_url]
                if task.scene_master_frame_url
                else []
            )
            reference_urls = self._resolve_reference_urls(task.reference_images, character_images)
            start_frame_url = self._resolve_continuity_start_frame(task, scene_map)
            if start_frame_url:
                task.start_frame_request_info = {
                    "provider": task.provider,
                    "variant": "reuse_previous_end_frame",
                    "payload": {
                        "mode": "reuse_previous_end_frame",
                        "source_segment_id": task.continuity_source_segment_id,
                        "reused_image_url": start_frame_url,
                    },
                    "reference_bindings": [
                        {
                            "label": "复用图",
                            "kind": "temporal_reuse",
                            "description": "未提交 Seedream，直接复用上一片段尾帧作为当前片段首帧。",
                            "url": start_frame_url,
                        }
                    ],
                }
                self._materialize_reused_start_frame(task, scene_map, client, start_frame_url)
            else:
                start_temporal_anchor_urls = self._resolve_start_temporal_anchor_urls(
                    task,
                    scene_map,
                )
                start_reference_urls, start_reference_bindings = self._build_frame_reference_bundle(
                    temporal_anchor_urls=start_temporal_anchor_urls,
                    scene_master_reference_urls=scene_master_reference_urls,
                    frame_character_names=task.start_frame_characters,
                    character_images=character_images,
                    fallback_urls=reference_urls,
                )
                self._last_request_info = {}
                start_frame_url = self._create_image(
                    client,
                    prompt=task.start_frame_prompt,
                    reference_images=start_reference_urls,
                )
                task.start_frame_request_info = self._snapshot_last_request_info(
                    provider=task.provider,
                    reference_bindings=start_reference_bindings,
                )

            mid_frame_url = ""
            task.mid_frame_request_info = {}
            if task.requires_mid_frame and task.mid_frame_prompt.strip():
                mid_frame_references, mid_frame_bindings = self._build_frame_reference_bundle(
                    temporal_anchor_urls=[start_frame_url] if start_frame_url else [],
                    scene_master_reference_urls=scene_master_reference_urls,
                    frame_character_names=task.mid_frame_characters,
                    character_images=character_images,
                    fallback_urls=reference_urls,
                )
                self._last_request_info = {}
                mid_frame_url = self._create_image(
                    client,
                    prompt=task.mid_frame_prompt,
                    reference_images=mid_frame_references,
                )
                task.mid_frame_request_info = self._snapshot_last_request_info(
                    provider=task.provider,
                    reference_bindings=mid_frame_bindings,
                )

            end_frame_references, end_frame_bindings = self._build_frame_reference_bundle(
                temporal_anchor_urls=(
                    [mid_frame_url]
                    if mid_frame_url
                    else ([start_frame_url] if start_frame_url else [])
                ),
                scene_master_reference_urls=scene_master_reference_urls,
                frame_character_names=task.end_frame_characters,
                character_images=character_images,
                fallback_urls=reference_urls,
            )
            self._last_request_info = {}
            end_frame_url = self._create_image(
                client,
                prompt=task.end_frame_prompt,
                reference_images=end_frame_references,
            )
            task.end_frame_request_info = self._snapshot_last_request_info(
                provider=task.provider,
                reference_bindings=end_frame_bindings,
            )
            task.start_frame_url = start_frame_url
            task.mid_frame_url = mid_frame_url
            task.end_frame_url = end_frame_url
            task.status = "completed"
            if self.config.download_outputs and start_frame_url and not task.reuse_previous_end_frame:
                self._download_image(client, start_frame_url, Path(task.start_frame_path))
            if self.config.download_outputs and mid_frame_url and task.mid_frame_path:
                self._download_image(client, mid_frame_url, Path(task.mid_frame_path))
            if self.config.download_outputs and end_frame_url:
                self._download_image(client, end_frame_url, Path(task.end_frame_path))
            return True
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            return False

    def _ensure_scene_master_frame(
        self,
        client: httpx.Client,
        scene: VideoScene,
        *,
        force_regenerate: bool = False,
    ) -> tuple[bool, bool]:
        if (
            not force_regenerate
            and scene.scene_master_frame_url
            and scene.scene_master_frame_status == "completed"
        ):
            return True, False
        previous_url = scene.scene_master_frame_url
        scene.scene_master_frame_status = "running"
        scene.scene_master_frame_error = ""
        try:
            self._last_request_info = {}
            master_frame_url = self._create_image(
                client,
                prompt=scene.scene_master_frame_prompt,
            )
            scene.scene_master_frame_url = master_frame_url
            scene.scene_master_frame_status = "completed"
            scene.scene_master_request_info = self._snapshot_last_request_info(
                provider="seedream",
                reference_bindings=[],
            )
            if self.config.download_outputs and master_frame_url and scene.scene_master_frame_path:
                self._download_image(client, master_frame_url, Path(scene.scene_master_frame_path))
            return True, True
        except Exception as exc:
            scene.scene_master_frame_status = "failed"
            scene.scene_master_frame_error = str(exc)
            if not previous_url:
                scene.scene_master_frame_url = ""
            return False, False

    def _sync_scene_master_to_task(
        self,
        task: SceneImageTask,
        scene: VideoScene | None,
    ) -> None:
        if scene is None:
            return
        task.scene_master_frame_prompt = scene.scene_master_frame_prompt
        task.scene_master_frame_path = scene.scene_master_frame_path
        task.scene_master_frame_url = scene.scene_master_frame_url
        task.scene_master_frame_status = scene.scene_master_frame_status
        task.scene_master_frame_error = scene.scene_master_frame_error

    def _sync_scene_master_to_scene_tasks(
        self,
        scene_tasks: list[SceneImageTask],
        scene: VideoScene,
    ) -> None:
        for task in scene_tasks:
            if task.scene_id != scene.scene_id:
                continue
            self._sync_scene_master_to_task(task, scene)

    def _create_image(
        self,
        client: httpx.Client,
        prompt: str,
        reference_images: list[str] | None = None,
    ) -> str:
        payload_attempts = self._payload_attempts(prompt, reference_images or [])
        last_error: Exception | None = None
        attempted_variants: list[str] = []
        self._last_request_info = {}
        for endpoint in self._candidate_endpoints():
            for payload_attempt in payload_attempts:
                attempted_variants.append(f"{endpoint} [{payload_attempt.label}]")
                try:
                    response = client.post(
                        endpoint,
                        json=payload_attempt.payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    response.raise_for_status()
                    self._last_request_info = {
                        "provider": "seedream",
                        "endpoint": endpoint,
                        "variant": payload_attempt.label,
                        "payload": copy.deepcopy(payload_attempt.payload),
                    }
                    return self._extract_image_url(response.json())
                except Exception as exc:
                    last_error = exc
                    continue

        raise RuntimeError(
            "Seedream image generation failed "
            f"after trying {attempted_variants}: {last_error}"
        )

    def _payload_attempts(
        self,
        prompt: str,
        reference_images: list[str],
    ) -> list[SeedreamPayloadAttempt]:
        base_payload = self._base_payload(prompt)
        attempts: list[SeedreamPayloadAttempt] = []
        seen_signatures: set[str] = set()
        for reference_variant in self._reference_image_candidates(reference_images):
            for field_label, field_payload in self._reference_field_payloads(reference_variant):
                payload = dict(base_payload)
                payload.update(field_payload)
                signature = self._payload_signature(payload)
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                attempts.append(
                    SeedreamPayloadAttempt(
                        label=f"{field_label}; refs={len(reference_variant)}",
                        payload=payload,
                        reference_images=list(reference_variant),
                    )
                )
        return attempts

    def _base_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "prompt": prompt,
            "size": self.config.image_size,
            "response_format": self.config.response_format,
            "watermark": self.config.watermark,
        }

    def _reference_image_candidates(self, reference_images: list[str]) -> list[list[str]]:
        normalized: list[str] = []
        for url in reference_images:
            normalized_url = url.strip()
            if normalized_url and normalized_url not in normalized:
                normalized.append(normalized_url)
        if not normalized:
            return [[]]

        candidates: list[list[str]] = [normalized]
        if len(normalized) > 2:
            candidates.append(normalized[:2])
        if len(normalized) > 1:
            candidates.append([normalized[0]])
            candidates.append([normalized[1]])

        deduped: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for candidate in candidates:
            signature = tuple(candidate)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(candidate)
        return deduped

    def _reference_field_payloads(
        self,
        reference_images: list[str],
    ) -> list[tuple[str, dict[str, Any]]]:
        if not reference_images:
            return [("text_only", {})]
        if len(reference_images) == 1:
            single_reference = reference_images[0]
            return [
                ("image_string", {"image": single_reference}),
                ("reference_images_string", {"reference_images": single_reference}),
                ("reference_images_list", {"reference_images": [single_reference]}),
            ]
        return [
            ("image_list", {"image": reference_images}),
            ("reference_images_list", {"reference_images": reference_images}),
            (
                "reference_images_objects",
                {"reference_images": [{"url": url} for url in reference_images]},
            ),
        ]

    def _payload_signature(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def _candidate_endpoints(self) -> list[str]:
        base = (
            os.getenv(SEEDREAM_BASE_URL_ENV)
            or self.config.base_url
            or DEFAULT_SEEDREAM_BASE_URL
        ).rstrip("/")
        if base.endswith("/api/v3"):
            return [f"{base}/images/generations"]
        if base.endswith("/images/generations"):
            return [base]
        if base.endswith("/api/v1/online"):
            return [f"{base}/images/generations", f"{base[:-7]}/images/generations"]
        if base.endswith("/api/v1"):
            return [f"{base}/images/generations", f"{base}/online/images/generations"]
        return [
            f"{base}/images/generations",
            f"{base}/api/v1/images/generations",
            f"{base}/api/v1/online/images/generations",
        ]

    def _extract_image_url(self, payload: dict[str, Any]) -> str:
        data = payload.get("data", payload)
        if isinstance(data, list) and data:
            return self._extract_item_url(data[0])
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list) and data["data"]:
                return self._extract_item_url(data["data"][0])
            if "images" in data and isinstance(data["images"], list) and data["images"]:
                return self._extract_item_url(data["images"][0])
            return self._extract_item_url(data)
        raise RuntimeError(f"Unexpected Seedream response payload: {payload}")

    def _extract_item_url(self, item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            for key in ("url", "image_url", "uri"):
                if item.get(key):
                    return str(item[key])
        raise RuntimeError(f"Unable to extract image URL from Seedream item: {item}")

    def _download_image(self, client: httpx.Client, image_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = client.get(image_url)
        response.raise_for_status()
        output_path.write_bytes(response.content)

    def _resolve_reference_urls(
        self,
        reference_paths: list[str],
        character_images: list[CharacterImageTask],
    ) -> list[str]:
        path_to_url = {
            item.output_path: item.generated_url
            for item in character_images
            if item.generated_url and item.use_as_reference
        }
        return [path_to_url[path] for path in reference_paths if path in path_to_url]

    def _resolve_character_reference_urls(
        self,
        character_names: list[str],
        character_images: list[CharacterImageTask],
        *,
        fallback_urls: list[str],
    ) -> list[str]:
        if not character_names:
            # A single available reference is safe as a legacy fallback; multiple
            # references would reintroduce off-frame characters into single-person frames.
            return list(fallback_urls) if len(fallback_urls) == 1 else []

        urls: list[str] = []
        for name in character_names:
            for item in character_images:
                if (
                    item.character_name == name
                    and item.generated_url
                    and item.use_as_reference
                    and item.generated_url not in urls
                ):
                    urls.append(item.generated_url)
        if urls:
            return urls
        return list(fallback_urls)

    def _build_frame_reference_urls(
        self,
        *,
        temporal_anchor_urls: list[str],
        scene_master_reference_urls: list[str],
        frame_character_names: list[str],
        character_images: list[CharacterImageTask],
        fallback_urls: list[str],
    ) -> list[str]:
        return self._build_frame_reference_bundle(
            temporal_anchor_urls=temporal_anchor_urls,
            scene_master_reference_urls=scene_master_reference_urls,
            frame_character_names=frame_character_names,
            character_images=character_images,
            fallback_urls=fallback_urls,
        )[0]

    def _build_frame_reference_bundle(
        self,
        *,
        temporal_anchor_urls: list[str],
        scene_master_reference_urls: list[str],
        frame_character_names: list[str],
        character_images: list[CharacterImageTask],
        fallback_urls: list[str],
    ) -> tuple[list[str], list[dict[str, str]]]:
        # Keep frame references intentionally sparse and stable: scene master first,
        # then only the characters actually visible in this frame, with any temporal
        # continuity anchor appended last as an extra hint rather than the primary ref.
        character_reference_urls = self._resolve_character_reference_urls(
            frame_character_names,
            character_images,
            fallback_urls=fallback_urls,
        )[:SEEDREAM_MAX_CHARACTER_REFERENCE_IMAGES]
        merged = self._merge_reference_url_groups(
            scene_master_reference_urls,
            character_reference_urls,
            temporal_anchor_urls,
        )
        ordered_urls = merged[:SEEDREAM_MAX_FRAME_REFERENCE_IMAGES]
        return ordered_urls, self._describe_reference_bindings(
            ordered_urls,
            scene_master_reference_urls=scene_master_reference_urls,
            character_reference_urls=character_reference_urls,
            temporal_anchor_urls=temporal_anchor_urls,
        )

    def _describe_reference_bindings(
        self,
        ordered_urls: list[str],
        *,
        scene_master_reference_urls: list[str],
        character_reference_urls: list[str],
        temporal_anchor_urls: list[str],
    ) -> list[dict[str, str]]:
        scene_master_set = {str(url).strip() for url in scene_master_reference_urls if str(url).strip()}
        character_set = {str(url).strip() for url in character_reference_urls if str(url).strip()}
        temporal_set = {str(url).strip() for url in temporal_anchor_urls if str(url).strip()}
        bindings: list[dict[str, str]] = []
        for index, raw_url in enumerate(ordered_urls, start=1):
            url = str(raw_url).strip()
            if not url:
                continue
            if url in scene_master_set:
                kind = "scene_master"
                description = "场景母图参考，用于锁定当前 scene 的环境、空间和光线基线。"
            elif url in character_set:
                kind = "character"
                description = "角色参考图，用于锁定当前帧真实出镜角色的定妆、服装和外观。"
            elif url in temporal_set:
                kind = "temporal"
                description = "时间承接参考，用上一帧或上一段画面锁定动作与镜头衔接。"
            else:
                kind = "reference"
                description = "补充参考图。"
            bindings.append(
                {
                    "label": f"图片{index}",
                    "kind": kind,
                    "description": description,
                    "url": url,
                }
            )
        return bindings

    def _snapshot_last_request_info(
        self,
        *,
        provider: str,
        reference_bindings: list[dict[str, str]],
    ) -> dict[str, Any]:
        snapshot = copy.deepcopy(self._last_request_info)
        if not snapshot:
            return {}
        snapshot["provider"] = snapshot.get("provider") or provider
        snapshot["reference_bindings"] = copy.deepcopy(reference_bindings)
        return snapshot

    def _apply_scene_urls_to_seedance_manifest(self, project_package: VideoProjectPackage) -> None:
        scene_map = {item.segment_id: item for item in project_package.scene_images}
        for clip in project_package.seedance_manifest.clips:
            scene = scene_map.get(clip.segment_id)
            if scene is None:
                continue
            clip.start_frame_url = scene.start_frame_url
            clip.mid_frame_url = scene.mid_frame_url
            clip.end_frame_url = scene.end_frame_url

    def _resolve_continuity_start_frame(
        self,
        task: SceneImageTask,
        scene_map: dict[str, SceneImageTask],
    ) -> str:
        if not task.reuse_previous_end_frame or not task.continuity_source_segment_id:
            return ""
        previous_task = scene_map.get(task.continuity_source_segment_id)
        if previous_task is None:
            return ""
        return previous_task.end_frame_url

    def _resolve_start_temporal_anchor_urls(
        self,
        task: SceneImageTask,
        scene_map: dict[str, SceneImageTask],
    ) -> list[str]:
        source_segment_id = str(task.scene_transition_source_segment_id or "").strip()
        if not source_segment_id:
            return []
        previous_task = scene_map.get(source_segment_id)
        if previous_task is None:
            return []
        temporal_url = str(previous_task.end_frame_url or "").strip()
        return [temporal_url] if temporal_url else []

    def _materialize_reused_start_frame(
        self,
        task: SceneImageTask,
        scene_map: dict[str, SceneImageTask],
        client: httpx.Client,
        start_frame_url: str,
    ) -> None:
        if not self.config.download_outputs:
            return
        previous_task = scene_map.get(task.continuity_source_segment_id)
        if previous_task is None:
            return
        source_path = Path(previous_task.end_frame_path)
        target_path = Path(task.start_frame_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.exists():
            shutil.copyfile(source_path, target_path)
            return
        response = client.get(start_frame_url)
        response.raise_for_status()
        target_path.write_bytes(response.content)

    def _merge_reference_urls(
        self,
        primary: list[str],
        secondary: list[str],
    ) -> list[str]:
        merged: list[str] = []
        for url in primary + secondary:
            if url and url not in merged:
                merged.append(url)
        return merged

    def _merge_reference_url_groups(
        self,
        *groups: list[str],
    ) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for url in group:
                if url and url not in merged:
                    merged.append(url)
        return merged

    def _planned_scene_frame_count(self, task: SceneImageTask) -> int:
        return 3 if task.requires_mid_frame else 2

    def _build_preflight_report(
        self,
        force_submit: bool,
    ) -> SeedreamExecutionReport | None:
        if not self.config.enabled:
            return SeedreamExecutionReport(
                submitted=False,
                generated_count=0,
                failed_count=0,
                note="Seedream is disabled; only manifests were generated.",
            )
        if not (force_submit or self.config.auto_submit):
            return SeedreamExecutionReport(
                submitted=False,
                generated_count=0,
                failed_count=0,
                note="Seedream execution skipped; only manifests were generated.",
            )
        if not self.api_key:
            return SeedreamExecutionReport(
                submitted=False,
                generated_count=0,
                failed_count=0,
                note="Seedream API key is missing; only manifests were generated.",
            )
        return None

    def _merge_execution_reports(
        self,
        character_report: SeedreamExecutionReport,
        scene_report: SeedreamExecutionReport,
    ) -> SeedreamExecutionReport:
        return SeedreamExecutionReport(
            submitted=character_report.submitted or scene_report.submitted,
            generated_count=character_report.generated_count + scene_report.generated_count,
            failed_count=character_report.failed_count + scene_report.failed_count,
            note=f"characters: {character_report.note} | scenes: {scene_report.note}",
        )
