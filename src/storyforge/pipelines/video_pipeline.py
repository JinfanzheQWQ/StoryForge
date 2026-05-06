from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, to_jsonable, write_json
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    SceneImageTask,
    SeedanceClipTask,
    SeedanceManifest,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.llm import build_agent_backend
from storyforge.integrations.ffmpeg_adapter import (
    concat_manifest_clips,
)
from storyforge.integrations.seedance import SeedanceClient
from storyforge.integrations.gpt_image import GPTImageClient
from storyforge.integrations.seedream import SeedreamClient, SeedreamExecutionReport
from storyforge.pipelines.continuity import write_continuity_report
from storyforge.pipelines.video_models import (
    CharacterImagePipelineResult,
    ContinuityRepairResult,
    SceneImagePipelineResult,
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
    validate_manifest_ready_for_video,
)
from storyforge.pipelines.video_reference_sync import (
    apply_previous_scene_master_reference as _apply_previous_scene_master_reference,
    reset_copied_previous_scene_master as _reset_copied_previous_scene_master,
    resolve_selected_segment_ids as _resolve_selected_segment_ids,
    sync_cross_scene_reused_master_frames as _sync_cross_scene_reused_master_frames,
    sync_scene_master_references as _sync_scene_master_references,
    sync_seedance_tail_frame_handoffs as _sync_seedance_tail_frame_handoffs,
    sync_v2_seedance_references as _sync_v2_seedance_references,
)


SCENE_MASTER_REPAIR_ACTION = "regenerate_scene_master_frame"
SCENE_REPAIR_GLOBAL_CODES = {
    "scene_bible_incomplete",
    "scene_master_frame_failed",
    "scene_master_frame_missing_output",
    "scene_master_frame_task_mismatch",
}
SCENE_REPAIR_SEGMENT_ACTIONS = {
    "regenerate_scene_images",
    "regenerate_video",
}


def run_character_image_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    submit_characters: bool = True,
    character_name: str | None = None,
    image_model: str | None = None,
    image_size: str | None = None,
    image_aspect_ratio: str | None = None,
) -> CharacterImagePipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    resolved_model = _resolve_image_model(config, image_model)
    resolved_size = str(image_size or config.seedream.image_size or "2K").strip() or "2K"
    resolved_aspect_ratio = str(image_aspect_ratio or config.video.aspect_ratio or "16:9").strip() or "16:9"
    selected_character_names = {character_name.strip()} if character_name and character_name.strip() else None
    if resolved_model == config.gpt_image.model:
        character_execution = _generate_character_images_with_gpt(
            planning.project_package.character_images,
            config=config,
            project_root=project_root,
            force_submit=submit_characters,
            character_names=selected_character_names,
            image_size=resolved_size,
            aspect_ratio=resolved_aspect_ratio,
        )
    else:
        seedream_client = SeedreamClient(replace(config.seedream, image_size=resolved_size))
        character_execution = seedream_client.generate_character_images(
            planning.project_package,
            force_submit=submit_characters,
            character_names=selected_character_names,
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
    segment_ids: set[str] | None = None,
    image_model: str | None = None,
    image_size: str | None = None,
    image_aspect_ratio: str | None = None,
) -> SceneImagePipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    character_execution_path = output_dir / "seedream_character_execution.json"
    resolved_model = _resolve_image_model(config, image_model)
    resolved_size = str(image_size or config.seedream.image_size or "2K").strip() or "2K"
    resolved_aspect_ratio = str(image_aspect_ratio or config.video.aspect_ratio or "16:9").strip() or "16:9"
    selected_scene_ids = {scene_id} if scene_id else None
    selected_segment_ids = _resolve_selected_segment_ids(
        planning.project_package,
        segment_id=segment_id,
        scene_id=None if master_only else scene_id,
        segment_ids=segment_ids,
    )
    selected_scene_ids = selected_scene_ids or (
        {scene.scene_id for scene in planning.project_package.scenes}
        if scene_id is None
        else {scene_id}
    )
    if resolved_model == config.gpt_image.model:
        scene_execution = _generate_scene_master_frames_with_gpt(
            planning.project_package.scenes,
            planning.project_package.scene_images,
            config=config,
            project_root=project_root,
            force_submit=submit_scenes,
            scene_ids=selected_scene_ids,
            force_regenerate=master_only,
            image_size=resolved_size,
            aspect_ratio=resolved_aspect_ratio,
        )
    else:
        seedream_client = SeedreamClient(replace(config.seedream, image_size=resolved_size))
        scene_execution = seedream_client.generate_scene_master_frames(
            planning.project_package,
            force_submit=submit_scenes,
            scene_ids=selected_scene_ids,
            force_regenerate=master_only,
        )
    if master_only:
        combined_execution = scene_execution
    else:
        character_execution = read_seedream_execution_report(character_execution_path)
        combined_execution = merge_seedream_execution_reports(character_execution, scene_execution)

    scene_execution_path = output_dir / "seedream_scene_execution.json"

    merged_scene_images = _merge_scene_image_tasks_for_write(
        planning.project_package.scene_images,
        planning.scene_images_path,
        selected_segment_ids=selected_segment_ids,
        selected_scene_ids=selected_scene_ids,
    )
    merged_manifest = _merge_seedance_manifest_for_write(
        planning.manifest,
        planning.manifest_path,
        selected_segment_ids=set(),
    )
    _sync_cross_scene_reused_master_frames(planning.project_package.scenes, merged_scene_images)
    _sync_scene_master_references(merged_scene_images, merged_manifest)
    planning.project_package.scene_images = merged_scene_images
    planning.project_package.seedance_manifest = merged_manifest
    planning.manifest = merged_manifest

    write_json(planning.character_images_path, planning.project_package.character_images)
    write_json(planning.scene_plan_path, {"scenes": planning.project_package.scenes})
    write_json(planning.scene_images_path, merged_scene_images)
    write_json(planning.manifest_path, merged_manifest)
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
        manifest=merged_manifest,
        seedream_execution=combined_execution,
    )


def _generate_character_images_with_gpt(
    tasks: list[CharacterImageTask],
    *,
    config: AppConfig,
    project_root: Path,
    force_submit: bool,
    character_names: set[str] | None,
    image_size: str,
    aspect_ratio: str,
) -> SeedreamExecutionReport:
    target_tasks = _select_character_image_tasks(tasks, character_names)
    if not force_submit:
        return SeedreamExecutionReport(
            submitted=False,
            generated_count=0,
            failed_count=0,
            note="GPT Image 2 character image submission skipped.",
        )

    generated_count = 0
    failed_count = 0
    client = GPTImageClient(config.gpt_image)
    for task in target_tasks:
        task.provider = config.gpt_image.model
        task.status = "running"
        try:
            has_current_image = bool(str(task.generated_url or "").strip()) or Path(task.output_path).is_file()
            output_path = (
                _candidate_character_image_path(_image_output_path_for_gpt(Path(task.output_path), config))
                if has_current_image
                else _image_output_path_for_gpt(Path(task.output_path), config)
            )
            image_result = client.generate_single_image(
                mode="text_to_image",
                prompt=task.prompt,
                reference_images=[],
                aspect_ratio=aspect_ratio,
                output_size=image_size,
                output_path=output_path,
            )
            generated_url = image_result.image_url or _build_output_file_url(config, project_root, output_path)
            if has_current_image:
                task.candidate_generated_url = generated_url
                task.candidate_output_path = str(output_path)
                task.status = "candidate_ready"
            else:
                task.output_path = str(output_path)
                task.generated_url = generated_url
                task.candidate_generated_url = ""
                task.candidate_output_path = ""
                task.status = "completed"
            task.request_info = image_result.request_info
            task.error = ""
            generated_count += 1
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            failed_count += 1
    return SeedreamExecutionReport(
        submitted=True,
        generated_count=generated_count,
        failed_count=failed_count,
        note=(
            "GPT Image 2 character image tasks executed successfully."
            if failed_count == 0
            else "GPT Image 2 character image generation completed with partial failures."
        ),
    )


def _generate_scene_master_frames_with_gpt(
    scenes: list[VideoScene],
    scene_tasks: list[SceneImageTask],
    *,
    config: AppConfig,
    project_root: Path,
    force_submit: bool,
    scene_ids: set[str] | None,
    force_regenerate: bool,
    image_size: str,
    aspect_ratio: str,
) -> SeedreamExecutionReport:
    target_scene_ids = {scene_id for scene_id in (scene_ids or set()) if scene_id}
    target_scenes = [scene for scene in scenes if not target_scene_ids or scene.scene_id in target_scene_ids]
    if not force_submit:
        return SeedreamExecutionReport(
            submitted=False,
            generated_count=0,
            failed_count=0,
            note="GPT Image 2 scene master submission skipped.",
        )

    scene_task_by_scene = _best_scene_task_by_scene(scene_tasks)
    previous_scene_by_id = _previous_scene_by_id(scenes)
    generated_count = 0
    failed_count = 0
    client = GPTImageClient(config.gpt_image)
    for scene in target_scenes:
        _apply_previous_scene_master_reference(scene, previous_scene_by_id.get(scene.scene_id))
        _reset_copied_previous_scene_master(scene, previous_scene_by_id.get(scene.scene_id))
        task = scene_task_by_scene.get(scene.scene_id)
        previous_url = scene.scene_master_frame_url
        if not force_regenerate and scene.scene_master_frame_url and scene.scene_master_frame_status == "completed":
            if task is not None:
                task.provider = config.gpt_image.model
            continue
        scene.scene_master_frame_status = "running"
        scene.scene_master_frame_error = ""
        if task is not None:
            task.provider = config.gpt_image.model
            task.scene_master_frame_status = "running"
            task.status = "running"
            task.error = ""
        try:
            output_path_text = scene.scene_master_frame_path or (task.scene_master_frame_path if task is not None else "")
            if not output_path_text:
                raise ValueError(f"{scene.scene_id} 缺少场景母图输出路径。")
            output_path = _image_output_path_for_gpt(Path(output_path_text), config)
            reference_images = list(scene.scene_master_reference_images or [])
            image_result = client.generate_single_image(
                mode="image_to_image" if reference_images else "text_to_image",
                prompt=scene.scene_master_frame_prompt,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                output_size=image_size,
                output_path=output_path,
            )
            generated_url = image_result.image_url or _build_output_file_url(config, project_root, output_path)
            scene.scene_master_frame_path = str(output_path)
            scene.scene_master_frame_url = generated_url
            scene.scene_master_frame_status = "completed"
            scene.scene_master_request_info = {
                **image_result.request_info,
                "reference_bindings": _scene_master_reference_bindings(reference_images),
            }
            if task is not None:
                task.scene_master_frame_path = str(output_path)
                task.scene_master_frame_url = generated_url
                task.scene_master_frame_status = "completed"
                task.status = "completed"
                task.error = ""
            generated_count += 1
        except Exception as exc:
            scene.scene_master_frame_status = "failed"
            scene.scene_master_frame_error = str(exc)
            if not previous_url:
                scene.scene_master_frame_url = ""
            if task is not None:
                task.scene_master_frame_status = "failed"
                task.scene_master_frame_error = str(exc)
                task.status = "failed"
                task.error = str(exc)
            failed_count += 1
    _sync_gpt_scene_tasks_from_scenes(scenes, scene_tasks, config.gpt_image.model)
    return SeedreamExecutionReport(
        submitted=True,
        generated_count=generated_count,
        failed_count=failed_count,
        note=(
            "GPT Image 2 scene master frame tasks executed successfully."
            if failed_count == 0
            else "GPT Image 2 scene master frame generation completed with partial failures."
        ),
    )


def _previous_scene_by_id(scenes: list[VideoScene]) -> dict[str, VideoScene]:
    previous_by_id: dict[str, VideoScene] = {}
    previous_scene: VideoScene | None = None
    for scene in scenes:
        if scene.scene_id and previous_scene is not None:
            previous_by_id[scene.scene_id] = previous_scene
        previous_scene = scene
    return previous_by_id


def _select_character_image_tasks(
    tasks: list[CharacterImageTask],
    character_names: set[str] | None,
) -> list[CharacterImageTask]:
    if not character_names:
        return list(tasks)
    selected_tasks = [task for task in tasks if task.character_name in character_names]
    missing_names = sorted(character_names - {task.character_name for task in selected_tasks})
    if missing_names:
        raise ValueError(
            "Requested characters are not present in character_image_manifest.json: "
            + ", ".join(missing_names)
        )
    return selected_tasks


def _resolve_image_model(config: AppConfig, raw_model: str | None) -> str:
    model = str(raw_model or "").strip()
    if not model:
        return config.seedream.model
    if model in {"gpt-image-2", config.gpt_image.model}:
        return config.gpt_image.model
    if model in {"seedream", "seedream-4.5", config.seedream.model}:
        return config.seedream.model
    raise ValueError(f"生图模型只支持 {config.gpt_image.model} 或 {config.seedream.model}。")


def _image_output_path_for_gpt(path: Path, config: AppConfig) -> Path:
    suffix = str(config.gpt_image.output_format or "png").strip().lower()
    if suffix == "jpeg":
        suffix = "jpg"
    if suffix not in {"png", "jpg", "webp"}:
        suffix = "png"
    return path.with_suffix(f".{suffix}")


def _candidate_character_image_path(output_path: Path) -> Path:
    candidate_dir = output_path.parent / "_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    return candidate_dir / output_path.name


def _build_output_file_url(config: AppConfig, project_root: Path, path: Path) -> str:
    if not path.exists():
        return ""
    output_root = (project_root / config.paths.output_dir).resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(output_root)
    except ValueError:
        return ""
    encoded_path = "/".join(quote(part) for part in relative_path.parts)
    return f"/outputs/{encoded_path}?v={int(resolved_path.stat().st_mtime_ns)}"


def _best_scene_task_by_scene(scene_tasks: list[SceneImageTask]) -> dict[str, SceneImageTask]:
    best_by_scene: dict[str, SceneImageTask] = {}
    for task in scene_tasks:
        if not task.scene_id:
            continue
        current = best_by_scene.get(task.scene_id)
        if current is None or _scene_task_score(task) > _scene_task_score(current):
            best_by_scene[task.scene_id] = task
    return best_by_scene


def _scene_task_score(task: SceneImageTask) -> tuple[int, int]:
    status = str(task.scene_master_frame_status or task.status or "").lower()
    return (
        2 if status == "completed" else 1 if status == "running" else 0,
        1 if task.scene_master_frame_url else 0,
    )


def _scene_master_reference_bindings(reference_images: list[str]) -> list[dict[str, str]]:
    return [
        {
            "label": f"图片{index}",
            "kind": "previous_scene_master",
            "description": "上一场场景母图参考，仅用于同一空间或同地点连续性。",
            "url": url,
        }
        for index, url in enumerate(reference_images, start=1)
    ]


def _sync_gpt_scene_tasks_from_scenes(
    scenes: list[VideoScene],
    scene_tasks: list[SceneImageTask],
    provider: str,
) -> None:
    scene_by_id = {scene.scene_id: scene for scene in scenes if scene.scene_id}
    for task in scene_tasks:
        scene = scene_by_id.get(task.scene_id)
        if scene is None:
            continue
        task.provider = provider
        if scene.scene_master_frame_path:
            task.scene_master_frame_path = scene.scene_master_frame_path
        if scene.scene_master_frame_url:
            task.scene_master_frame_url = scene.scene_master_frame_url
        task.scene_master_frame_status = scene.scene_master_frame_status or task.scene_master_frame_status
        task.scene_master_frame_error = scene.scene_master_frame_error or task.scene_master_frame_error
        if scene.scene_master_frame_status == "completed":
            task.status = "completed"
        elif scene.scene_master_frame_status == "failed":
            task.status = "failed"
            task.error = scene.scene_master_frame_error


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
    repair_report["repair_action"] = "rewrite_segment_contract"
    repair_report["execution_mode"] = "plan_only"
    repair_report["downstream_actions"] = [
        "regenerate_scene_images",
        "regenerate_video",
    ]

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
        repair_action="rewrite_segment_contract",
    )


def run_scene_continuity_repair_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    scene_id: str | None = None,
    use_llm: bool = True,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> ContinuityRepairResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    resolved_scene_id = str(scene_id or "").strip()
    if not resolved_scene_id:
        raise ValueError("scene_id is required for scene continuity repair.")

    planning = load_video_planning_artifacts(output_dir)
    scene_issues, related_segment_issues = _collect_scene_repair_issues(
        output_dir,
        resolved_scene_id,
    )
    if not scene_issues and not related_segment_issues:
        raise ValueError(f"Scene {resolved_scene_id} has no continuity issues to repair.")

    target_segment_ids, selection_mode = _resolve_scene_repair_segment_ids(
        project_package=planning.project_package,
        scene_id=resolved_scene_id,
        scene_issues=scene_issues,
        related_segment_issues=related_segment_issues,
    )
    novel_package_path = output_dir / "novel_package.json"
    if not novel_package_path.exists():
        raise FileNotFoundError(
            f"Novel package not found at {novel_package_path}. Generate structured story information first."
        )

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
    repaired_scene, repair_report = service.repair_scene_continuity(
        novel_package=novel_package,
        project_package=planning.project_package,
        scene_id=resolved_scene_id,
        scene_issues=scene_issues,
        related_segment_issues=related_segment_issues,
        target_segment_ids=target_segment_ids,
        selection_mode=selection_mode,
    )
    project_package = _apply_repaired_scene_to_project_package(
        planning.project_package,
        repaired_scene,
        target_segment_ids=target_segment_ids,
    )
    rebuilt_scene_images = project_package.scene_images
    rebuilt_manifest = planning.manifest
    for target_segment_id in target_segment_ids:
        rebuilt_scene_images, rebuilt_manifest = _rebuild_segment_execution_contracts(
            service=service,
            project_package=project_package,
            output_dir=output_dir,
            target_segment_id=target_segment_id,
            existing_scene_images=rebuilt_scene_images,
            existing_manifest=rebuilt_manifest,
        )
    project_package.scene_images = rebuilt_scene_images
    project_package.seedance_manifest = rebuilt_manifest

    repair_report_path = output_dir / f"continuity_repair_{resolved_scene_id}.json"
    repair_summary = str(repair_report.get("repair_summary", "") or "").strip() or _build_scene_repair_summary(selection_mode)
    repair_report.update(
        {
            "scope": "scene",
            "scene_id": resolved_scene_id,
            "repair_action": SCENE_MASTER_REPAIR_ACTION,
            "repair_summary": repair_summary,
            "execution_mode": "plan_only",
            "selection_mode": selection_mode,
            "affected_segment_ids": target_segment_ids,
            "downstream_actions": [
                SCENE_MASTER_REPAIR_ACTION,
                "regenerate_scene_images",
                "regenerate_video",
            ],
            "continuity_issues": scene_issues,
            "related_segment_issues": related_segment_issues,
        }
    )

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
        repair_action=SCENE_MASTER_REPAIR_ACTION,
        selection_mode=selection_mode,
        affected_segment_ids=tuple(target_segment_ids),
        scene_id=resolved_scene_id,
        repair_summary=repair_summary,
    )


def reset_scene_execution_contracts_for_repair(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    scene_id: str | None = None,
    segment_ids: set[str] | None = None,
) -> set[str]:
    output_dir = output_root or (project_root / config.paths.output_dir)
    resolved_scene_id = str(scene_id or "").strip()
    if not resolved_scene_id:
        raise ValueError("scene_id is required to reset scene execution contracts.")

    planning = load_video_planning_artifacts(output_dir)
    target_segment_ids = _resolve_selected_segment_ids(
        planning.project_package,
        scene_id=resolved_scene_id,
        segment_ids=segment_ids,
    )
    if not target_segment_ids:
        raise ValueError(f"Scene {resolved_scene_id} has no segments to reset.")

    reset_scene_images = [
        _reset_scene_image_task_for_repair(task)
        if task.segment_id in target_segment_ids
        else task
        for task in planning.project_package.scene_images
    ]
    reset_clips = [
        _reset_seedance_clip_task_for_repair(clip)
        if clip.segment_id in target_segment_ids
        else clip
        for clip in planning.manifest.clips
    ]
    reset_manifest = SeedanceManifest(
        title=planning.manifest.title,
        model=planning.manifest.model,
        base_url=planning.manifest.base_url,
        clips=reset_clips,
        notes=list(planning.manifest.notes),
    )
    planning.project_package.scene_images = reset_scene_images
    planning.project_package.seedance_manifest = reset_manifest

    write_json(planning.scene_images_path, reset_scene_images)
    write_json(planning.manifest_path, reset_manifest)
    return target_segment_ids


def run_video_render_pipeline(
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    submit_seedance: bool = True,
    segment_id: str | None = None,
    scene_id: str | None = None,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    segment_ids: set[str] | None = None,
) -> VideoRenderResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    manifest_path = planning.manifest_path
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Seedance manifest not found at {manifest_path}. Generate images first."
        )

    manifest = planning.manifest
    _sync_cross_scene_reused_master_frames(
        planning.project_package.scenes,
        planning.project_package.scene_images,
    )
    _sync_v2_seedance_references(manifest, planning.project_package)
    _sync_v2_seedance_references(planning.project_package.seedance_manifest, planning.project_package)
    planning.project_package.seedance_manifest = manifest
    selected_segment_ids = _resolve_selected_segment_ids(
        planning.project_package,
        segment_id=segment_id,
        scene_id=scene_id,
        segment_ids=segment_ids,
    )
    _sync_seedance_tail_frame_handoffs(manifest, planning.project_package.scenes)
    write_json(manifest_path, manifest)
    if submit_seedance or config.seedance.auto_submit:
        validate_manifest_ready_for_video(manifest, selected_segment_ids)
    seedance_client = SeedanceClient(config.seedance)
    seedance_execution = seedance_client.execute_manifest(
        manifest,
        force_submit=submit_seedance,
        segment_ids=selected_segment_ids,
    )
    merged_manifest = _merge_seedance_manifest_for_write(
        manifest,
        manifest_path,
        selected_segment_ids=selected_segment_ids,
    )
    _sync_scene_master_references(planning.project_package.scene_images, merged_manifest)
    _sync_seedance_tail_frame_handoffs(merged_manifest, planning.project_package.scenes)
    planning.project_package.seedance_manifest = merged_manifest
    planning.manifest = merged_manifest

    seedance_execution_path = output_dir / "seedance_execution.json"

    write_json(manifest_path, merged_manifest)
    write_json(seedance_execution_path, seedance_execution)
    write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    selected_clips = resolve_selected_manifest_clips(merged_manifest, selected_segment_ids)
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
        manifest=merged_manifest,
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
    "SceneImagePipelineResult",
    "VideoPlanningArtifacts",
    "VideoMergeResult",
    "VideoRenderResult",
    "run_character_image_pipeline",
    "reset_scene_execution_contracts_for_repair",
    "run_scene_continuity_repair_pipeline",
    "run_segment_continuity_repair_pipeline",
    "run_video_merge_pipeline",
    "run_scene_image_pipeline",
    "run_video_render_pipeline",
]


def _load_scene_image_tasks_from_path(path: Path) -> list[SceneImageTask]:
    if not path.exists():
        return []
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    return [SceneImageTask.from_dict(item) for item in payload if isinstance(item, dict)]


def _load_seedance_manifest_from_path(path: Path) -> SeedanceManifest | None:
    if not path.exists():
        return None
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    return SeedanceManifest.from_dict(payload)


def _merge_scene_image_tasks_for_write(
    current_tasks: list[SceneImageTask],
    path: Path,
    *,
    selected_segment_ids: set[str] | None,
    selected_scene_ids: set[str] | None,
) -> list[SceneImageTask]:
    latest_tasks = _load_scene_image_tasks_from_path(path)
    latest_by_segment = {item.segment_id: item for item in latest_tasks}
    current_by_segment = {item.segment_id: item for item in current_tasks}
    ordered_segment_ids = list(current_by_segment)
    ordered_segment_ids.extend(
        segment_id for segment_id in latest_by_segment if segment_id not in current_by_segment
    )

    merged_tasks: list[SceneImageTask] = []
    for segment_id in ordered_segment_ids:
        current_task = current_by_segment.get(segment_id)
        latest_task = latest_by_segment.get(segment_id)
        if current_task is None:
            merged_tasks.append(latest_task)
            continue
        if latest_task is None:
            merged_tasks.append(current_task)
            continue
        prefer_current = _should_prefer_current_segment_state(
            segment_id=segment_id,
            scene_id=current_task.scene_id,
            selected_segment_ids=selected_segment_ids,
            selected_scene_ids=selected_scene_ids,
        )
        primary, secondary = (
            (current_task, latest_task) if prefer_current else (latest_task, current_task)
        )
        merged_tasks.append(_merge_scene_image_task(primary, secondary))
    return merged_tasks


def _merge_seedance_manifest_for_write(
    current_manifest: SeedanceManifest,
    path: Path,
    *,
    selected_segment_ids: set[str] | None,
) -> SeedanceManifest:
    latest_manifest = _load_seedance_manifest_from_path(path)
    if latest_manifest is None:
        return current_manifest

    latest_by_segment = {item.segment_id: item for item in latest_manifest.clips}
    current_by_segment = {item.segment_id: item for item in current_manifest.clips}
    ordered_segment_ids = list(current_by_segment)
    ordered_segment_ids.extend(
        segment_id for segment_id in latest_by_segment if segment_id not in current_by_segment
    )

    merged_clips: list[SeedanceClipTask] = []
    for segment_id in ordered_segment_ids:
        current_clip = current_by_segment.get(segment_id)
        latest_clip = latest_by_segment.get(segment_id)
        if current_clip is None:
            merged_clips.append(latest_clip)
            continue
        if latest_clip is None:
            merged_clips.append(current_clip)
            continue
        prefer_current = _should_prefer_current_segment_state(
            segment_id=segment_id,
            scene_id="",
            selected_segment_ids=selected_segment_ids,
            selected_scene_ids=None,
        )
        primary, secondary = (
            (current_clip, latest_clip) if prefer_current else (latest_clip, current_clip)
        )
        merged_clips.append(_merge_seedance_clip_task(primary, secondary))

    merged_notes = list(current_manifest.notes)
    merged_notes.extend(note for note in latest_manifest.notes if note not in merged_notes)
    return SeedanceManifest(
        title=current_manifest.title or latest_manifest.title,
        model=current_manifest.model or latest_manifest.model,
        base_url=current_manifest.base_url or latest_manifest.base_url,
        clips=merged_clips,
        notes=merged_notes,
    )


def _should_prefer_current_segment_state(
    *,
    segment_id: str,
    scene_id: str,
    selected_segment_ids: set[str] | None,
    selected_scene_ids: set[str] | None,
) -> bool:
    if selected_scene_ids:
        return scene_id in selected_scene_ids
    if selected_segment_ids is None:
        return True
    return segment_id in selected_segment_ids


def _merge_scene_image_task(
    preferred: SceneImageTask,
    fallback: SceneImageTask,
) -> SceneImageTask:
    payload = to_jsonable(preferred)
    fallback_payload = to_jsonable(fallback)
    payload["status"] = _prefer_nondefault_status(
        payload.get("status", "planned"),
        fallback_payload.get("status", "planned"),
    )
    payload["scene_master_frame_status"] = _prefer_nondefault_status(
        payload.get("scene_master_frame_status", "planned"),
        fallback_payload.get("scene_master_frame_status", "planned"),
    )
    for field_name in (
        "scene_master_frame_url",
    ):
        payload[field_name] = _prefer_nonempty_string(
            payload.get(field_name, ""),
            fallback_payload.get(field_name, ""),
        )
    payload["scene_master_frame_error"] = _merge_runtime_error(
        preferred_error=payload.get("scene_master_frame_error", ""),
        fallback_error=fallback_payload.get("scene_master_frame_error", ""),
        chosen_status=payload["scene_master_frame_status"],
    )
    payload["error"] = _merge_runtime_error(
        preferred_error=payload.get("error", ""),
        fallback_error=fallback_payload.get("error", ""),
        chosen_status=payload["status"],
    )
    return SceneImageTask.from_dict(payload)


def _merge_seedance_clip_task(
    preferred: SeedanceClipTask,
    fallback: SeedanceClipTask,
) -> SeedanceClipTask:
    payload = to_jsonable(preferred)
    fallback_payload = to_jsonable(fallback)
    payload["submit_status"] = _prefer_nondefault_status(
        payload.get("submit_status", "planned"),
        fallback_payload.get("submit_status", "planned"),
    )
    payload["remote_status"] = _prefer_nondefault_status(
        payload.get("remote_status", "planned"),
        fallback_payload.get("remote_status", "planned"),
    )
    for field_name in (
        "scene_id",
        "scene_master_path",
        "scene_master_url",
        "video_mode",
        "storyboard_grid_path",
        "storyboard_grid_url",
        "storyboard_grid_prompt",
        "storyboard_grid_status",
        "storyboard_grid_error",
        "submitted_prompt",
        "submit_variant",
        "remote_task_id",
        "video_url",
        "cover_url",
        "first_frame_url",
        "last_frame_url",
        "last_frame_path",
        "previous_clip_segment_id",
        "previous_clip_video_url",
        "downloaded_path",
    ):
        payload[field_name] = _prefer_nonempty_string(
            payload.get(field_name, ""),
            fallback_payload.get(field_name, ""),
        )
    payload["storyboard_grid_status"] = _prefer_nondefault_status(
        payload.get("storyboard_grid_status", "planned"),
        fallback_payload.get("storyboard_grid_status", "planned"),
    )
    for field_name in (
        "character_image_paths",
        "character_image_urls",
        "visible_characters",
        "storyboard_scene_descriptions",
    ):
        payload[field_name] = _prefer_nonempty_list(
            payload.get(field_name, []),
            fallback_payload.get(field_name, []),
        )
    payload["storyboard_grid_request_info"] = _prefer_nonempty_mapping(
        payload.get("storyboard_grid_request_info", {}),
        fallback_payload.get("storyboard_grid_request_info", {}),
    )
    payload["motion_contract"] = _prefer_nonempty_mapping(
        payload.get("motion_contract", {}),
        fallback_payload.get("motion_contract", {}),
    )
    payload["submitted_reference_bindings"] = _prefer_nonempty_list(
        payload.get("submitted_reference_bindings", []),
        fallback_payload.get("submitted_reference_bindings", []),
    )
    payload["submitted_request_info"] = _prefer_nonempty_mapping(
        payload.get("submitted_request_info", {}),
        fallback_payload.get("submitted_request_info", {}),
    )
    payload["error"] = _merge_runtime_error(
        preferred_error=payload.get("error", ""),
        fallback_error=fallback_payload.get("error", ""),
        chosen_status=payload["remote_status"],
    )
    return SeedanceClipTask.from_dict(payload)


def _prefer_nondefault_status(preferred: object, fallback: object) -> str:
    preferred_value = str(preferred or "planned")
    fallback_value = str(fallback or "planned")
    if preferred_value != "planned":
        return preferred_value
    return fallback_value


def _prefer_nonempty_string(preferred: object, fallback: object) -> str:
    preferred_value = str(preferred or "").strip()
    if preferred_value:
        return preferred_value
    return str(fallback or "").strip()


def _prefer_nonempty_list(preferred: object, fallback: object) -> list[str]:
    preferred_value = list(preferred or [])
    if preferred_value:
        return preferred_value
    return list(fallback or [])


def _prefer_nonempty_mapping(preferred: object, fallback: object) -> dict[str, object]:
    preferred_value = dict(preferred or {})
    if preferred_value:
        return preferred_value
    return dict(fallback or {})


def _merge_runtime_error(
    *,
    preferred_error: object,
    fallback_error: object,
    chosen_status: object,
) -> str:
    preferred_value = str(preferred_error or "").strip()
    if preferred_value:
        return preferred_value
    status_value = str(chosen_status or "").strip().lower()
    if status_value in {"failed", "cancelled", "canceled", "rejected"}:
        return str(fallback_error or "").strip()
    return ""


def _collect_scene_repair_issues(
    output_dir: Path,
    scene_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    payload = _load_continuity_report_payload(output_dir)
    return (
        _collect_scene_continuity_issues(payload, scene_id),
        _collect_scene_segment_continuity_issues(payload, scene_id),
    )


def _load_continuity_report_payload(output_dir: Path) -> dict[str, object]:
    report_path = output_dir / "continuity_report.json"
    if not report_path.exists():
        raise FileNotFoundError(
            f"Continuity report not found at {report_path}. Generate structured story information first."
        )
    payload = read_json(report_path)
    if not isinstance(payload, dict):
        raise ValueError("continuity_report.json is not a valid object payload.")
    return payload


def _collect_scene_continuity_issues(
    payload: dict[str, object],
    scene_id: str,
) -> list[dict[str, object]]:
    return [
        _normalize_continuity_issue_payload(item)
        for item in payload.get("scene_issues", [])
        if isinstance(item, dict) and str(item.get("scene_id", "") or "") == scene_id
    ]


def _collect_scene_segment_continuity_issues(
    payload: dict[str, object],
    scene_id: str,
) -> list[dict[str, object]]:
    return [
        _normalize_continuity_issue_payload(item)
        for item in payload.get("segment_issues", [])
        if isinstance(item, dict) and str(item.get("scene_id", "") or "") == scene_id
    ]


def _normalize_continuity_issue_payload(item: dict[str, object]) -> dict[str, object]:
    return {
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


def _resolve_scene_repair_segment_ids(
    *,
    project_package,
    scene_id: str,
    scene_issues: list[dict[str, object]],
    related_segment_issues: list[dict[str, object]],
) -> tuple[list[str], str]:
    scene_segment_ids = _resolve_selected_segment_ids(project_package, scene_id=scene_id) or set()
    if _scene_repair_requires_full_scene(scene_issues):
        return sorted(scene_segment_ids), "full_scene_global_issue"

    localized_segment_ids: set[str] = set()
    for issue in scene_issues:
        segment_id = str(issue.get("segment_id", "") or "").strip()
        if segment_id and segment_id in scene_segment_ids:
            localized_segment_ids.add(segment_id)
    for issue in related_segment_issues:
        segment_id = str(issue.get("segment_id", "") or "").strip()
        recommended_action = str(issue.get("recommended_action", "") or "").strip()
        if (
            segment_id
            and segment_id in scene_segment_ids
            and recommended_action in SCENE_REPAIR_SEGMENT_ACTIONS
        ):
            localized_segment_ids.add(segment_id)
    if localized_segment_ids:
        return sorted(localized_segment_ids), "localized_segments"
    return sorted(scene_segment_ids), "full_scene_fallback"


def _scene_repair_requires_full_scene(scene_issues: list[dict[str, object]]) -> bool:
    for issue in scene_issues:
        code = str(issue.get("code", "") or "").strip()
        segment_id = str(issue.get("segment_id", "") or "").strip()
        if code in SCENE_REPAIR_GLOBAL_CODES:
            return True
        if code == "scene_master_frame_status_mismatch" and not segment_id:
            return True
    return False


def _build_scene_repair_summary(selection_mode: str) -> str:
    if selection_mode == "localized_segments":
        return (
            "已识别 scene 级连续性问题，并完成修复规划。"
            "当前只更新修复方案，不会自动重生成场景母图或重跑受影响片段，"
            "后续需要人工决定是否执行。"
        )
    if selection_mode == "full_scene_global_issue":
        return (
            "已识别 scene 级全局连续性问题，并完成修复规划。"
            "当前只记录需要重生成场景母图和整 scene 媒体的建议动作，"
            "不会自动开始执行。"
        )
    return (
        "已识别 scene 级连续性问题，但当前报告无法稳定定位到更小范围。"
        "系统已生成整 scene 的修复规划，后续是否重生成母图和媒体由人工决定。"
    )


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


def _apply_repaired_scene_to_project_package(
    project_package,
    repaired_scene,
    *,
    target_segment_ids: list[str],
):
    repaired_scene_contract = repaired_scene
    target_segment_set = set(target_segment_ids)

    for scene_index, scene in enumerate(project_package.scenes):
        if scene.scene_id != repaired_scene_contract.scene_id:
            continue
        updated_scene_segments: list[VideoSegment] = []
        for segment in scene.segments:
            if target_segment_set and segment.segment_id not in target_segment_set:
                updated_scene_segments.append(segment)
                continue
            updated_scene_segments.append(
                VideoSegment.from_dict(
                    {
                        **to_jsonable(segment),
                        "scene_anchor": repaired_scene_contract.scene_anchor,
                        "scene_bible": to_jsonable(repaired_scene_contract.scene_bible),
                    }
                )
            )
        project_package.scenes[scene_index] = type(scene).from_dict(
            {
                **to_jsonable(scene),
                "scene_anchor": repaired_scene_contract.scene_anchor,
                "scene_bible": to_jsonable(repaired_scene_contract.scene_bible),
                "scene_master_frame_prompt": repaired_scene_contract.scene_master_frame_prompt,
                "scene_master_frame_path": repaired_scene_contract.scene_master_frame_path,
                "scene_master_frame_url": repaired_scene_contract.scene_master_frame_url,
                "scene_master_frame_status": repaired_scene_contract.scene_master_frame_status,
                "scene_master_frame_error": repaired_scene_contract.scene_master_frame_error,
                "segments": [to_jsonable(item) for item in updated_scene_segments],
            }
        )
        break
    else:
        raise ValueError(f"Scene {repaired_scene_contract.scene_id} not found in current project package.")

    for index, segment in enumerate(project_package.segments):
        if segment.scene_id != repaired_scene_contract.scene_id:
            continue
        if target_segment_set and segment.segment_id not in target_segment_set:
            continue
        project_package.segments[index] = VideoSegment.from_dict(
            {
                **to_jsonable(segment),
                "scene_anchor": repaired_scene_contract.scene_anchor,
                "scene_bible": to_jsonable(repaired_scene_contract.scene_bible),
            }
        )
    return project_package


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
        project_package.scenes,
        project_package.segments,
        rebuilt_scene_images,
        project_package.character_images,
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
        "scene_master_frame_status": "planned",
        "scene_master_frame_url": "",
        "scene_master_frame_error": "",
        "error": "",
    }
    return SceneImageTask.from_dict(payload)


def _reset_seedance_clip_task_for_repair(task: SeedanceClipTask) -> SeedanceClipTask:
    payload = {
        **to_jsonable(task),
        "remote_task_id": "",
        "submit_status": "planned",
        "remote_status": "planned",
        "video_url": "",
        "cover_url": "",
        "last_frame_url": "",
        "last_frame_path": "",
        "downloaded_path": "",
        "storyboard_grid_path": "",
        "storyboard_grid_url": "",
        "storyboard_grid_prompt": "",
        "storyboard_grid_status": "planned",
        "storyboard_grid_error": "",
        "storyboard_grid_request_info": {},
        "storyboard_scene_descriptions": [],
        "error": "",
    }
    return SeedanceClipTask.from_dict(payload)
