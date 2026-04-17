from __future__ import annotations

from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, to_jsonable, write_json
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import SceneImageTask, SeedanceClipTask, SeedanceManifest, VideoSegment
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.llm import build_agent_backend
from storyforge.integrations.ffmpeg_adapter import (
    concat_manifest_clips,
)
from storyforge.integrations.seedance import SeedanceClient, SeedanceExecutionReport
from storyforge.integrations.seedream import SeedreamClient
from storyforge.pipelines.continuity import write_continuity_report
from storyforge.pipelines.video_models import (
    CharacterImagePipelineResult,
    ContinuityRepairResult,
    ImagePipelineResult,
    SceneImagePipelineResult,
    VideoPipelineResult,
    VideoPlanningArtifacts,
    VideoMergeResult,
    VideoRenderResult,
)
from storyforge.pipelines.video_planning import (
    load_video_planning_artifacts,
    load_seedance_manifest,
    resolve_video_planning_paths,
)
from storyforge.pipelines.video_support import (
    merge_seedream_execution_reports,
    read_seedream_execution_report,
    resolve_rendered_manifest_clips,
    resolve_selected_manifest_clips,
    should_skip_seedance_after_seedream,
    validate_manifest_ready_for_video,
)


def run_video_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    submit_seedance: bool = False,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
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
            scene_plan_path=image_result.scene_plan_path,
            segment_plan_path=image_result.segment_plan_path,
            scene_images_path=image_result.scene_images_path,
            manifest_path=image_result.manifest_path,
            seedream_execution_path=image_result.seedream_execution_path,
            seedance_execution_path=seedance_execution_path,
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
        continuity_review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    return VideoPipelineResult(
        output_dir=image_result.output_dir,
        character_bible_path=image_result.character_bible_path,
        character_images_path=image_result.character_images_path,
        scene_plan_path=image_result.scene_plan_path,
        segment_plan_path=image_result.segment_plan_path,
        scene_images_path=image_result.scene_images_path,
        manifest_path=video_render_result.manifest_path,
        seedream_execution_path=image_result.seedream_execution_path,
        seedance_execution_path=video_render_result.seedance_execution_path,
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
    use_llm: bool = True,
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
        scene_plan_path=scene_result.scene_plan_path,
        segment_plan_path=scene_result.segment_plan_path,
        scene_images_path=scene_result.scene_images_path,
        manifest_path=scene_result.manifest_path,
        seedream_execution_path=scene_result.seedream_execution_path,
        character_seedream_execution_path=scene_result.character_seedream_execution_path,
        scene_seedream_execution_path=scene_result.scene_seedream_execution_path,
        project_package=scene_result.project_package,
        manifest=scene_result.manifest,
        seedream_execution=scene_result.seedream_execution,
    )


def run_character_image_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    submit_characters: bool = True,
) -> CharacterImagePipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    seedream_client = SeedreamClient(config.seedream)
    character_execution = seedream_client.generate_character_images(
        planning.project_package,
        force_submit=submit_characters,
    )
    character_execution_path = planning.output_dir / "seedream_character_execution.json"

    write_json(planning.character_images_path, planning.project_package.character_images)
    write_json(planning.scene_plan_path, {"scenes": planning.project_package.scenes})
    write_json(planning.scene_images_path, planning.project_package.scene_images)
    write_json(planning.manifest_path, planning.manifest)
    write_json(character_execution_path, character_execution)

    return CharacterImagePipelineResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        scene_plan_path=planning.scene_plan_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        seedream_execution_path=character_execution_path,
        character_seedream_execution_path=character_execution_path,
        project_package=planning.project_package,
        manifest=planning.manifest,
        seedream_execution=character_execution,
    )


def run_scene_image_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    submit_scenes: bool = True,
    segment_id: str | None = None,
    scene_id: str | None = None,
    master_only: bool = False,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> SceneImagePipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    seedream_client = SeedreamClient(config.seedream)
    character_execution_path = output_dir / "seedream_character_execution.json"
    selected_scene_ids = {scene_id} if scene_id else None
    if master_only:
        scene_execution = seedream_client.generate_scene_master_frames(
            planning.project_package,
            force_submit=submit_scenes,
            scene_ids=selected_scene_ids,
            force_regenerate=True,
        )
        combined_execution = scene_execution
    else:
        scene_execution = seedream_client.generate_scene_images(
            planning.project_package,
            force_submit=submit_scenes,
            segment_ids={segment_id} if segment_id else None,
        )
        character_execution = read_seedream_execution_report(character_execution_path)
        combined_execution = merge_seedream_execution_reports(character_execution, scene_execution)

    scene_execution_path = output_dir / "seedream_scene_execution.json"

    write_json(planning.character_images_path, planning.project_package.character_images)
    write_json(planning.scene_plan_path, {"scenes": planning.project_package.scenes})
    write_json(planning.scene_images_path, planning.project_package.scene_images)
    write_json(planning.manifest_path, planning.manifest)
    write_json(scene_execution_path, scene_execution)
    write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    return SceneImagePipelineResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        scene_plan_path=planning.scene_plan_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        seedream_execution_path=scene_execution_path,
        character_seedream_execution_path=character_execution_path,
        scene_seedream_execution_path=scene_execution_path,
        project_package=planning.project_package,
        manifest=planning.manifest,
        seedream_execution=combined_execution,
    )


def run_segment_continuity_repair_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    segment_id: str | None = None,
    use_llm: bool = True,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> ContinuityRepairResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    resolved_segment_id = str(segment_id or "").strip()
    if not resolved_segment_id:
        raise ValueError("segment_id is required for continuity repair.")

    planning = load_video_planning_artifacts(output_dir)
    novel_package_path = output_dir / "novel_package.json"
    if not novel_package_path.exists():
        raise FileNotFoundError(
            f"Novel package not found at {novel_package_path}. Generate structured story information first."
        )

    continuity_issues = _collect_segment_continuity_issues(output_dir, resolved_segment_id)
    if not continuity_issues:
        raise ValueError(f"Segment {resolved_segment_id} has no continuity issues to repair.")

    novel_package = NovelPackage.from_dict(read_json(novel_package_path))
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
    repaired_segment, repair_report = service.repair_segment_continuity(
        novel_package=novel_package,
        project_package=planning.project_package,
        segment_id=resolved_segment_id,
        continuity_issues=continuity_issues,
    )
    project_package = _apply_repaired_segment_to_project_package(
        planning.project_package,
        repaired_segment,
    )
    rebuilt_scene_images, rebuilt_manifest = _rebuild_segment_execution_contracts(
        service=service,
        project_package=project_package,
        output_dir=output_dir,
        target_segment_id=resolved_segment_id,
        existing_scene_images=project_package.scene_images,
        existing_manifest=planning.manifest,
    )
    project_package.scene_images = rebuilt_scene_images
    project_package.seedance_manifest = rebuilt_manifest

    repair_report_path = output_dir / f"continuity_repair_{resolved_segment_id}.json"
    repair_summary = str(repair_report.get("repair_summary", "") or "").strip()

    write_json(planning.scene_plan_path, {"scenes": project_package.scenes})
    write_json(planning.segment_plan_path, project_package.segments)
    write_json(planning.scene_images_path, rebuilt_scene_images)
    write_json(planning.manifest_path, rebuilt_manifest)
    write_json(repair_report_path, repair_report)
    continuity_report_path, _ = write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    return ContinuityRepairResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        scene_plan_path=planning.scene_plan_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        continuity_report_path=continuity_report_path,
        repair_report_path=repair_report_path,
        project_package=project_package,
        manifest=rebuilt_manifest,
        segment_id=resolved_segment_id,
        repair_summary=repair_summary,
    )


def run_video_render_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    submit_seedance: bool = True,
    segment_id: str | None = None,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> VideoRenderResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    paths = resolve_video_planning_paths(output_dir)
    manifest_path = paths.manifest_path
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Seedance manifest not found at {manifest_path}. Generate images first."
        )

    manifest = load_seedance_manifest(output_dir)
    selected_segment_ids = {segment_id} if segment_id else None
    if submit_seedance or config.seedance.auto_submit:
        validate_manifest_ready_for_video(manifest, selected_segment_ids)
    seedance_client = SeedanceClient(config.seedance)
    seedance_execution = seedance_client.execute_manifest(
        manifest,
        force_submit=submit_seedance,
        segment_ids=selected_segment_ids,
    )

    seedance_execution_path = output_dir / "seedance_execution.json"

    write_json(manifest_path, manifest)
    write_json(seedance_execution_path, seedance_execution)
    write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    selected_clips = resolve_selected_manifest_clips(manifest, selected_segment_ids)
    rendered_clip_paths = [
        Path(clip.downloaded_path)
        for clip in selected_clips
        if clip.downloaded_path
    ]

    full_story_path = None

    return VideoRenderResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        seedance_execution_path=seedance_execution_path,
        rendered_clip_paths=rendered_clip_paths,
        full_story_path=full_story_path,
        manifest=manifest,
        seedance_execution=seedance_execution,
    )


def run_video_merge_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> VideoMergeResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    paths = resolve_video_planning_paths(output_dir)
    manifest_path = paths.manifest_path
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Seedance manifest not found at {manifest_path}. Generate videos first."
        )

    manifest = load_seedance_manifest(output_dir)
    rendered_clips = resolve_rendered_manifest_clips(manifest)
    if len(rendered_clips) < 2:
        raise ValueError("At least 2 rendered video clips are required before manual merge.")

    full_story_output_path = output_dir / "rendered" / "full_story.mp4"
    merge_manifest = SeedanceManifest(
        title=manifest.title,
        model=manifest.model,
        base_url=manifest.base_url,
        clips=rendered_clips,
        notes=list(manifest.notes),
    )
    full_story_path = concat_manifest_clips(
        manifest=merge_manifest,
        output_path=full_story_output_path,
    )
    write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    return VideoMergeResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        rendered_clip_paths=[Path(clip.downloaded_path or clip.output_path) for clip in rendered_clips],
        full_story_path=full_story_path,
        manifest=manifest,
        merged_clip_count=len(rendered_clips),
        skipped_clip_count=max(0, len(manifest.clips) - len(rendered_clips)),
    )


__all__ = [
    "CharacterImagePipelineResult",
    "ContinuityRepairResult",
    "ImagePipelineResult",
    "SceneImagePipelineResult",
    "VideoPipelineResult",
    "VideoPlanningArtifacts",
    "VideoMergeResult",
    "VideoRenderResult",
    "run_character_image_pipeline",
    "run_segment_continuity_repair_pipeline",
    "run_image_pipeline",
    "run_video_merge_pipeline",
    "run_scene_image_pipeline",
    "run_video_pipeline",
    "run_video_render_pipeline",
]


def _collect_segment_continuity_issues(output_dir: Path, segment_id: str) -> list[dict[str, object]]:
    report_path = output_dir / "continuity_report.json"
    if not report_path.exists():
        raise FileNotFoundError(
            f"Continuity report not found at {report_path}. Generate structured story information first."
        )
    payload = read_json(report_path)
    if not isinstance(payload, dict):
        raise ValueError("continuity_report.json is not a valid object payload.")
    return [
        {
            "severity": str(item.get("severity", "") or ""),
            "scope": str(item.get("scope", "") or ""),
            "code": str(item.get("code", "") or ""),
            "message": str(item.get("message", "") or ""),
            "scene_id": str(item.get("scene_id", "") or ""),
            "segment_id": str(item.get("segment_id", "") or ""),
            "recommended_action": str(item.get("recommended_action", "") or ""),
            "recommended_action_label": str(item.get("recommended_action_label", "") or ""),
            "details": item.get("details", {}) if isinstance(item.get("details"), dict) else {},
        }
        for item in payload.get("segment_issues", [])
        if isinstance(item, dict) and str(item.get("segment_id", "") or "") == segment_id
    ]


def _apply_repaired_segment_to_project_package(
    project_package,
    repaired_segment,
):
    repaired_contract = VideoSegment.from_dict(to_jsonable(repaired_segment))
    for index, segment in enumerate(project_package.segments):
        if segment.segment_id != repaired_contract.segment_id:
            continue
        project_package.segments[index] = repaired_contract
        break
    else:
        raise ValueError(f"Segment {repaired_contract.segment_id} not found in current project package.")

    for scene in project_package.scenes:
        for index, segment in enumerate(scene.segments):
            if segment.segment_id != repaired_contract.segment_id:
                continue
            scene.segments[index] = repaired_contract
            return project_package
    raise ValueError(
        f"Scene container for segment {repaired_contract.segment_id} not found in current project package."
    )


def _rebuild_segment_execution_contracts(
    *,
    service: NovelToVideoService,
    project_package,
    output_dir: Path,
    target_segment_id: str,
    existing_scene_images: list[SceneImageTask],
    existing_manifest: SeedanceManifest,
) -> tuple[list[SceneImageTask], SeedanceManifest]:
    profile_map = {item.name: item for item in project_package.character_profiles}
    rebuilt_scene_images = service._build_scene_image_tasks(
        project_package.scenes,
        project_package.segments,
        project_package.character_images,
        profile_map,
        str(output_dir),
    )
    rebuilt_manifest = service._build_seedance_manifest(
        project_package.title,
        project_package.segments,
        rebuilt_scene_images,
        str(output_dir),
    )

    existing_scene_image_map = {item.segment_id: item for item in existing_scene_images}
    merged_scene_images: list[SceneImageTask] = []
    for item in rebuilt_scene_images:
        if item.segment_id != target_segment_id:
            merged_scene_images.append(existing_scene_image_map.get(item.segment_id, item))
            continue
        merged_scene_images.append(_reset_scene_image_task_for_repair(item))

    existing_clip_map = {item.segment_id: item for item in existing_manifest.clips}
    merged_clips: list[SeedanceClipTask] = []
    for item in rebuilt_manifest.clips:
        if item.segment_id != target_segment_id:
            merged_clips.append(existing_clip_map.get(item.segment_id, item))
            continue
        merged_clips.append(_reset_seedance_clip_task_for_repair(item))

    return (
        merged_scene_images,
        SeedanceManifest(
            title=rebuilt_manifest.title,
            model=rebuilt_manifest.model,
            base_url=rebuilt_manifest.base_url,
            clips=merged_clips,
            notes=list(rebuilt_manifest.notes),
        ),
    )


def _reset_scene_image_task_for_repair(task: SceneImageTask) -> SceneImageTask:
    payload = {
        **to_jsonable(task),
        "status": "planned",
        "start_frame_url": "",
        "mid_frame_url": "",
        "end_frame_url": "",
        "error": "",
    }
    return SceneImageTask.from_dict(payload)


def _reset_seedance_clip_task_for_repair(task: SeedanceClipTask) -> SeedanceClipTask:
    payload = {
        **to_jsonable(task),
        "start_frame_url": "",
        "mid_frame_url": "",
        "end_frame_url": "",
        "reference_image_urls": [],
        "remote_task_id": "",
        "submit_status": "planned",
        "remote_status": "planned",
        "video_url": "",
        "cover_url": "",
        "downloaded_path": "",
        "error": "",
    }
    return SeedanceClipTask.from_dict(payload)
