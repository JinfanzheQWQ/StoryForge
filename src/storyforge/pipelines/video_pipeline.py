from __future__ import annotations

from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, write_json, write_text
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import SeedanceManifest
from storyforge.integrations.ffmpeg_adapter import (
    build_concat_list,
    build_concat_script,
    concat_manifest_clips,
)
from storyforge.integrations.seedance import SeedanceClient, SeedanceExecutionReport
from storyforge.integrations.seedream import SeedreamClient
from storyforge.pipelines.video_models import (
    CharacterImagePipelineResult,
    ImagePipelineResult,
    SceneImagePipelineResult,
    VideoPipelineResult,
    VideoPlanningArtifacts,
    VideoRenderResult,
)
from storyforge.pipelines.video_planning import (
    build_video_planning_artifacts,
    load_video_planning_artifacts,
)
from storyforge.pipelines.video_support import (
    merge_seedream_execution_reports,
    read_seedream_execution_report,
    should_concat_rendered_clips,
    should_skip_seedance_after_seedream,
    validate_manifest_ready_for_video,
)


def run_video_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = False,
    submit_seedance: bool = False,
) -> VideoPipelineResult:
    image_result = run_image_pipeline(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=output_root,
        use_llm=use_llm,
        submit_images=submit_seedance,
    )

    if should_skip_seedance_after_seedream(submit_seedance, image_result.seedream_execution):
        seedance_execution = SeedanceExecutionReport(
            submitted=False,
            manifest_title=image_result.manifest.title,
            completed_count=0,
            failed_count=0,
            pending_count=len(image_result.manifest.clips),
            note="Seedance skipped because Seedream did not generate all required frame images.",
        )
        seedance_execution_path = image_result.output_dir / "seedance_execution.json"
        write_json(seedance_execution_path, seedance_execution)
        return VideoPipelineResult(
            output_dir=image_result.output_dir,
            character_bible_path=image_result.character_bible_path,
            character_images_path=image_result.character_images_path,
            segment_plan_path=image_result.segment_plan_path,
            scene_images_path=image_result.scene_images_path,
            manifest_path=image_result.manifest_path,
            seedream_execution_path=image_result.seedream_execution_path,
            seedance_execution_path=seedance_execution_path,
            concat_script_path=image_result.concat_script_path,
            concat_list_path=image_result.concat_list_path,
            workflow_trace_path=image_result.workflow_trace_path,
            rendered_clip_paths=[],
            full_story_path=None,
            project_package=image_result.project_package,
            manifest=image_result.manifest,
            seedream_execution=image_result.seedream_execution,
            seedance_execution=seedance_execution,
        )

    video_render_result = run_video_render_pipeline(
        config=config,
        project_root=project_root,
        output_root=image_result.output_dir,
        submit_seedance=submit_seedance,
    )
    return VideoPipelineResult(
        output_dir=image_result.output_dir,
        character_bible_path=image_result.character_bible_path,
        character_images_path=image_result.character_images_path,
        segment_plan_path=image_result.segment_plan_path,
        scene_images_path=image_result.scene_images_path,
        manifest_path=video_render_result.manifest_path,
        seedream_execution_path=image_result.seedream_execution_path,
        seedance_execution_path=video_render_result.seedance_execution_path,
        concat_script_path=video_render_result.concat_script_path,
        concat_list_path=video_render_result.concat_list_path,
        workflow_trace_path=image_result.workflow_trace_path,
        rendered_clip_paths=video_render_result.rendered_clip_paths,
        full_story_path=video_render_result.full_story_path,
        project_package=image_result.project_package,
        manifest=video_render_result.manifest,
        seedream_execution=image_result.seedream_execution,
        seedance_execution=video_render_result.seedance_execution,
    )


def run_image_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = False,
    submit_images: bool = True,
) -> ImagePipelineResult:
    character_result = run_character_image_pipeline(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=output_root,
        use_llm=use_llm,
        submit_characters=submit_images,
    )

    scene_result = run_scene_image_pipeline(
        config=config,
        project_root=project_root,
        output_root=character_result.output_dir,
        submit_scenes=submit_images,
    )

    return ImagePipelineResult(
        output_dir=scene_result.output_dir,
        character_bible_path=scene_result.character_bible_path,
        character_images_path=scene_result.character_images_path,
        segment_plan_path=scene_result.segment_plan_path,
        scene_images_path=scene_result.scene_images_path,
        manifest_path=scene_result.manifest_path,
        seedream_execution_path=scene_result.seedream_execution_path,
        character_seedream_execution_path=scene_result.character_seedream_execution_path,
        scene_seedream_execution_path=scene_result.scene_seedream_execution_path,
        concat_script_path=scene_result.concat_script_path,
        concat_list_path=scene_result.concat_list_path,
        workflow_trace_path=scene_result.workflow_trace_path,
        project_package=scene_result.project_package,
        manifest=scene_result.manifest,
        seedream_execution=scene_result.seedream_execution,
    )


def run_character_image_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = False,
    submit_characters: bool = True,
) -> CharacterImagePipelineResult:
    planning = build_video_planning_artifacts(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=output_root,
        use_llm=use_llm,
    )
    seedream_client = SeedreamClient(config.seedream)
    character_execution = seedream_client.generate_character_images(
        planning.project_package,
        force_submit=submit_characters,
    )
    aggregate_execution_path = planning.output_dir / "seedream_execution.json"
    character_execution_path = planning.output_dir / "seedream_character_execution.json"

    write_json(planning.character_images_path, planning.project_package.character_images)
    write_json(planning.scene_images_path, planning.project_package.scene_images)
    write_json(planning.manifest_path, planning.manifest)
    write_json(character_execution_path, character_execution)
    write_json(aggregate_execution_path, character_execution)

    return CharacterImagePipelineResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        seedream_execution_path=aggregate_execution_path,
        character_seedream_execution_path=character_execution_path,
        concat_script_path=planning.concat_script_path,
        concat_list_path=planning.concat_list_path,
        workflow_trace_path=planning.workflow_trace_path,
        project_package=planning.project_package,
        manifest=planning.manifest,
        seedream_execution=character_execution,
    )


def run_scene_image_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    submit_scenes: bool = True,
) -> SceneImagePipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    seedream_client = SeedreamClient(config.seedream)
    scene_execution = seedream_client.generate_scene_images(
        planning.project_package,
        force_submit=submit_scenes,
    )

    aggregate_execution_path = output_dir / "seedream_execution.json"
    character_execution_path = output_dir / "seedream_character_execution.json"
    scene_execution_path = output_dir / "seedream_scene_execution.json"
    character_execution = read_seedream_execution_report(character_execution_path)
    combined_execution = merge_seedream_execution_reports(character_execution, scene_execution)

    write_json(planning.character_images_path, planning.project_package.character_images)
    write_json(planning.scene_images_path, planning.project_package.scene_images)
    write_json(planning.manifest_path, planning.manifest)
    write_json(scene_execution_path, scene_execution)
    write_json(aggregate_execution_path, combined_execution)

    return SceneImagePipelineResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        seedream_execution_path=aggregate_execution_path,
        character_seedream_execution_path=character_execution_path,
        scene_seedream_execution_path=scene_execution_path,
        concat_script_path=planning.concat_script_path,
        concat_list_path=planning.concat_list_path,
        workflow_trace_path=planning.workflow_trace_path,
        project_package=planning.project_package,
        manifest=planning.manifest,
        seedream_execution=combined_execution,
    )


def run_video_render_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    submit_seedance: bool = True,
) -> VideoRenderResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    manifest_path = output_dir / "seedance_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Seedance manifest not found at {manifest_path}. Generate images first."
        )

    manifest = SeedanceManifest.from_dict(read_json(manifest_path))
    if submit_seedance or config.seedance.auto_submit:
        validate_manifest_ready_for_video(manifest)
    seedance_client = SeedanceClient(config.seedance)
    seedance_execution = seedance_client.execute_manifest(
        manifest,
        force_submit=submit_seedance,
    )

    seedance_execution_path = output_dir / "seedance_execution.json"
    concat_script_path = output_dir / "ffmpeg_concat.sh"
    concat_list_path = output_dir / "concat_list.txt"
    full_story_output_path = output_dir / "rendered" / "full_story.mp4"

    write_json(manifest_path, manifest)
    write_json(seedance_execution_path, seedance_execution)
    write_text(
        concat_script_path,
        build_concat_script(manifest, output_path=str(full_story_output_path)),
    )
    write_text(concat_list_path, build_concat_list(manifest))

    rendered_clip_paths = [
        Path(clip.downloaded_path)
        for clip in manifest.clips
        if clip.downloaded_path
    ]

    full_story_path = None
    if should_concat_rendered_clips(manifest, seedance_execution):
        full_story_path = concat_manifest_clips(
            manifest=manifest,
            concat_list_path=concat_list_path,
            output_path=full_story_output_path,
        )

    return VideoRenderResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        seedance_execution_path=seedance_execution_path,
        concat_script_path=concat_script_path,
        concat_list_path=concat_list_path,
        rendered_clip_paths=rendered_clip_paths,
        full_story_path=full_story_path,
        manifest=manifest,
        seedance_execution=seedance_execution,
    )


__all__ = [
    "CharacterImagePipelineResult",
    "ImagePipelineResult",
    "SceneImagePipelineResult",
    "VideoPipelineResult",
    "VideoPlanningArtifacts",
    "VideoRenderResult",
    "run_character_image_pipeline",
    "run_image_pipeline",
    "run_scene_image_pipeline",
    "run_video_pipeline",
    "run_video_render_pipeline",
]
