from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from storyforge.core.io import read_json, to_jsonable
from storyforge.application.task_support import (
    build_requested_image_error,
    build_requested_video_error,
    refresh_artifact_revision_for_tasks,
    load_novel_package,
    load_story_source,
    persist_task_progress,
    propagate_shared_result,
    resolve_continuity_review_mode,
    resolve_llm_selection,
    resolve_output_dir,
    resolve_pipeline_root_task_id,
    resolve_source_task,
    resolve_story_title,
)
from storyforge.application.tasks import QueuedTask, TaskExecutionError, utc_now
from storyforge.domains.novel.contracts import StoryBrief
from storyforge.pipelines.story_pipeline import (
    run_story_generation_pipeline,
    run_story_scene_structure_pipeline,
    run_story_segment_contracts_pipeline,
)
from storyforge.pipelines.video_pipeline import (
    run_character_image_pipeline,
    run_scene_continuity_repair_pipeline,
    run_segment_continuity_repair_pipeline,
    run_video_merge_pipeline,
    run_scene_image_pipeline,
    run_video_render_pipeline,
)
from storyforge.pipelines.video_planning import load_segment_contract_progress

if TYPE_CHECKING:
    from storyforge.application.task_runtime import TaskExecutionContext


REPAIR_BATCH_DEFAULT_LIMIT = 4
REPAIR_BATCH_MAX_LIMIT = 12
REPAIR_BATCH_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
REPAIR_BATCH_SCOPE_ORDER = {"scene": 0, "segment": 1}


def run_story_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    brief = StoryBrief.from_dict(task.payload["brief"])
    use_llm = bool(task.payload.get("use_llm", True))
    llm_provider, llm_model = resolve_llm_selection(task)
    continuity_review_mode = resolve_continuity_review_mode(task)
    output_root = _build_story_output_root(context, task)
    story_result = run_story_generation_pipeline(
        brief=brief,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        output_root=output_root,
    )
    response = {
        "project_id": task.project_id,
        "story_title": story_result.story_source.title,
        "output_dir": str(story_result.output_dir),
        "story_source_path": str(story_result.story_source_path),
        "story_source_revision": utc_now(),
        "pipeline_stage": "story_source_completed",
        "task_stage": "story",
        "pipeline_root_task_id": task.task_id,
        "source_task_id": task.task_id,
        "artifact_revision": utc_now(),
        "continuity_review_mode": continuity_review_mode,
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    return response


def run_scene_structure_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    story_source = load_story_source(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = {
        "project_id": task.project_id,
        "story_title": story_source.title,
        "output_dir": str(output_dir),
        "story_source_path": str(source_task.result["story_source_path"]),
        "story_source_revision": str(source_task.result.get("story_source_revision", utc_now())),
        "pipeline_stage": "scene_structure_started",
        "task_stage": "scene_structure",
        "pipeline_root_task_id": pipeline_root_task_id,
        "source_task_id": str(task.payload["source_task_id"]),
        "artifact_revision": utc_now(),
        "continuity_review_mode": continuity_review_mode,
    }
    persist_task_progress(context, task, partial_response)

    scene_structure_result = run_story_scene_structure_pipeline(
        story_source=story_source,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        output_root=output_dir,
    )
    response = {
        **partial_response,
        **_build_stage_reset_fields(clear_character_assets=True),
        "story_title": scene_structure_result.novel_package.outline.title,
        "novel_package_path": str(scene_structure_result.novel_package_path),
        "novel_audit_path": str(scene_structure_result.novel_audit_path),
        "story_memory_path": str(scene_structure_result.story_memory_path),
        "character_bible_path": str(scene_structure_result.character_bible_path),
        "scene_plan_path": str(scene_structure_result.scene_plan_path),
        "pipeline_stage": "scene_structure_completed",
    }
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="propagate",
    )
    return response


def run_segment_contracts_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    if not (source_task.result and source_task.result.get("scene_plan_path")):
        raise ValueError("Scene structure artifacts are missing. Generate scene structure first.")
    novel_package = load_novel_package(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    resume_from_progress = bool(task.payload.get("resume_from_progress", False))
    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="segment_contracts",
        pipeline_stage="segment_contracts_started",
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )
    if resume_from_progress:
        partial_response["resume_from_progress"] = True
        persist_task_progress(context, task, partial_response)

    def progress_callback(progress) -> None:
        _persist_stage_update(
            context,
            task,
            partial_response,
            pipeline_stage="segment_contracts_started",
            **_build_segment_contract_progress_result(output_dir, progress),
        )

    try:
        segment_contracts_result = run_story_segment_contracts_pipeline(
            novel_package=novel_package,
            config=context.config,
            project_root=context.project_root,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            continuity_review_mode=continuity_review_mode,
            output_root=output_dir,
            resume_from_progress=resume_from_progress,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        failure_progress = load_segment_contract_progress(output_dir)
        failure_response = {
            **partial_response,
            **_build_stage_reset_fields(clear_character_assets=False),
            **_build_segment_contract_output_paths(output_dir),
            **_build_segment_contract_progress_result(output_dir, failure_progress),
            "story_title": novel_package.outline.title,
            "pipeline_stage": "segment_contracts_failed",
        }
        raise TaskExecutionError(str(exc), result=failure_response) from exc

    response = {
        **partial_response,
        **_build_stage_reset_fields(clear_character_assets=False),
        "story_title": novel_package.outline.title,
        "story_memory_path": str(segment_contracts_result.story_memory_path),
        "character_bible_path": str(segment_contracts_result.character_bible_path),
        "character_images_path": str(segment_contracts_result.character_images_path),
        "scene_plan_path": str(segment_contracts_result.scene_plan_path),
        "segment_plan_path": str(segment_contracts_result.segment_plan_path),
        "segment_contract_progress_path": str(segment_contracts_result.segment_contract_progress_path),
        "scene_images_path": str(segment_contracts_result.scene_images_path),
        "seedance_manifest_path": str(segment_contracts_result.seedance_manifest_path),
        "pipeline_stage": "segment_contracts_completed",
        **_build_segment_contract_progress_result(
            output_dir,
            segment_contracts_result.video_planning.segment_contract_progress,
        ),
    }
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="propagate",
    )
    return response


def run_characters_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    novel_package = load_novel_package(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="characters",
        pipeline_stage="character_generation_started",
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )

    character_result = run_character_image_pipeline(
        novel_package=novel_package,
        config=context.config,
        project_root=context.project_root,
        output_root=output_dir,
        use_llm=use_llm,
        submit_characters=True,
    )
    response = {
        **partial_response,
        "story_title": character_result.project_package.title,
        "output_dir": str(character_result.output_dir),
        "character_bible_path": str(character_result.character_bible_path),
        "character_images_path": str(character_result.character_images_path),
        "scene_plan_path": str(character_result.scene_plan_path),
        "segment_plan_path": str(character_result.segment_plan_path),
        "scene_images_path": str(character_result.scene_images_path),
        "seedance_manifest_path": str(character_result.manifest_path),
        "character_seedream_execution_path": str(character_result.character_seedream_execution_path),
        "seedream_execution_path": str(character_result.seedream_execution_path),
        "pipeline_stage": "characters_completed",
    }
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="propagate",
    )
    image_error = build_requested_image_error(character_result.seedream_execution)
    if image_error:
        raise TaskExecutionError(image_error, result=response)
    return response


def run_scenes_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    segment_id = str(task.payload.get("segment_id", "")).strip() or None
    scene_id = str(task.payload.get("scene_id", "")).strip() or None
    master_only = bool(task.payload.get("master_only", False))
    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="scene_master_frames" if master_only else "scenes",
        pipeline_stage=(
            "scene_master_frame_generation_started"
            if master_only
            else "scene_generation_started"
        ),
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )

    scene_result = run_scene_image_pipeline(
        config=context.config,
        project_root=context.project_root,
        output_root=output_dir,
        submit_scenes=True,
        segment_id=segment_id,
        scene_id=scene_id,
        master_only=master_only,
        continuity_review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    response = {
        **partial_response,
        "story_title": scene_result.project_package.title,
        "output_dir": str(scene_result.output_dir),
        "character_bible_path": str(scene_result.character_bible_path),
        "character_images_path": str(scene_result.character_images_path),
        "scene_plan_path": str(scene_result.scene_plan_path),
        "segment_plan_path": str(scene_result.segment_plan_path),
        "scene_images_path": str(scene_result.scene_images_path),
        "seedance_manifest_path": str(scene_result.manifest_path),
        "character_seedream_execution_path": str(scene_result.character_seedream_execution_path),
        "scene_seedream_execution_path": str(scene_result.scene_seedream_execution_path),
        "seedream_execution_path": str(scene_result.seedream_execution_path),
        "pipeline_stage": "scene_master_frame_completed" if master_only else "scenes_completed",
    }
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="refresh" if (segment_id or scene_id) else "propagate",
    )
    scene_error = build_requested_image_error(scene_result.seedream_execution)
    if scene_error:
        raise TaskExecutionError(scene_error, result=response)
    return response


def run_videos_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    segment_id = str(task.payload.get("segment_id", "")).strip() or None
    scene_id = str(task.payload.get("scene_id", "")).strip() or None
    merge_only = bool(task.payload.get("merge_only", False))
    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="video_merge" if merge_only else "videos",
        pipeline_stage="video_merge_started" if merge_only else "video_render_started",
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )

    if merge_only:
        video_result = run_video_merge_pipeline(
            config=context.config,
            project_root=context.project_root,
            output_root=output_dir,
            continuity_review_mode=continuity_review_mode,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        response = {
            **partial_response,
            "story_title": resolve_story_title(source_task),
            "output_dir": str(video_result.output_dir),
            "seedance_manifest_path": str(video_result.manifest_path),
            "rendered_clips": [str(path) for path in video_result.rendered_clip_paths],
            "full_story_path": str(video_result.full_story_path),
            "pipeline_stage": "video_merge_completed",
            "merge_only": True,
            "merged_clip_count": video_result.merged_clip_count,
            "skipped_clip_count": video_result.skipped_clip_count,
        }
    else:
        video_result = run_video_render_pipeline(
            config=context.config,
            project_root=context.project_root,
            output_root=output_dir,
            submit_seedance=True,
            segment_id=segment_id,
            scene_id=scene_id,
            continuity_review_mode=continuity_review_mode,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        response = {
            **partial_response,
            "story_title": resolve_story_title(source_task),
            "output_dir": str(video_result.output_dir),
            "seedance_manifest_path": str(video_result.manifest_path),
            "seedance_execution_path": str(video_result.seedance_execution_path),
            "rendered_clips": [str(path) for path in video_result.rendered_clip_paths],
            "full_story_path": (
                str(video_result.full_story_path) if video_result.full_story_path else None
            ),
            "pipeline_stage": "video_completed",
            "seedance_submitted": video_result.seedance_execution.submitted,
        }
    if merge_only:
        response["merge_only"] = True
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="refresh" if (segment_id or scene_id) else "propagate",
    )
    if not merge_only:
        video_error = build_requested_video_error(video_result.seedance_execution)
        if video_error:
            raise TaskExecutionError(video_error, result=response)
    return response


def run_continuity_repair_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    segment_id = str(task.payload.get("segment_id", "")).strip()
    scene_id = str(task.payload.get("scene_id", "")).strip()
    if bool(segment_id) == bool(scene_id):
        raise ValueError("Provide exactly one of segment_id or scene_id for continuity repair.")

    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="continuity_repair",
        pipeline_stage="continuity_repair_started",
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )

    if scene_id:
        try:
            affected_segment_ids: set[str] = set()
            repair_result = run_scene_continuity_repair_pipeline(
                config=context.config,
                project_root=context.project_root,
                output_root=output_dir,
                scene_id=scene_id,
                use_llm=True,
                continuity_review_mode=continuity_review_mode,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
        except ValueError as exc:
            if "has no continuity issues to repair" not in str(exc):
                raise
            response = _build_repair_noop_response(
                partial_response=partial_response,
                source_task=source_task,
                repair_summary=f"Scene {scene_id} 当前没有需要修复的连续性问题。",
                scene_id=scene_id,
            )
            response = _build_completed_stage_response(response)
            _store_stage_result(context, task, response)
            _sync_stage_result(
                context,
                task=task,
                pipeline_root_task_id=pipeline_root_task_id,
                result=response,
                mode="refresh",
            )
            return response
        affected_segment_ids = set(repair_result.affected_segment_ids)
        response = _build_repair_plan_only_response(
            partial_response=partial_response,
            repair_result=repair_result,
            pending_media_actions=_build_scene_repair_pending_actions(repair_result),
            affected_segment_ids=sorted(affected_segment_ids),
        )
        response = _build_completed_stage_response(response)
        _store_stage_result(context, task, response)
        _sync_stage_result(
            context,
            task=task,
            pipeline_root_task_id=pipeline_root_task_id,
            result=response,
            mode="refresh",
        )
        return response

    try:
        repair_result = run_segment_continuity_repair_pipeline(
            config=context.config,
            project_root=context.project_root,
            output_root=output_dir,
            segment_id=segment_id,
            use_llm=True,
            continuity_review_mode=continuity_review_mode,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except ValueError as exc:
        if "has no continuity issues to repair" not in str(exc):
            raise
        response = _build_repair_noop_response(
            partial_response=partial_response,
            source_task=source_task,
            repair_summary=f"Segment {segment_id} 当前没有需要修复的连续性问题。",
            segment_id=segment_id,
        )
        response = _build_completed_stage_response(response)
        _store_stage_result(context, task, response)
        _sync_stage_result(
            context,
            task=task,
            pipeline_root_task_id=pipeline_root_task_id,
            result=response,
            mode="refresh",
        )
        return response
    response = _build_repair_plan_only_response(
        partial_response=partial_response,
        repair_result=repair_result,
        pending_media_actions=["regenerate_scene_images", "regenerate_video"],
        affected_segment_ids=[segment_id],
    )
    response = _build_completed_stage_response(response)
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="refresh",
    )
    return response


def run_continuity_repair_batch_task(
    context: TaskExecutionContext,
    task: QueuedTask,
) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    llm_provider, llm_model = resolve_llm_selection(task, source_task)
    continuity_review_mode = resolve_continuity_review_mode(task, source_task)
    severity_threshold = _normalize_repair_batch_severity(task.payload.get("severity_threshold"))
    max_units_per_batch = _normalize_repair_batch_limit(task.payload.get("max_units_per_batch"))

    partial_response = _start_stage_task(
        context,
        task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="continuity_repair_batch",
        pipeline_stage="continuity_repair_batch_started",
        pipeline_root_task_id=pipeline_root_task_id,
        continuity_review_mode=continuity_review_mode,
    )
    _persist_stage_update(
        context,
        task,
        partial_response,
        severity_threshold=severity_threshold,
        max_units_per_batch=max_units_per_batch,
        processed_unit_count=0,
        repaired_unit_count=0,
        noop_unit_count=0,
        failed_unit_count=0,
        repaired_scene_ids=[],
        repaired_segment_ids=[],
    )

    processed_targets: set[tuple[str, str]] = set()
    repaired_scene_ids: list[str] = []
    repaired_segment_ids: list[str] = []
    noop_targets: list[dict[str, str]] = []
    failed_targets: list[dict[str, str]] = []
    aggregate_pending_actions: list[str] = []
    latest_result_paths = _build_repair_output_paths(output_dir)

    while len(processed_targets) < max_units_per_batch:
        target = _select_next_repair_batch_target(
            output_dir=output_dir,
            severity_threshold=severity_threshold,
            processed_targets=processed_targets,
        )
        if target is None:
            break

        scope = str(target["scope"])
        target_id = str(target["target_id"])
        processed_targets.add((scope, target_id))

        try:
            if scope == "scene":
                repair_result = run_scene_continuity_repair_pipeline(
                    config=context.config,
                    project_root=context.project_root,
                    output_root=output_dir,
                    scene_id=target_id,
                    use_llm=True,
                    continuity_review_mode=continuity_review_mode,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
                repaired_scene_ids.append(target_id)
                latest_result_paths = _build_repair_paths_from_result(repair_result)
                aggregate_pending_actions = _merge_pending_actions(
                    aggregate_pending_actions,
                    _build_scene_repair_pending_actions(repair_result),
                )
            else:
                repair_result = run_segment_continuity_repair_pipeline(
                    config=context.config,
                    project_root=context.project_root,
                    output_root=output_dir,
                    segment_id=target_id,
                    use_llm=True,
                    continuity_review_mode=continuity_review_mode,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
                repaired_segment_ids.append(target_id)
                latest_result_paths = _build_repair_paths_from_result(repair_result)
                aggregate_pending_actions = _merge_pending_actions(
                    aggregate_pending_actions,
                    ["regenerate_scene_images", "regenerate_video"],
                )
        except ValueError as exc:
            if "has no continuity issues to repair" not in str(exc):
                failed_targets.append(
                    {
                        "scope": scope,
                        "target_id": target_id,
                        "error": str(exc),
                    }
                )
            else:
                noop_targets.append({"scope": scope, "target_id": target_id})
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            failed_targets.append(
                {
                    "scope": scope,
                    "target_id": target_id,
                    "error": str(exc),
                }
            )

        _persist_stage_update(
            context,
            task,
            partial_response,
            severity_threshold=severity_threshold,
            max_units_per_batch=max_units_per_batch,
            processed_unit_count=len(processed_targets),
            repaired_unit_count=len(repaired_scene_ids) + len(repaired_segment_ids),
            noop_unit_count=len(noop_targets),
            failed_unit_count=len(failed_targets),
            repaired_scene_ids=repaired_scene_ids,
            repaired_segment_ids=repaired_segment_ids,
            current_target_scope=scope,
            current_target_id=target_id,
        )

    remaining_summary = _count_remaining_repair_batch_targets(
        output_dir=output_dir,
        severity_threshold=severity_threshold,
    )
    repaired_unit_count = len(repaired_scene_ids) + len(repaired_segment_ids)
    repair_summary = _build_repair_batch_summary(
        repaired_scene_ids=repaired_scene_ids,
        repaired_segment_ids=repaired_segment_ids,
        noop_targets=noop_targets,
        failed_targets=failed_targets,
        remaining_summary=remaining_summary,
    )
    response = _build_completed_stage_response(
        {
            **partial_response,
            **latest_result_paths,
            "pipeline_stage": "continuity_repair_batch_completed",
            "repair_execution_mode": "plan_only" if repaired_unit_count else "noop",
            "media_regeneration_required": repaired_unit_count > 0,
            "pending_media_actions": aggregate_pending_actions if repaired_unit_count else [],
            "repair_summary": repair_summary,
            "severity_threshold": severity_threshold,
            "max_units_per_batch": max_units_per_batch,
            "processed_unit_count": len(processed_targets),
            "repaired_unit_count": repaired_unit_count,
            "noop_unit_count": len(noop_targets),
            "failed_unit_count": len(failed_targets),
            "repaired_scene_ids": repaired_scene_ids,
            "repaired_segment_ids": repaired_segment_ids,
            "noop_targets": noop_targets,
            "failed_targets": failed_targets,
            "remaining_repairable_count": remaining_summary["total_count"],
            "remaining_scene_target_count": remaining_summary["scene_count"],
            "remaining_segment_target_count": remaining_summary["segment_count"],
            "has_more_batches": remaining_summary["total_count"] > 0,
        }
    )
    _store_stage_result(context, task, response)
    _sync_stage_result(
        context,
        task=task,
        pipeline_root_task_id=pipeline_root_task_id,
        result=response,
        mode="refresh",
    )
    if repaired_unit_count == 0 and failed_targets and not noop_targets:
        raise TaskExecutionError(_build_repair_batch_failure_message(failed_targets), result=response)
    return response


def _build_story_output_root(context: TaskExecutionContext, task: QueuedTask) -> Path:
    return (
        context.project_root
        / context.config.paths.output_dir
        / "projects"
        / task.project_id
        / "runs"
        / task.task_id
    )


def _start_stage_task(
    context: TaskExecutionContext,
    task: QueuedTask,
    *,
    source_task,
    output_dir: Path,
    task_stage: str,
    pipeline_stage: str,
    pipeline_root_task_id: str,
    continuity_review_mode: str,
) -> dict[str, object]:
    response = _build_stage_response(
        task=task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage=task_stage,
        pipeline_stage=pipeline_stage,
        pipeline_root_task_id=pipeline_root_task_id,
    )
    response["continuity_review_mode"] = continuity_review_mode
    persist_task_progress(context, task, response)
    return response


def _persist_stage_update(
    context: TaskExecutionContext,
    task: QueuedTask,
    response: dict[str, object],
    **updates: object,
) -> None:
    response.update(updates)
    response["artifact_revision"] = utc_now()
    persist_task_progress(context, task, response)


def _build_completed_stage_response(
    response: dict[str, object],
    **updates: object,
) -> dict[str, object]:
    completed_response = {
        **response,
        **updates,
    }
    completed_response["artifact_revision"] = utc_now()
    return completed_response


def _store_stage_result(
    context: TaskExecutionContext,
    task: QueuedTask,
    result: dict[str, object],
) -> None:
    context.project_store.mark_task_result(task.project_id, task.task_id, result)


def _sync_stage_result(
    context: TaskExecutionContext,
    *,
    task: QueuedTask,
    pipeline_root_task_id: str,
    result: dict[str, object],
    mode: Literal["propagate", "refresh"],
) -> None:
    task_ids = {str(task.payload["source_task_id"]), pipeline_root_task_id}
    if mode == "refresh":
        refresh_artifact_revision_for_tasks(
            context,
            task_ids=task_ids,
            artifact_revision=str(result["artifact_revision"]),
            exclude_task_id=task.task_id,
        )
        return
    propagate_shared_result(
        context,
        task_ids=task_ids,
        result=result,
        exclude_task_id=task.task_id,
    )


def _build_stage_response(
    task: QueuedTask,
    source_task,
    output_dir: Path,
    task_stage: str,
    pipeline_stage: str,
    pipeline_root_task_id: str,
) -> dict[str, object]:
    response = {
        "project_id": task.project_id,
        "story_title": resolve_story_title(source_task),
        "output_dir": str(output_dir),
        "story_source_revision": str(source_task.result.get("story_source_revision", "")),
        "pipeline_stage": pipeline_stage,
        "task_stage": task_stage,
        "pipeline_root_task_id": pipeline_root_task_id,
        "source_task_id": str(task.payload["source_task_id"]),
        "artifact_revision": utc_now(),
    }
    if source_task.result and source_task.result.get("novel_package_path"):
        response["novel_package_path"] = str(source_task.result["novel_package_path"])
    if source_task.result and source_task.result.get("novel_audit_path"):
        response["novel_audit_path"] = str(source_task.result["novel_audit_path"])
    if source_task.result and source_task.result.get("scene_plan_path"):
        response["scene_plan_path"] = str(source_task.result["scene_plan_path"])
    segment_id = str(task.payload.get("segment_id", "")).strip()
    if segment_id:
        response["segment_id"] = segment_id
    scene_id = str(task.payload.get("scene_id", "")).strip()
    if scene_id:
        response["scene_id"] = scene_id
    if bool(task.payload.get("master_only", False)):
        response["master_only"] = True
    return response


def _build_stage_reset_fields(*, clear_character_assets: bool) -> dict[str, object]:
    fields: dict[str, object] = {
        "character_images_path": None,
        "segment_plan_path": None,
        "segment_contract_progress_path": None,
        "segment_contract_progress": None,
        "scene_images_path": None,
        "seedream_execution_path": None,
        "scene_seedream_execution_path": None,
        "seedance_manifest_path": None,
        "seedance_execution_path": None,
        "rendered_clips": [],
        "full_story_path": None,
        "seedance_submitted": False,
        "continuity_report_path": None,
    }
    if clear_character_assets:
        fields["character_seedream_execution_path"] = None
    return fields


def _build_segment_contract_output_paths(output_dir: Path) -> dict[str, object]:
    return {
        "story_memory_path": str(output_dir / "story_memory.json"),
        "character_bible_path": str(output_dir / "character_visual_bible.json"),
        "character_images_path": str(output_dir / "character_image_manifest.json"),
        "scene_plan_path": str(output_dir / "scene_plan.json"),
        "segment_plan_path": str(output_dir / "segment_plan.json"),
        "segment_contract_progress_path": str(output_dir / "segment_contract_progress.json"),
        "scene_images_path": str(output_dir / "scene_image_manifest.json"),
        "seedance_manifest_path": str(output_dir / "seedance_manifest.json"),
    }


def _build_segment_contract_progress_result(
    output_dir: Path,
    progress,
) -> dict[str, object]:
    progress_payload = progress
    if progress_payload is None:
        progress_payload = load_segment_contract_progress(output_dir)
    if progress_payload is None:
        return {
            "segment_contract_progress_path": str(output_dir / "segment_contract_progress.json"),
            "segment_contract_progress": None,
        }
    return {
        "segment_contract_progress_path": str(output_dir / "segment_contract_progress.json"),
        "segment_contract_progress": to_jsonable(progress_payload),
    }


def _build_repair_plan_only_response(
    *,
    partial_response: dict[str, object],
    repair_result,
    pending_media_actions: list[str],
    affected_segment_ids: list[str],
) -> dict[str, object]:
    response = {
        **partial_response,
        "story_title": repair_result.project_package.title,
        "character_bible_path": str(repair_result.character_bible_path),
        "character_images_path": str(repair_result.character_images_path),
        "scene_plan_path": str(repair_result.scene_plan_path),
        "segment_plan_path": str(repair_result.segment_plan_path),
        "scene_images_path": str(repair_result.scene_images_path),
        "seedance_manifest_path": str(repair_result.manifest_path),
        "continuity_report_path": str(repair_result.continuity_report_path),
        "repair_report_path": str(repair_result.repair_report_path),
        "repair_summary": repair_result.repair_summary,
        "pipeline_stage": "continuity_repair_plan_completed",
        "repair_execution_mode": "plan_only",
        "media_regeneration_required": True,
        "pending_media_actions": pending_media_actions,
        "affected_segment_ids": affected_segment_ids,
    }
    if getattr(repair_result, "repair_action", ""):
        response["repair_action"] = repair_result.repair_action
    if getattr(repair_result, "selection_mode", ""):
        response["selection_mode"] = repair_result.selection_mode
    if getattr(repair_result, "segment_id", ""):
        response["segment_id"] = repair_result.segment_id
    if getattr(repair_result, "scene_id", ""):
        response["scene_id"] = repair_result.scene_id
    return response


def _build_repair_noop_response(
    *,
    partial_response: dict[str, object],
    source_task: QueuedTask,
    repair_summary: str,
    segment_id: str = "",
    scene_id: str = "",
) -> dict[str, object]:
    result = source_task.result or {}
    response = {
        **partial_response,
        "story_title": resolve_story_title(source_task),
        "character_bible_path": result.get("character_bible_path"),
        "character_images_path": result.get("character_images_path"),
        "scene_plan_path": result.get("scene_plan_path"),
        "segment_plan_path": result.get("segment_plan_path"),
        "scene_images_path": result.get("scene_images_path"),
        "seedance_manifest_path": result.get("seedance_manifest_path"),
        "continuity_report_path": result.get("continuity_report_path"),
        "repair_summary": repair_summary,
        "pipeline_stage": "continuity_repair_plan_completed",
        "repair_execution_mode": "noop",
        "media_regeneration_required": False,
        "pending_media_actions": [],
        "affected_segment_ids": [segment_id] if segment_id else [],
    }
    if segment_id:
        response["segment_id"] = segment_id
    if scene_id:
        response["scene_id"] = scene_id
    return response


def _build_scene_repair_pending_actions(repair_result) -> list[str]:
    actions: list[str] = []
    repair_action = str(getattr(repair_result, "repair_action", "") or "").strip()
    if repair_action:
        actions.append(repair_action)
    for action in ("regenerate_scene_images", "regenerate_video"):
        if action not in actions:
            actions.append(action)
    return actions


def _normalize_repair_batch_limit(raw_value: object) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = REPAIR_BATCH_DEFAULT_LIMIT
    return max(1, min(REPAIR_BATCH_MAX_LIMIT, value))


def _normalize_repair_batch_severity(raw_value: object) -> str:
    normalized = str(raw_value or "medium").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return "medium"


def _build_repair_output_paths(output_dir: Path) -> dict[str, object]:
    return {
        "character_bible_path": str(output_dir / "character_visual_bible.json"),
        "character_images_path": str(output_dir / "character_image_manifest.json"),
        "scene_plan_path": str(output_dir / "scene_plan.json"),
        "segment_plan_path": str(output_dir / "segment_plan.json"),
        "scene_images_path": str(output_dir / "scene_image_manifest.json"),
        "seedance_manifest_path": str(output_dir / "seedance_manifest.json"),
        "continuity_report_path": str(output_dir / "continuity_report.json"),
    }


def _build_repair_paths_from_result(repair_result) -> dict[str, object]:
    return {
        "character_bible_path": str(repair_result.character_bible_path),
        "character_images_path": str(repair_result.character_images_path),
        "scene_plan_path": str(repair_result.scene_plan_path),
        "segment_plan_path": str(repair_result.segment_plan_path),
        "scene_images_path": str(repair_result.scene_images_path),
        "seedance_manifest_path": str(repair_result.manifest_path),
        "continuity_report_path": str(repair_result.continuity_report_path),
    }


def _merge_pending_actions(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    for action in incoming:
        normalized = str(action or "").strip()
        if normalized and normalized not in merged:
            merged.append(normalized)
    return merged


def _select_next_repair_batch_target(
    *,
    output_dir: Path,
    severity_threshold: str,
    processed_targets: set[tuple[str, str]],
) -> dict[str, object] | None:
    report_payload = _load_continuity_report_payload(output_dir)
    candidates = _collect_repair_batch_candidates(
        report_payload=report_payload,
        severity_threshold=severity_threshold,
    )
    for candidate in candidates:
        key = (str(candidate["scope"]), str(candidate["target_id"]))
        if key in processed_targets:
            continue
        return candidate
    return None


def _count_remaining_repair_batch_targets(
    *,
    output_dir: Path,
    severity_threshold: str,
) -> dict[str, int]:
    report_payload = _load_continuity_report_payload(output_dir)
    candidates = _collect_repair_batch_candidates(
        report_payload=report_payload,
        severity_threshold=severity_threshold,
    )
    scene_count = sum(1 for item in candidates if item["scope"] == "scene")
    segment_count = sum(1 for item in candidates if item["scope"] == "segment")
    return {
        "total_count": len(candidates),
        "scene_count": scene_count,
        "segment_count": segment_count,
    }


def _load_continuity_report_payload(output_dir: Path) -> dict[str, object]:
    report_path = output_dir / "continuity_report.json"
    if not report_path.exists():
        raise FileNotFoundError(
            f"Continuity report not found at {report_path}. Generate segment contracts first."
        )
    payload = read_json(report_path)
    if not isinstance(payload, dict):
        raise ValueError("continuity_report.json is invalid.")
    return payload


def _collect_repair_batch_candidates(
    *,
    report_payload: dict[str, object],
    severity_threshold: str,
) -> list[dict[str, object]]:
    allowed_severities = _allowed_repair_batch_severities(severity_threshold)
    scene_candidates = _group_repair_batch_candidates(
        issues=report_payload.get("scene_issues", []),
        scope="scene",
        id_field="scene_id",
        allowed_severities=allowed_severities,
    )
    segment_candidates = _group_repair_batch_candidates(
        issues=report_payload.get("segment_issues", []),
        scope="segment",
        id_field="segment_id",
        allowed_severities=allowed_severities,
    )
    return sorted(
        [*scene_candidates, *segment_candidates],
        key=lambda item: (
            int(item["severity_rank"]),
            int(item["scope_rank"]),
            -int(item["issue_count"]),
            str(item["target_id"]),
        ),
    )


def _allowed_repair_batch_severities(severity_threshold: str) -> set[str]:
    threshold_rank = REPAIR_BATCH_SEVERITY_ORDER.get(severity_threshold, REPAIR_BATCH_SEVERITY_ORDER["medium"])
    return {
        severity
        for severity, rank in REPAIR_BATCH_SEVERITY_ORDER.items()
        if rank <= threshold_rank
    }


def _group_repair_batch_candidates(
    *,
    issues: object,
    scope: str,
    id_field: str,
    allowed_severities: set[str],
) -> list[dict[str, object]]:
    if not isinstance(issues, list):
        return []

    grouped: dict[str, list[dict[str, object]]] = {}
    for raw_issue in issues:
        if not isinstance(raw_issue, dict):
            continue
        target_id = str(raw_issue.get(id_field, "") or "").strip()
        severity = str(raw_issue.get("severity", "") or "").strip().lower()
        if not target_id or severity not in allowed_severities:
            continue
        grouped.setdefault(target_id, []).append(raw_issue)

    candidates: list[dict[str, object]] = []
    for target_id, target_issues in grouped.items():
        severity_values = [
            REPAIR_BATCH_SEVERITY_ORDER.get(str(item.get("severity", "")).strip().lower(), 99)
            for item in target_issues
        ]
        if not severity_values:
            continue
        candidates.append(
            {
                "scope": scope,
                "target_id": target_id,
                "severity_rank": min(severity_values),
                "scope_rank": REPAIR_BATCH_SCOPE_ORDER.get(scope, 99),
                "issue_count": len(target_issues),
            }
        )
    return candidates


def _build_repair_batch_summary(
    *,
    repaired_scene_ids: list[str],
    repaired_segment_ids: list[str],
    noop_targets: list[dict[str, str]],
    failed_targets: list[dict[str, str]],
    remaining_summary: dict[str, int],
) -> str:
    parts: list[str] = []
    if repaired_scene_ids or repaired_segment_ids:
        parts.append(
            "本批已更新 "
            f"{len(repaired_scene_ids) + len(repaired_segment_ids)} 个合同目标"
            f"（场景 {len(repaired_scene_ids)} / 片段 {len(repaired_segment_ids)}）。"
        )
    if noop_targets:
        parts.append(f"{len(noop_targets)} 个目标当前没有可修复问题。")
    if failed_targets:
        parts.append(f"{len(failed_targets)} 个目标修复失败。")
    if remaining_summary["total_count"] > 0:
        parts.append(
            f"当前仍有 {remaining_summary['total_count']} 个风险目标待继续修复"
            f"（场景 {remaining_summary['scene_count']} / 片段 {remaining_summary['segment_count']}）。"
        )
    if not parts:
        return "当前批次没有发现需要更新的风险合同。"
    return " ".join(parts)


def _build_repair_batch_failure_message(failed_targets: list[dict[str, str]]) -> str:
    first_failure = failed_targets[0] if failed_targets else {}
    scope = str(first_failure.get("scope", "") or "").strip() or "target"
    target_id = str(first_failure.get("target_id", "") or "").strip() or "unknown"
    error = str(first_failure.get("error", "") or "").strip() or "unknown error"
    return f"批量修复失败：{scope} {target_id} 修复异常：{error}"
