from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from storyforge.api.serializers import (
    build_project_detail_response,
    build_project_summary_responses,
)
from storyforge.api.schemas import (
    CreateContinuityRepairBatchTaskRequest,
    CreateContinuityRepairTaskRequest,
    CreateStageTaskRequest,
    CreateStoryTaskRequest,
    JobAcceptedResponse,
    ProjectDeletedResponse,
    CharacterImageVersionSelectionResponse,
    CharacterPromptUpdateResponse,
    ResetSegmentPromptRequest,
    SelectCharacterImageVersionRequest,
    SegmentPromptUpdateResponse,
    ProjectDetailResponse,
    ProjectSummaryResponse,
    StorySourceResponse,
    UpdateCharacterPromptRequest,
    UpdateSegmentPromptRequest,
    UpdateStorySourceRequest,
)
from storyforge.application.projects import ProjectRecord
from storyforge.application.tasks import utc_now
from storyforge.application.project_deletion import delete_project_output_dirs
from storyforge.application.task_support import resolve_pipeline_root_task_id
from storyforge.core.io import read_json, write_json
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import DraftChapter, StorySourcePackage
from storyforge.domains.video.contracts import VideoScene, VideoSegment
from storyforge.domains.video.service import NovelToVideoService
from storyforge.pipelines.story_files import (
    clear_story_derived_artifacts,
    prune_story_derived_result,
    write_story_source_files,
)


router = APIRouter(prefix="/v1/projects", tags=["projects"])


PROMPT_UPDATE_FIELDS = {"scene_master_frame_prompt", "video_prompt"}
CHARACTER_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _load_json_file(path: Path, fallback):
    if not path.exists():
        return fallback
    return read_json(path)


def _normalize_prompt_updates(payload: UpdateSegmentPromptRequest) -> dict[str, str]:
    updates: dict[str, str] = {}
    for field in PROMPT_UPDATE_FIELDS:
        raw_value = getattr(payload, field)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            raise HTTPException(status_code=422, detail=f"{field} 不能为空。")
        updates[field] = value
    if not updates:
        raise HTTPException(status_code=422, detail="至少需要提交一个 prompt 字段。")
    return updates


def _load_character_prompt_target(
    output_dir: Path,
    character_name: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    path = output_dir / "character_image_manifest.json"
    items = _load_json_file(path, [])
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="character_image_manifest.json 格式无效。")
    for item in items:
        if isinstance(item, dict) and str(item.get("character_name", "")).strip() == character_name:
            return items, item
    raise HTTPException(status_code=404, detail=f"Character {character_name} not found in character_image_manifest.json")


def _update_character_prompt(output_dir: Path, character_name: str, prompt: str) -> list[str]:
    items, target = _load_character_prompt_target(output_dir, character_name)
    _delete_character_candidate_file(target.get("candidate_output_path", ""), output_dir=output_dir)
    target["candidate_generated_url"] = ""
    target["candidate_output_path"] = ""
    target["prompt"] = prompt
    target["status"] = "planned"
    target["error"] = ""
    path = output_dir / "character_image_manifest.json"
    write_json(path, items)
    return ["prompt"]


def _resolve_character_image_path(raw_path: object, *, output_dir: Path | None = None) -> Path | None:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute() and output_dir is not None:
        path = output_dir / path
    return path.resolve(strict=False)


def _delete_character_image_variant_files(
    raw_path: object,
    *,
    output_dir: Path | None = None,
    keep_path: Path | None = None,
) -> None:
    path = _resolve_character_image_path(raw_path, output_dir=output_dir)
    if path is None:
        return
    keep_resolved = keep_path.resolve(strict=False) if keep_path is not None else None
    candidates = {path}
    if path.suffix.lower() in CHARACTER_IMAGE_SUFFIXES:
        candidates.update(path.with_suffix(suffix) for suffix in CHARACTER_IMAGE_SUFFIXES)
    for candidate in candidates:
        if keep_resolved is not None and candidate.resolve(strict=False) == keep_resolved:
            continue
        try:
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
        except OSError:
            continue


def _delete_character_candidate_file(raw_path: object, *, output_dir: Path | None = None) -> None:
    path = _resolve_character_image_path(raw_path, output_dir=output_dir)
    if path is None:
        return
    try:
        _delete_character_image_variant_files(path)
    except OSError:
        return


def _select_character_image_version(
    output_dir: Path,
    character_name: str,
    version: str,
) -> tuple[str, str]:
    items, target = _load_character_prompt_target(output_dir, character_name)
    if version not in {"current", "candidate"}:
        raise HTTPException(status_code=422, detail="version 只能是 current 或 candidate。")
    candidate_url = str(target.get("candidate_generated_url", "") or "").strip()
    candidate_path = str(target.get("candidate_output_path", "") or "").strip()
    if version == "candidate":
        current_path = str(target.get("output_path", "") or "").strip()
        if candidate_url:
            target["generated_url"] = candidate_url
        if candidate_path and current_path:
            source_path = _resolve_character_image_path(candidate_path, output_dir=output_dir)
            target_path = _resolve_character_image_path(current_path, output_dir=output_dir)
            if source_path is not None and target_path is not None and source_path.exists() and source_path.is_file():
                _delete_character_image_variant_files(target_path, keep_path=target_path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes())
        elif candidate_url and current_path:
            _delete_character_image_variant_files(current_path, output_dir=output_dir)
    _delete_character_candidate_file(candidate_path, output_dir=output_dir)
    target["candidate_generated_url"] = ""
    target["candidate_output_path"] = ""
    target["status"] = "completed"
    target["error"] = ""
    write_json(output_dir / "character_image_manifest.json", items)
    return str(target.get("generated_url", "") or ""), str(target.get("candidate_generated_url", "") or "")


def _load_segment_prompt_target(output_dir: Path, segment_id: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    path = output_dir / "segment_plan.json"
    plan = _load_json_file(path, [])
    if not isinstance(plan, list):
        raise HTTPException(status_code=400, detail="segment_plan.json 格式无效。")
    for item in plan:
        if isinstance(item, dict) and str(item.get("segment_id", "")) == segment_id:
            return plan, item
    raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found in segment_plan.json")


def _load_scene_prompt_target(output_dir: Path, scene_id: str) -> VideoScene | None:
    path = output_dir / "scene_plan.json"
    plan = _load_json_file(path, {"scenes": []})
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list):
        return None
    for item in scenes:
        if isinstance(item, dict) and str(item.get("scene_id", "")) == scene_id:
            return VideoScene.from_dict(item)
    return None


def _build_prompt_reset_service(container) -> NovelToVideoService:
    return NovelToVideoService(
        seedance_config=SeedanceConfig(
            model=container.config.seedance.model,
            base_url=container.config.seedance.base_url,
            with_audio=container.config.seedance.with_audio,
            subtitle_mode=container.config.seedance.subtitle_mode,
            subtitle_style=container.config.seedance.subtitle_style,
        )
    )


def _build_default_segment_prompt(output_dir: Path, segment_id: str, field: str, container) -> tuple[str, str]:
    _plan, raw_segment = _load_segment_prompt_target(output_dir, segment_id)
    segment = VideoSegment.from_dict(raw_segment)
    service = _build_prompt_reset_service(container)
    if field == "video_prompt":
        scene = _load_scene_prompt_target(output_dir, segment.scene_id)
        return service._build_seedance_clip_prompt(segment, scene=scene), segment.scene_id
    if field == "scene_master_frame_prompt":
        scene = _load_scene_prompt_target(output_dir, segment.scene_id)
        return service._build_scene_master_frame_prompt(scene), segment.scene_id
    raise HTTPException(status_code=422, detail=f"不支持重置字段：{field}")


def _update_segment_plan_prompts(output_dir: Path, segment_id: str, updates: dict[str, str]) -> tuple[set[str], str]:
    path = output_dir / "segment_plan.json"
    plan = _load_json_file(path, [])
    if not isinstance(plan, list):
        raise HTTPException(status_code=400, detail="segment_plan.json 格式无效。")

    matched_segment: dict[str, object] | None = None
    for item in plan:
        if isinstance(item, dict) and str(item.get("segment_id", "")) == segment_id:
            matched_segment = item
            break
    if matched_segment is None:
        raise HTTPException(status_code=404, detail=f"Segment {segment_id} not found in segment_plan.json")

    scene_id = str(matched_segment.get("scene_id", "") or "")
    changed: set[str] = set()
    for field in ("video_prompt",):
        if field in updates and matched_segment.get(field) != updates[field]:
            matched_segment[field] = updates[field]
            changed.add(field)
    if changed:
        write_json(path, plan)
    return changed, scene_id


def _update_scene_plan_master_prompt(output_dir: Path, scene_id: str, prompt: str | None) -> set[str]:
    if not prompt or not scene_id:
        return set()
    path = output_dir / "scene_plan.json"
    plan = _load_json_file(path, {"scenes": []})
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list):
        return set()

    changed: set[str] = set()
    for scene in scenes:
        if isinstance(scene, dict) and str(scene.get("scene_id", "")) == scene_id:
            if scene.get("scene_master_frame_prompt") != prompt:
                scene["scene_master_frame_prompt"] = prompt
                changed.add("scene_master_frame_prompt")
            if changed:
                _delete_output_file(scene.get("scene_master_frame_path"))
                scene["scene_master_frame_url"] = ""
                scene["scene_master_frame_status"] = "planned"
                scene["scene_master_frame_error"] = ""
                scene["scene_master_request_info"] = {}
            break
    if changed:
        write_json(path, plan)
    return changed


def _update_scene_image_manifest_prompts(output_dir: Path, segment_id: str, scene_id: str, updates: dict[str, str]) -> set[str]:
    path = output_dir / "scene_image_manifest.json"
    tasks = _load_json_file(path, [])
    if not isinstance(tasks, list):
        return set()

    changed: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        is_target_scene = scene_id and str(task.get("scene_id", "")) == scene_id
        if "scene_master_frame_prompt" in updates and is_target_scene:
            if task.get("scene_master_frame_prompt") != updates["scene_master_frame_prompt"]:
                task["scene_master_frame_prompt"] = updates["scene_master_frame_prompt"]
                changed.add("scene_master_frame_prompt")
                _delete_output_file(task.get("scene_master_frame_path"))
                task["scene_master_frame_url"] = ""
                task["scene_master_frame_status"] = "planned"
                task["scene_master_frame_error"] = ""
    if changed:
        write_json(path, tasks)
    return changed


def _delete_output_file(raw_path: object) -> None:
    if not raw_path:
        return
    path = Path(str(raw_path))
    if path.exists() and path.is_file():
        path.unlink()


def _reset_seedance_clip_after_prompt_change(clip: dict[str, object]) -> None:
    _delete_output_file(clip.get("downloaded_path"))
    _delete_output_file(clip.get("output_path"))
    clip["submitted_prompt"] = ""
    clip["submit_variant"] = ""
    clip["submitted_reference_bindings"] = []
    clip["submitted_request_info"] = {}
    clip["remote_task_id"] = ""
    clip["submit_status"] = "planned"
    clip["remote_status"] = "planned"
    clip["video_url"] = ""
    clip["cover_url"] = ""
    clip["last_frame_url"] = ""
    clip["last_frame_path"] = ""
    clip["downloaded_path"] = ""
    clip["error"] = ""


def _update_seedance_manifest_prompt(output_dir: Path, segment_id: str, prompt: str | None) -> set[str]:
    if not prompt:
        return set()
    path = output_dir / "seedance_manifest.json"
    manifest = _load_json_file(path, {"clips": []})
    clips = manifest.get("clips") if isinstance(manifest, dict) else None
    if not isinstance(clips, list):
        return set()

    changed: set[str] = set()
    for clip in clips:
        if isinstance(clip, dict) and str(clip.get("segment_id", "")) == segment_id:
            if clip.get("prompt") != prompt:
                clip["prompt"] = prompt
                _reset_seedance_clip_after_prompt_change(clip)
                changed.add("video_prompt")
            break
    if changed:
        write_json(path, manifest)
    return changed


def _invalidate_seedance_scene_master_references(output_dir: Path, scene_id: str, *, enabled: bool) -> set[str]:
    if not enabled or not scene_id:
        return set()
    path = output_dir / "seedance_manifest.json"
    manifest = _load_json_file(path, {"clips": []})
    clips = manifest.get("clips") if isinstance(manifest, dict) else None
    if not isinstance(clips, list):
        return set()

    changed = False
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        if str(clip.get("scene_id", "") or "") != scene_id:
            continue
        if clip.get("scene_master_url"):
            clip["scene_master_url"] = ""
            changed = True
        if clip.get("submit_status") not in {"", "planned"} or clip.get("remote_status") not in {"", "planned"}:
            _reset_seedance_clip_after_prompt_change(clip)
            changed = True
    if changed:
        write_json(path, manifest)
        return {"video_prompt"}
    return set()


def _ensure_live_llm_requested(use_llm: bool | None) -> None:
    if use_llm is False:
        raise HTTPException(
            status_code=400,
            detail="Non-LLM mode has been removed. Configure DeepSeek and keep use_llm=true.",
        )


def _apply_llm_selection(task_payload: dict[str, object], provider: str | None, model: str | None) -> None:
    if provider:
        task_payload["llm_provider"] = provider
    if model:
        task_payload["llm_model"] = model


def _apply_continuity_review_mode(task_payload: dict[str, object], mode: str | None) -> None:
    normalized = str(mode or "").strip().lower()
    if normalized in {"off", "auto", "on"}:
        task_payload["continuity_review_mode"] = normalized


def _apply_media_watermark_options(
    task_payload: dict[str, object],
    *,
    seedream_watermark: bool | None,
    seedance_watermark: bool | None,
) -> None:
    if seedream_watermark is not None:
        task_payload["seedream_watermark"] = bool(seedream_watermark)
    if seedance_watermark is not None:
        task_payload["seedance_watermark"] = bool(seedance_watermark)


def _apply_storyboard_options(
    task_payload: dict[str, object],
    payload: CreateStageTaskRequest,
) -> None:
    if payload.video_mode:
        task_payload["video_mode"] = payload.video_mode
    _apply_image_generation_options(task_payload, payload)
    if payload.storyboard_image_model:
        task_payload["storyboard_image_model"] = payload.storyboard_image_model.strip()
    if payload.storyboard_size:
        task_payload["storyboard_size"] = payload.storyboard_size.strip()
    if payload.storyboard_aspect_ratio:
        task_payload["storyboard_aspect_ratio"] = payload.storyboard_aspect_ratio.strip()


def _apply_image_generation_options(
    task_payload: dict[str, object],
    payload: CreateStageTaskRequest,
) -> None:
    if payload.image_model:
        task_payload["image_model"] = payload.image_model.strip()
        task_payload.setdefault("storyboard_image_model", payload.image_model.strip())
    if payload.image_size:
        task_payload["image_size"] = payload.image_size.strip()
        task_payload.setdefault("storyboard_size", payload.image_size.strip())
    if payload.image_aspect_ratio:
        task_payload["image_aspect_ratio"] = payload.image_aspect_ratio.strip()
        task_payload.setdefault("storyboard_aspect_ratio", payload.image_aspect_ratio.strip())


def _normalize_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def _apply_pipeline_root_task_id(
    container,
    task_payload: dict[str, object],
    *,
    project_id: str,
    source_task_id: str,
) -> None:
    source_task = container.task_queue.store.get(source_task_id)
    if source_task is None or source_task.project_id != project_id:
        return
    task_payload["pipeline_root_task_id"] = resolve_pipeline_root_task_id(source_task)


@router.get("", response_model=list[ProjectSummaryResponse])
async def list_projects(request: Request) -> list[ProjectSummaryResponse]:
    container = request.app.state.container
    return build_project_summary_responses(
        [project for project in container.project_store.list() if _is_visible_project(project)],
        container.task_queue.store,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: str, request: Request) -> ProjectDetailResponse:
    container = request.app.state.container
    project = container.project_store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return build_project_detail_response(project, container.task_queue.store)


@router.delete("/{project_id}", response_model=ProjectDeletedResponse)
async def delete_project(project_id: str, request: Request) -> ProjectDeletedResponse:
    return delete_project_records(project_id, request.app.state.container)


def delete_project_records(project_id: str, container) -> ProjectDeletedResponse:
    project = container.project_store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    project_tasks = container.task_queue.store.list(project_id=project_id)
    active_tasks = [
        item.task_id
        for item in project_tasks
        if item.status in {"queued", "running"}
    ]
    if active_tasks:
        raise HTTPException(
            status_code=409,
            detail=(
                "Project has queued or running tasks and cannot be deleted yet: "
                + ", ".join(active_tasks)
            ),
        )

    output_report = delete_project_output_dirs(
        project_root=container.project_root,
        output_dir=container.config.paths.output_dir,
        tasks=project_tasks,
    )
    if output_report.errors:
        raise HTTPException(
            status_code=500,
            detail="Project output cleanup failed: " + "; ".join(output_report.errors),
        )

    deleted_task_count = container.task_queue.store.delete_project_tasks(project_id)
    deleted = container.project_store.delete(project_id)
    return ProjectDeletedResponse(
        project_id=project_id,
        deleted=deleted,
        deleted_task_count=deleted_task_count,
        deleted_output_count=output_report.deleted_count,
        deleted_output_paths=output_report.deleted_paths,
        skipped_output_paths=output_report.skipped_paths,
    )


@router.post("/novel", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_story_job(
    payload: CreateStoryTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project_store = container.project_store
    project_id = payload.project_id
    if project_id:
        project = project_store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    else:
        project = project_store.create(payload.brief.model_dump())
        project_id = project.project_id

    task_payload = {
        "project_id": project_id,
        "brief": payload.brief.model_dump(),
        "use_llm": payload.use_llm,
    }
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    record = await container.task_queue.submit(
        project_id=project_id,
        task_type="project.story",
        payload=task_payload,
    )
    project_store.attach_task(project_id, record.task_id, payload.brief.model_dump())
    return JobAcceptedResponse(project_id=project_id, task_id=record.task_id, status=record.status)


@router.post("/scene-structure", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scene_structure_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    source_task = _resolve_story_source_task(
        container,
        payload.project_id,
        payload.source_task_id,
        require_completed=True,
    )
    existing_task = _find_existing_revisioned_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.scene_structure",
        source_task_id=payload.source_task_id,
        pipeline_root_task_id=resolve_pipeline_root_task_id(source_task),
        story_source_revision=str(source_task.result.get("story_source_revision", "")),
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    if existing_task is not None:
        _restore_existing_stage_result(
            container,
            existing_task=existing_task,
            source_task=source_task,
            pipeline_root_task_id=resolve_pipeline_root_task_id(source_task),
        )
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
        "use_llm": True if payload.use_llm is None else payload.use_llm,
    }
    task_payload["pipeline_root_task_id"] = resolve_pipeline_root_task_id(source_task)
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.scene_structure",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/segment-contracts", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_segment_contracts_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    source_task = _resolve_story_source_task(
        container,
        payload.project_id,
        payload.source_task_id,
        require_completed=True,
    )
    if not (source_task.result and source_task.result.get("scene_plan_path")):
        raise HTTPException(
            status_code=400,
            detail="Scene structure artifacts are missing. Generate scene structure first.",
        )

    existing_task = _find_existing_revisioned_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.segment_contracts",
        source_task_id=payload.source_task_id,
        pipeline_root_task_id=resolve_pipeline_root_task_id(source_task),
        story_source_revision=str(source_task.result.get("story_source_revision", "")),
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    if existing_task is not None:
        _restore_existing_stage_result(
            container,
            existing_task=existing_task,
            source_task=source_task,
            pipeline_root_task_id=resolve_pipeline_root_task_id(source_task),
        )
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
        "use_llm": True if payload.use_llm is None else payload.use_llm,
    }
    if payload.resume_from_progress:
        task_payload["resume_from_progress"] = True
    task_payload["pipeline_root_task_id"] = resolve_pipeline_root_task_id(source_task)
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.segment_contracts",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/continuity-repair", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_continuity_repair_job(
    payload: CreateContinuityRepairTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.continuity_repair",
        source_task_id=payload.source_task_id,
        segment_id=payload.segment_id,
        scene_id=payload.scene_id,
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    if existing_task is not None:
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
        "use_llm": True if payload.use_llm is None else payload.use_llm,
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    if payload.scene_id:
        task_payload["scene_id"] = payload.scene_id
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.continuity_repair",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/continuity-repair-batch", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_continuity_repair_batch_job(
    payload: CreateContinuityRepairBatchTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.continuity_repair_batch",
        source_task_id=payload.source_task_id,
        segment_id=None,
        scene_id=None,
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    if existing_task is not None:
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
        "use_llm": True if payload.use_llm is None else payload.use_llm,
        "severity_threshold": payload.severity_threshold,
        "max_units_per_batch": payload.max_units_per_batch,
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.continuity_repair_batch",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )

def _find_existing_revisioned_stage_task(
    container,
    *,
    project_id: str,
    task_type: str,
    source_task_id: str,
    pipeline_root_task_id: str,
    story_source_revision: str,
    continuity_review_mode: str | None = None,
    seedream_watermark: bool | None = None,
    seedance_watermark: bool | None = None,
):
    expected_mode = str(continuity_review_mode or "auto").strip().lower() or "auto"
    expected_seedream_watermark = _normalize_optional_bool(seedream_watermark)
    expected_seedance_watermark = _normalize_optional_bool(seedance_watermark)
    for task in container.task_queue.store.list(project_id=project_id):
        if task.task_type != task_type:
            continue
        if str(task.payload.get("source_task_id", "")) != source_task_id:
            continue
        if expected_seedream_watermark is not None:
            if _normalize_optional_bool(task.payload.get("seedream_watermark")) != expected_seedream_watermark:
                continue
        if expected_seedance_watermark is not None:
            if _normalize_optional_bool(task.payload.get("seedance_watermark")) != expected_seedance_watermark:
                continue
        task_mode = str(task.payload.get("continuity_review_mode", "auto") or "auto").strip().lower() or "auto"
        if task_mode != expected_mode:
            continue
        if task.status in {"queued", "running"}:
            return task
        if task.status != "completed":
            continue
        result = task.result or {}
        if str(result.get("pipeline_root_task_id", pipeline_root_task_id)) != pipeline_root_task_id:
            continue
        existing_revision = str(result.get("story_source_revision", ""))
        if not story_source_revision or existing_revision == story_source_revision:
            return task
    return None


def _restore_existing_stage_result(
    container,
    *,
    existing_task,
    source_task,
    pipeline_root_task_id: str,
) -> None:
    if existing_task.status != "completed" or not existing_task.result:
        return
    shared_result = {
        key: value
        for key, value in existing_task.result.items()
        if key not in {"task_stage", "source_task_id"}
    }
    if not shared_result:
        return
    shared_result["artifact_revision"] = utc_now()
    for task_id in {source_task.task_id, pipeline_root_task_id}:
        if not task_id or task_id == existing_task.task_id:
            continue
        if container.task_queue.store.get(task_id) is None:
            continue
        container.task_queue.store.update_result(task_id, shared_result)


def _find_existing_stage_task(
    container,
    *,
    project_id: str,
    task_type: str,
    source_task_id: str,
    segment_id: str | None,
    scene_id: str | None = None,
    master_only: bool = False,
    merge_only: bool = False,
    continuity_review_mode: str | None = None,
    seedream_watermark: bool | None = None,
    seedance_watermark: bool | None = None,
    image_model: str | None = None,
    image_size: str | None = None,
    image_aspect_ratio: str | None = None,
):
    expected_segment_id = segment_id or ""
    expected_scene_id = scene_id or ""
    expected_mode = str(continuity_review_mode or "auto").strip().lower() or "auto"
    expected_seedream_watermark = _normalize_optional_bool(seedream_watermark)
    expected_seedance_watermark = _normalize_optional_bool(seedance_watermark)
    expected_image_options = {
        "image_model": str(image_model or "").strip(),
        "image_size": str(image_size or "").strip(),
        "image_aspect_ratio": str(image_aspect_ratio or "").strip(),
    }
    for task in container.task_queue.store.list(project_id=project_id):
        if task.task_type != task_type:
            continue
        if str(task.payload.get("source_task_id", "")) != source_task_id:
            continue
        if str(task.payload.get("segment_id", "")) != expected_segment_id:
            continue
        if str(task.payload.get("scene_id", "")) != expected_scene_id:
            continue
        if bool(task.payload.get("master_only", False)) != master_only:
            continue
        if bool(task.payload.get("merge_only", False)) != merge_only:
            continue
        if expected_seedream_watermark is not None:
            if _normalize_optional_bool(task.payload.get("seedream_watermark")) != expected_seedream_watermark:
                continue
        if expected_seedance_watermark is not None:
            if _normalize_optional_bool(task.payload.get("seedance_watermark")) != expected_seedance_watermark:
                continue
        task_mode = str(task.payload.get("continuity_review_mode", "auto") or "auto").strip().lower() or "auto"
        if task_mode != expected_mode:
            continue
        if not _stage_image_options_match(task.payload, expected_image_options):
            continue
        if task.status in {"queued", "running"}:
            return task
    return None


def _stage_image_options_match(task_payload: dict[str, object], expected: dict[str, str]) -> bool:
    for key, expected_value in expected.items():
        if not expected_value:
            continue
        actual = str(task_payload.get(key, "") or "").strip()
        if not actual and key == "image_model":
            actual = str(task_payload.get("storyboard_image_model", "") or "").strip()
        if not actual and key == "image_size":
            actual = str(task_payload.get("storyboard_size", "") or "").strip()
        if not actual and key == "image_aspect_ratio":
            actual = str(task_payload.get("storyboard_aspect_ratio", "") or "").strip()
        if actual != expected_value:
            return False
    return True


@router.post("/characters", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_character_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    _ensure_live_llm_requested(payload.use_llm)
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    if payload.use_llm is not None:
        task_payload["use_llm"] = payload.use_llm
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)
    character_name = str(payload.character_name or "").strip()
    if character_name:
        source_task = _resolve_story_source_task(container, payload.project_id, payload.source_task_id)
        output_dir = _output_dir(source_task)
        items, target = _load_character_prompt_target(output_dir, character_name)
        _delete_character_candidate_file(target.get("candidate_output_path", ""))
        target["candidate_generated_url"] = ""
        target["candidate_output_path"] = ""
        write_json(output_dir / "character_image_manifest.json", items)
        task_payload["character_name"] = character_name

    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.characters",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.put(
    "/{project_id}/character-prompts/{source_task_id}/{character_name}",
    response_model=CharacterPromptUpdateResponse,
)
async def update_character_prompt(
    project_id: str,
    source_task_id: str,
    character_name: str,
    payload: UpdateCharacterPromptRequest,
    request: Request,
) -> CharacterPromptUpdateResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    output_dir = _output_dir(source_task)
    prompt = str(payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt 不能为空。")
    resolved_character_name = str(character_name or "").strip()
    if not resolved_character_name:
        raise HTTPException(status_code=422, detail="character_name 不能为空。")
    updated_fields = _update_character_prompt(output_dir, resolved_character_name, prompt)
    return CharacterPromptUpdateResponse(
        project_id=project_id,
        source_task_id=source_task_id,
        character_name=resolved_character_name,
        updated_fields=updated_fields,
        prompt=prompt,
    )




@router.post(
    "/{project_id}/character-images/{source_task_id}/{character_name}/select",
    response_model=CharacterImageVersionSelectionResponse,
)
async def select_character_image_version(
    project_id: str,
    source_task_id: str,
    character_name: str,
    payload: SelectCharacterImageVersionRequest,
    request: Request,
) -> CharacterImageVersionSelectionResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    output_dir = _output_dir(source_task)
    resolved_character_name = str(character_name or "").strip()
    if not resolved_character_name:
        raise HTTPException(status_code=422, detail="character_name 不能为空。")
    current_url, candidate_url = _select_character_image_version(output_dir, resolved_character_name, payload.version)
    return CharacterImageVersionSelectionResponse(
        project_id=project_id,
        source_task_id=source_task_id,
        character_name=resolved_character_name,
        selected_version=payload.version,
        current_url=current_url,
        candidate_url=candidate_url,
    )


@router.post("/scenes", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scene_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.scenes",
        source_task_id=payload.source_task_id,
        segment_id=payload.segment_id,
        scene_id=payload.scene_id,
        master_only=payload.master_only,
        merge_only=False,
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
        image_model=payload.image_model or payload.storyboard_image_model,
        image_size=payload.image_size or payload.storyboard_size,
        image_aspect_ratio=payload.image_aspect_ratio or payload.storyboard_aspect_ratio,
    )
    if existing_task is not None:
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    if payload.scene_id:
        task_payload["scene_id"] = payload.scene_id
    if payload.master_only:
        task_payload["master_only"] = True
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)

    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.scenes",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/storyboards", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_storyboard_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.storyboards",
        source_task_id=payload.source_task_id,
        segment_id=payload.segment_id,
        scene_id=payload.scene_id,
        merge_only=False,
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
        image_model=payload.image_model or payload.storyboard_image_model,
        image_size=payload.image_size or payload.storyboard_size,
        image_aspect_ratio=payload.image_aspect_ratio or payload.storyboard_aspect_ratio,
    )
    if existing_task is not None:
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
        "video_mode": "grid_storyboard",
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    if payload.scene_id:
        task_payload["scene_id"] = payload.scene_id
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)

    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.storyboards",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/videos", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_video_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.videos",
        source_task_id=payload.source_task_id,
        segment_id=payload.segment_id,
        scene_id=payload.scene_id,
        merge_only=payload.merge_only,
        continuity_review_mode=payload.continuity_review_mode,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    if existing_task is not None:
        return JobAcceptedResponse(
            project_id=payload.project_id,
            task_id=existing_task.task_id,
            status=existing_task.status,
        )

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
    _apply_pipeline_root_task_id(
        container,
        task_payload,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
    )
    if payload.merge_only:
        task_payload["merge_only"] = True
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    if payload.scene_id:
        task_payload["scene_id"] = payload.scene_id
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    _apply_continuity_review_mode(task_payload, payload.continuity_review_mode)
    _apply_media_watermark_options(
        task_payload,
        seedream_watermark=payload.seedream_watermark,
        seedance_watermark=payload.seedance_watermark,
    )
    _apply_storyboard_options(task_payload, payload)
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.videos",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )



@router.put(
    "/{project_id}/segment-prompts/{source_task_id}/{segment_id}",
    response_model=SegmentPromptUpdateResponse,
)
async def update_segment_prompts(
    project_id: str,
    source_task_id: str,
    segment_id: str,
    payload: UpdateSegmentPromptRequest,
    request: Request,
) -> SegmentPromptUpdateResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    output_dir = _output_dir(source_task)
    updates = _normalize_prompt_updates(payload)

    updated_fields, scene_id = _update_segment_plan_prompts(output_dir, segment_id, updates)
    updated_fields.update(
        _update_scene_plan_master_prompt(
            output_dir,
            scene_id,
            updates.get("scene_master_frame_prompt"),
        )
    )
    updated_fields.update(_update_scene_image_manifest_prompts(output_dir, segment_id, scene_id, updates))
    updated_fields.update(_update_seedance_manifest_prompt(output_dir, segment_id, updates.get("video_prompt")))
    updated_fields.update(
        _invalidate_seedance_scene_master_references(
            output_dir,
            scene_id,
            enabled="scene_master_frame_prompt" in updated_fields,
        )
    )

    return SegmentPromptUpdateResponse(
        project_id=project_id,
        source_task_id=source_task_id,
        segment_id=segment_id,
        updated_fields=sorted(updated_fields),
    )


@router.post(
    "/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset",
    response_model=SegmentPromptUpdateResponse,
)
async def reset_segment_prompt(
    project_id: str,
    source_task_id: str,
    segment_id: str,
    payload: ResetSegmentPromptRequest,
    request: Request,
) -> SegmentPromptUpdateResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    output_dir = _output_dir(source_task)
    prompt, scene_id = _build_default_segment_prompt(
        output_dir,
        segment_id,
        payload.field,
        container,
    )
    updates = {payload.field: prompt}
    updated_fields, resolved_scene_id = _update_segment_plan_prompts(output_dir, segment_id, updates)
    scene_id = resolved_scene_id or scene_id
    updated_fields.update(_update_scene_image_manifest_prompts(output_dir, segment_id, scene_id, updates))
    updated_fields.update(_update_seedance_manifest_prompt(output_dir, segment_id, updates.get("video_prompt")))
    return SegmentPromptUpdateResponse(
        project_id=project_id,
        source_task_id=source_task_id,
        segment_id=segment_id,
        updated_fields=sorted(updated_fields),
        reset_field=payload.field,
        prompt=prompt,
    )


@router.get("/{project_id}/story-source/{source_task_id}", response_model=StorySourceResponse)
async def get_story_source(
    project_id: str,
    source_task_id: str,
    request: Request,
) -> StorySourceResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    story_source = StorySourcePackage.from_dict(read_json(_story_source_path(source_task)))
    return _build_story_source_response(
        project_id=project_id,
        source_task_id=source_task_id,
        story_source=story_source,
        story_source_revision=(
            str(source_task.result.get("story_source_revision"))
            if source_task.result and source_task.result.get("story_source_revision")
            else None
        ),
    )


@router.put("/{project_id}/story-source/{source_task_id}", response_model=StorySourceResponse)
async def update_story_source(
    project_id: str,
    source_task_id: str,
    payload: UpdateStorySourceRequest,
    request: Request,
) -> StorySourceResponse:
    container = request.app.state.container
    source_task = _resolve_story_source_task(container, project_id, source_task_id)
    output_dir = _output_dir(source_task)

    existing = StorySourcePackage.from_dict(read_json(_story_source_path(source_task)))
    updated_story_source = StorySourcePackage(
        brief=existing.brief,
        title=payload.story_title.strip() or existing.title,
        chapters=[
            DraftChapter(
                number=item.number,
                title=item.title.strip() or f"第 {item.number} 章",
                summary=item.summary.strip(),
                markdown=item.markdown.strip(),
                agent_notes="user-edited",
            )
            for item in payload.chapters
        ],
    )
    if not updated_story_source.chapters:
        raise HTTPException(status_code=400, detail="Story source must contain at least one chapter.")

    story_files = write_story_source_files(output_dir, updated_story_source)

    clear_story_derived_artifacts(output_dir)

    updated_revision = utc_now()
    updated_result = prune_story_derived_result(source_task.result or {})
    updated_result.update(
        {
            "project_id": project_id,
            "story_title": updated_story_source.title,
            "output_dir": str(output_dir),
            "story_source_path": str(story_files.story_source_path),
            "story_source_revision": updated_revision,
            "pipeline_stage": "story_source_completed",
            "task_stage": "story",
            "pipeline_root_task_id": source_task.task_id,
            "source_task_id": source_task.task_id,
            "artifact_revision": updated_revision,
        }
    )
    container.task_queue.store.update_result(source_task.task_id, updated_result)
    container.project_store.mark_task_result(project_id, source_task.task_id, updated_result)

    return _build_story_source_response(
        project_id=project_id,
        source_task_id=source_task_id,
        story_source=updated_story_source,
        story_source_revision=updated_revision,
    )


def _resolve_story_source_task(
    container,
    project_id: str,
    source_task_id: str,
    *,
    require_completed: bool = False,
):
    project = container.project_store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    source_task = container.task_queue.store.get(source_task_id)
    if source_task is None or source_task.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Source task {source_task_id} not found")
    if require_completed and source_task.status != "completed":
        raise HTTPException(status_code=400, detail=f"Source task {source_task_id} is not completed yet")
    if not source_task.result or not source_task.result.get("story_source_path"):
        raise HTTPException(
            status_code=400,
            detail=f"Task {source_task_id} does not have editable story source output.",
        )
    return source_task


def _story_source_path(source_task) -> Path:
    return Path(str(source_task.result["story_source_path"]))


def _output_dir(source_task) -> Path:
    raw_output_dir = source_task.result.get("output_dir") if source_task.result else None
    if not raw_output_dir:
        raise HTTPException(status_code=400, detail=f"Task {source_task.task_id} has no output_dir.")
    return Path(str(raw_output_dir))


def _build_story_source_response(
    project_id: str,
    source_task_id: str,
    story_source: StorySourcePackage,
    story_source_revision: str | None,
) -> StorySourceResponse:
    return StorySourceResponse(
        project_id=project_id,
        source_task_id=source_task_id,
        story_title=story_source.title,
        story_source_revision=story_source_revision,
        chapters=[
            {
                "number": chapter.number,
                "title": chapter.title,
                "summary": chapter.summary,
                "markdown": chapter.markdown,
            }
            for chapter in story_source.chapters
        ],
    )


def _is_visible_project(project: ProjectRecord) -> bool:
    if project.brief.get("project_kind") == "image_generation" and project.brief.get("image_saved") is False:
        return False
    return True
