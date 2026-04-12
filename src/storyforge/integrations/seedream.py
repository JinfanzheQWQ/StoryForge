from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
from typing import Any

import httpx

from storyforge.core.config import SeedreamConfig
from storyforge.domains.video.contracts import CharacterImageTask, SceneImageTask, VideoProjectPackage


DEFAULT_SEEDREAM_BASE_URL = "https://operator.las.cn-beijing.volces.com/api/v1"
SEEDREAM_BASE_URL_ENV = "SEEDREAM_BASE_URL"


@dataclass(slots=True)
class SeedreamExecutionReport:
    submitted: bool
    generated_count: int
    failed_count: int
    note: str


class SeedreamClient:
    def __init__(self, config: SeedreamConfig) -> None:
        self.config = config
        self.api_key = os.getenv(config.api_key_env, "")

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
    ) -> SeedreamExecutionReport:
        preflight = self._build_preflight_report(force_submit=force_submit)
        if preflight is not None:
            return preflight

        missing_references = [
            item.character_name
            for item in project_package.character_images
            if item.use_as_reference and not item.generated_url
        ]
        if missing_references:
            return SeedreamExecutionReport(
                submitted=False,
                generated_count=0,
                failed_count=len(project_package.scene_images),
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

        with httpx.Client(timeout=120) as client:
            for task in project_package.scene_images:
                success = self._generate_scene_frames(
                    client,
                    task,
                    project_package.character_images,
                    scene_map,
                )
                generated_count += int(success) * 2
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
    ) -> bool:
        task.status = "running"
        try:
            reference_urls = self._resolve_reference_urls(task.reference_images, character_images)
            start_frame_url = self._resolve_continuity_start_frame(task, scene_map)
            if start_frame_url:
                self._materialize_reused_start_frame(task, scene_map, client, start_frame_url)
            else:
                start_frame_url = self._create_image(
                    client,
                    prompt=task.start_frame_prompt,
                    reference_images=reference_urls,
                )

            end_frame_references = self._merge_reference_urls(
                [start_frame_url] if start_frame_url else [],
                reference_urls,
            )
            end_frame_url = self._create_image(
                client,
                prompt=task.end_frame_prompt,
                reference_images=end_frame_references,
            )
            task.start_frame_url = start_frame_url
            task.end_frame_url = end_frame_url
            task.status = "completed"
            if self.config.download_outputs and start_frame_url and not task.reuse_previous_end_frame:
                self._download_image(client, start_frame_url, Path(task.start_frame_path))
            if self.config.download_outputs and end_frame_url:
                self._download_image(client, end_frame_url, Path(task.end_frame_path))
            return True
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            return False

    def _create_image(
        self,
        client: httpx.Client,
        prompt: str,
        reference_images: list[str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "prompt": prompt,
            "size": self.config.image_size,
            "response_format": self.config.response_format,
        }
        if reference_images:
            # Seedream's image-conditioning path accepts image inputs; we pass the
            # available references through directly so scene frames can stay close
            # to the approved character portraits.
            payload["image"] = reference_images if len(reference_images) > 1 else reference_images[0]

        last_error: Exception | None = None
        attempted_endpoints: list[str] = []
        for endpoint in self._candidate_endpoints():
            attempted_endpoints.append(endpoint)
            try:
                response = client.post(
                    endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                return self._extract_image_url(response.json())
            except Exception as exc:
                last_error = exc
                continue

        raise RuntimeError(
            "Seedream image generation failed "
            f"after trying {attempted_endpoints}: {last_error}"
        )

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

    def _apply_scene_urls_to_seedance_manifest(self, project_package: VideoProjectPackage) -> None:
        scene_map = {item.segment_id: item for item in project_package.scene_images}
        for clip in project_package.seedance_manifest.clips:
            scene = scene_map.get(clip.segment_id)
            if scene is None:
                continue
            clip.start_frame_url = scene.start_frame_url
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
