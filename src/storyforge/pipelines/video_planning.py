from __future__ import annotations

from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, write_json
from storyforge.domains.novel.contracts import NovelPackage, StorySourcePackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneImageTask,
    SeedanceManifest,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.schemas import VideoSegmentPlanSchema
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.video_models import VideoPlanningArtifacts


def build_video_planning_artifacts(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> VideoPlanningArtifacts:
    backend = build_agent_backend(
        config,
        use_llm=use_llm,
        provider=llm_provider,
        model=llm_model,
    )
    service = NovelToVideoService(
        backend=backend,
        segment_duration_seconds=config.video.segment_duration_seconds,
        aspect_ratio=config.video.aspect_ratio,
        fps=config.video.fps,
        character_image_provider=config.video.character_image_provider,
        scene_image_provider=config.video.scene_image_provider,
        seedance_config=config.seedance,
    )

    output_dir = output_root or (project_root / config.paths.output_dir)
    project_package = service.build_video_project(novel_package, output_dir=str(output_dir))
    manifest = project_package.seedance_manifest

    character_bible_path = output_dir / "character_visual_bible.json"
    character_images_path = output_dir / "character_image_manifest.json"
    scene_plan_path = output_dir / "scene_plan.json"
    segment_plan_path = output_dir / "segment_plan.json"
    scene_images_path = output_dir / "scene_image_manifest.json"
    manifest_path = output_dir / "seedance_manifest.json"

    write_json(character_bible_path, project_package.character_profiles)
    write_json(character_images_path, project_package.character_images)
    write_json(scene_plan_path, {"scenes": project_package.scenes})
    write_json(segment_plan_path, project_package.segments)
    write_json(scene_images_path, project_package.scene_images)
    write_json(manifest_path, manifest)

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        character_bible_path=character_bible_path,
        character_images_path=character_images_path,
        scene_plan_path=scene_plan_path,
        segment_plan_path=segment_plan_path,
        scene_images_path=scene_images_path,
        manifest_path=manifest_path,
        project_package=project_package,
        manifest=manifest,
    )


def load_video_planning_artifacts(output_dir: Path) -> VideoPlanningArtifacts:
    character_bible_path = output_dir / "character_visual_bible.json"
    character_images_path = output_dir / "character_image_manifest.json"
    scene_plan_path = output_dir / "scene_plan.json"
    segment_plan_path = output_dir / "segment_plan.json"
    scene_images_path = output_dir / "scene_image_manifest.json"
    manifest_path = output_dir / "seedance_manifest.json"

    required_paths = {
        "character_visual_bible.json": character_bible_path,
        "character_image_manifest.json": character_images_path,
        "segment_plan.json": segment_plan_path,
        "scene_image_manifest.json": scene_images_path,
        "seedance_manifest.json": manifest_path,
    }
    missing_files = [name for name, path in required_paths.items() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            "Video planning artifacts are incomplete. Generate structured story information first. Missing: "
            + ", ".join(missing_files)
        )

    manifest = SeedanceManifest.from_dict(read_json(manifest_path))
    scene_plan = _load_scene_plan(scene_plan_path, segment_plan_path)

    project_package = VideoProjectPackage(
        title=_resolve_video_project_title(output_dir, manifest),
        character_profiles=[
            CharacterVisualProfile.from_dict(item)
            for item in read_json(character_bible_path)
        ],
        character_images=[
            CharacterImageTask.from_dict(item)
            for item in read_json(character_images_path)
        ],
        scenes=[
            VideoScene.from_dict(item.model_dump())
            for item in scene_plan.scenes
        ],
        segments=[VideoSegment.from_dict(item.model_dump()) for item in scene_plan.segments],
        scene_images=[
            SceneImageTask.from_dict(item)
            for item in read_json(scene_images_path)
        ],
        seedance_manifest=manifest,
        workflow_trace={},
    )

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        character_bible_path=character_bible_path,
        character_images_path=character_images_path,
        scene_plan_path=scene_plan_path,
        segment_plan_path=segment_plan_path,
        scene_images_path=scene_images_path,
        manifest_path=manifest_path,
        project_package=project_package,
        manifest=project_package.seedance_manifest,
    )


def _resolve_video_project_title(output_dir: Path, manifest: SeedanceManifest) -> str:
    novel_package_path = output_dir / "novel_package.json"
    if novel_package_path.exists():
        payload = read_json(novel_package_path)
        if isinstance(payload, dict):
            outline = payload.get("outline")
            if isinstance(outline, dict):
                title = str(outline.get("title", "")).strip()
                if title:
                    return title

    story_source_path = output_dir / "story_source.json"
    if story_source_path.exists():
        payload = read_json(story_source_path)
        if isinstance(payload, dict):
            title = StorySourcePackage.from_dict(payload).title.strip()
            if title:
                return title

    manifest_title = manifest.title.strip()
    if manifest_title and manifest_title not in {"segment_video_manifest", "seedance_manifest"}:
        return manifest_title
    return output_dir.name


def _load_scene_plan(scene_plan_path: Path, segment_plan_path: Path) -> VideoSegmentPlanSchema:
    if scene_plan_path.exists():
        payload = read_json(scene_plan_path)
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict) and "segments" in payload[0]:
                return VideoSegmentPlanSchema.model_validate({"scenes": payload})
            return VideoSegmentPlanSchema.model_validate({"segments": payload})
        return VideoSegmentPlanSchema.model_validate(payload)

    segment_payload = read_json(segment_plan_path)
    return VideoSegmentPlanSchema.model_validate({"segments": segment_payload})
