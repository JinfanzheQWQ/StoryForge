from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.domains.video.contracts import SeedanceManifest, VideoProjectPackage
from storyforge.integrations.seedance import SeedanceExecutionReport
from storyforge.integrations.seedream import SeedreamExecutionReport


@dataclass(slots=True)
class VideoPipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    seedance_execution_path: Path
    rendered_clip_paths: list[Path]
    full_story_path: Path | None
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None
    seedance_execution: SeedanceExecutionReport


@dataclass(slots=True)
class CharacterImagePipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    character_seedream_execution_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None


@dataclass(slots=True)
class SceneImagePipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    character_seedream_execution_path: Path
    scene_seedream_execution_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None


@dataclass(slots=True)
class ImagePipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    character_seedream_execution_path: Path
    scene_seedream_execution_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None


@dataclass(slots=True)
class VideoRenderResult:
    output_dir: Path
    manifest_path: Path
    seedance_execution_path: Path
    rendered_clip_paths: list[Path]
    full_story_path: Path | None
    manifest: SeedanceManifest
    seedance_execution: SeedanceExecutionReport


@dataclass(slots=True)
class VideoPlanningArtifacts:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
