from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path
import os
from typing import Any

import httpx

from storyforge.core.config import SeedreamConfig
from storyforge.domains.video.contracts import CharacterImageTask, SceneImageTask, VideoProjectPackage, VideoScene


DEFAULT_SEEDREAM_BASE_URL = "https://operator.las.cn-beijing.volces.com/api/v1"
SEEDREAM_BASE_URL_ENV = "SEEDREAM_BASE_URL"
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
        character_names: set[str] | None = None,
    ) -> SeedreamExecutionReport:
        preflight = self._build_preflight_report(force_submit=force_submit)
        if preflight is not None:
            return preflight

        target_tasks = self._select_character_tasks(project_package, character_names)

        generated_count = 0
        failed_count = 0
        with httpx.Client(timeout=120) as client:
            for task in target_tasks:
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

    def _select_character_tasks(
        self,
        project_package: VideoProjectPackage,
        character_names: set[str] | None,
    ) -> list[CharacterImageTask]:
        if not character_names:
            return list(project_package.character_images)
        selected_tasks = [
            task
            for task in project_package.character_images
            if task.character_name in character_names
        ]
        missing_names = sorted(character_names - {task.character_name for task in selected_tasks})
        if missing_names:
            raise ValueError(
                "Requested characters are not present in character_image_manifest.json: "
                + ", ".join(missing_names)
            )
        return selected_tasks

    def generate_scene_images(
        self,
        project_package: VideoProjectPackage,
        force_submit: bool = False,
        segment_ids: set[str] | None = None,
    ) -> SeedreamExecutionReport:
        scene_ids = {
            task.scene_id
            for task in self._select_scene_tasks(project_package, segment_ids)
            if task.scene_id
        }
        return self.generate_scene_master_frames(
            project_package,
            force_submit=force_submit,
            scene_ids=scene_ids or None,
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
            self._last_request_info = {}
            image_url = self._create_image(client, prompt=task.prompt)
            task.request_info = self._snapshot_last_request_info(
                provider=task.provider,
                reference_bindings=[],
            )
            has_current_image = bool(str(task.generated_url or "").strip()) or Path(task.output_path).is_file()
            if has_current_image:
                task.candidate_generated_url = image_url
                task.status = "candidate_ready"
                if self.config.download_outputs and image_url:
                    candidate_path = self._candidate_character_image_path(Path(task.output_path))
                    task.candidate_output_path = str(candidate_path)
                    self._download_image(client, image_url, candidate_path)
            else:
                task.generated_url = image_url
                task.candidate_generated_url = ""
                task.candidate_output_path = ""
                task.status = "completed"
                if self.config.download_outputs and image_url:
                    self._download_image(client, image_url, Path(task.output_path))
            return True
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            return False

    def _candidate_character_image_path(self, output_path: Path) -> Path:
        candidate_dir = output_path.parent / "_candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        return candidate_dir / output_path.name

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
        character_url_by_path = {
            item.output_path: item.generated_url
            for item in project_package.character_images
            if item.output_path and item.generated_url
        }
        character_url_by_name = {
            item.character_name: item.generated_url
            for item in project_package.character_images
            if item.character_name and item.generated_url
        }
        for clip in project_package.seedance_manifest.clips:
            scene = scene_map.get(clip.segment_id)
            if scene is not None:
                clip.scene_master_path = clip.scene_master_path or scene.scene_master_frame_path
                clip.scene_master_url = clip.scene_master_url or scene.scene_master_frame_url
            character_urls = [
                character_url_by_path.get(path, "")
                for path in clip.character_image_paths
            ]
            if not any(character_urls):
                character_urls = [
                    character_url_by_name.get(name, "")
                    for name in clip.visible_characters
            ]
            clip.character_image_urls = [url for url in character_urls if url]

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
