from __future__ import annotations

from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, write_json, write_text
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneImageTask,
    SeedanceManifest,
    VideoProjectPackage,
    VideoSegment,
)
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.ffmpeg_adapter import build_concat_list, build_concat_script
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.video_models import VideoPlanningArtifacts


def build_video_planning_artifacts(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = False,
) -> VideoPlanningArtifacts:
    backend = build_agent_backend(config, use_llm=use_llm)
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
    segment_plan_path = output_dir / "segment_plan.json"
    scene_images_path = output_dir / "scene_image_manifest.json"
    manifest_path = output_dir / "seedance_manifest.json"
    seedream_execution_path = output_dir / "seedream_execution.json"
    seedance_execution_path = output_dir / "seedance_execution.json"
    concat_script_path = output_dir / "ffmpeg_concat.sh"
    concat_list_path = output_dir / "concat_list.txt"
    full_story_output_path = output_dir / "rendered" / "full_story.mp4"
    workflow_trace_path = output_dir / "video_workflow_trace.json"

    write_json(character_bible_path, project_package.character_profiles)
    write_json(character_images_path, project_package.character_images)
    write_json(segment_plan_path, project_package.segments)
    write_json(scene_images_path, project_package.scene_images)
    write_json(manifest_path, manifest)
    write_text(
        concat_script_path,
        build_concat_script(manifest, output_path=str(full_story_output_path)),
    )
    write_text(concat_list_path, build_concat_list(manifest))
    write_json(workflow_trace_path, project_package.workflow_trace)

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        character_bible_path=character_bible_path,
        character_images_path=character_images_path,
        segment_plan_path=segment_plan_path,
        scene_images_path=scene_images_path,
        manifest_path=manifest_path,
        seedream_execution_path=seedream_execution_path,
        seedance_execution_path=seedance_execution_path,
        concat_script_path=concat_script_path,
        concat_list_path=concat_list_path,
        workflow_trace_path=workflow_trace_path,
        full_story_output_path=full_story_output_path,
        project_package=project_package,
        manifest=manifest,
    )


def load_video_planning_artifacts(output_dir: Path) -> VideoPlanningArtifacts:
    character_bible_path = output_dir / "character_visual_bible.json"
    character_images_path = output_dir / "character_image_manifest.json"
    segment_plan_path = output_dir / "segment_plan.json"
    scene_images_path = output_dir / "scene_image_manifest.json"
    manifest_path = output_dir / "seedance_manifest.json"
    seedream_execution_path = output_dir / "seedream_execution.json"
    seedance_execution_path = output_dir / "seedance_execution.json"
    concat_script_path = output_dir / "ffmpeg_concat.sh"
    concat_list_path = output_dir / "concat_list.txt"
    full_story_output_path = output_dir / "rendered" / "full_story.mp4"
    workflow_trace_path = output_dir / "video_workflow_trace.json"

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
            "Video planning artifacts are incomplete. Generate character images first. Missing: "
            + ", ".join(missing_files)
        )

    workflow_trace = read_json(workflow_trace_path) if workflow_trace_path.exists() else {}
    project_package = VideoProjectPackage(
        title=str(SeedanceManifest.from_dict(read_json(manifest_path)).title),
        character_profiles=[
            CharacterVisualProfile.from_dict(item)
            for item in read_json(character_bible_path)
        ],
        character_images=[
            CharacterImageTask.from_dict(item)
            for item in read_json(character_images_path)
        ],
        segments=[
            VideoSegment.from_dict(item)
            for item in read_json(segment_plan_path)
        ],
        scene_images=[
            SceneImageTask.from_dict(item)
            for item in read_json(scene_images_path)
        ],
        seedance_manifest=SeedanceManifest.from_dict(read_json(manifest_path)),
        workflow_trace=workflow_trace if isinstance(workflow_trace, dict) else {},
    )

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        character_bible_path=character_bible_path,
        character_images_path=character_images_path,
        segment_plan_path=segment_plan_path,
        scene_images_path=scene_images_path,
        manifest_path=manifest_path,
        seedream_execution_path=seedream_execution_path,
        seedance_execution_path=seedance_execution_path,
        concat_script_path=concat_script_path,
        concat_list_path=concat_list_path,
        workflow_trace_path=workflow_trace_path,
        full_story_output_path=full_story_output_path,
        project_package=project_package,
        manifest=project_package.seedance_manifest,
    )
