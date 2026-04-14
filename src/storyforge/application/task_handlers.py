from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from storyforge.application.task_support import (
    build_requested_image_error,
    build_requested_media_error,
    build_requested_video_error,
    load_novel_package,
    load_story_source,
    persist_task_progress,
    propagate_shared_result,
    resolve_output_dir,
    resolve_pipeline_root_task_id,
    resolve_source_task,
    resolve_story_title,
)
from storyforge.application.tasks import QueuedTask, TaskExecutionError, utc_now
from storyforge.domains.novel.contracts import StoryBrief
from storyforge.pipelines.story_pipeline import (
    run_story_analysis_pipeline,
    run_story_generation_pipeline,
)
from storyforge.pipelines.video_pipeline import (
    run_character_image_pipeline,
    run_image_pipeline,
    run_scene_image_pipeline,
    run_video_pipeline,
    run_video_render_pipeline,
)

if TYPE_CHECKING:
    from storyforge.application.task_runtime import TaskExecutionContext


def run_story_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    brief = StoryBrief.from_dict(task.payload["brief"])
    use_llm = bool(task.payload.get("use_llm", True))
    output_root = _build_story_output_root(context, task)
    story_result = run_story_generation_pipeline(
        brief=brief,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
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
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    return response


def run_story_analysis_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    story_source = load_story_source(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = {
        "project_id": task.project_id,
        "story_title": story_source.title,
        "output_dir": str(output_dir),
        "story_source_path": str(source_task.result["story_source_path"]),
        "story_source_revision": str(source_task.result.get("story_source_revision", utc_now())),
        "pipeline_stage": "story_analysis_started",
        "task_stage": "story_analysis",
        "pipeline_root_task_id": pipeline_root_task_id,
        "source_task_id": str(task.payload["source_task_id"]),
        "artifact_revision": utc_now(),
    }
    persist_task_progress(context, task, partial_response)

    analysis_result = run_story_analysis_pipeline(
        story_source=story_source,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
        output_root=output_dir,
    )
    response = {
        **partial_response,
        "story_title": analysis_result.novel_package.outline.title,
        "novel_package_path": str(analysis_result.novel_package_path),
        "novel_audit_path": str(analysis_result.novel_audit_path),
        "character_bible_path": str(analysis_result.character_bible_path),
        "character_images_path": str(analysis_result.character_images_path),
        "segment_plan_path": str(analysis_result.segment_plan_path),
        "scene_images_path": str(analysis_result.scene_images_path),
        "seedance_manifest_path": str(analysis_result.seedance_manifest_path),
        "pipeline_stage": "story_analysis_completed",
        "artifact_revision": utc_now(),
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    propagate_shared_result(
        context,
        task_ids={str(task.payload["source_task_id"]), pipeline_root_task_id},
        result=response,
        exclude_task_id=task.task_id,
    )
    return response


def run_images_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    novel_package = load_novel_package(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = _build_stage_response(
        task=task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="images",
        pipeline_stage="image_generation_started",
        pipeline_root_task_id=pipeline_root_task_id,
    )
    persist_task_progress(context, task, partial_response)

    image_result = run_image_pipeline(
        novel_package=novel_package,
        config=context.config,
        project_root=context.project_root,
        output_root=output_dir,
        use_llm=use_llm,
        submit_images=True,
    )
    response = {
        **partial_response,
        "story_title": image_result.project_package.title,
        "output_dir": str(image_result.output_dir),
        "character_bible_path": str(image_result.character_bible_path),
        "character_images_path": str(image_result.character_images_path),
        "segment_plan_path": str(image_result.segment_plan_path),
        "scene_images_path": str(image_result.scene_images_path),
        "seedream_execution_path": str(image_result.seedream_execution_path),
        "seedance_manifest_path": str(image_result.manifest_path),
        "pipeline_stage": "images_completed",
        "artifact_revision": utc_now(),
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    propagate_shared_result(
        context,
        task_ids={str(task.payload["source_task_id"]), pipeline_root_task_id},
        result=response,
        exclude_task_id=task.task_id,
    )
    image_error = build_requested_image_error(image_result.seedream_execution)
    if image_error:
        raise TaskExecutionError(image_error, result=response)
    return response


def run_characters_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    novel_package = load_novel_package(source_task)
    use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", True)))
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = _build_stage_response(
        task=task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="characters",
        pipeline_stage="character_generation_started",
        pipeline_root_task_id=pipeline_root_task_id,
    )
    persist_task_progress(context, task, partial_response)

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
        "segment_plan_path": str(character_result.segment_plan_path),
        "scene_images_path": str(character_result.scene_images_path),
        "seedance_manifest_path": str(character_result.manifest_path),
        "character_seedream_execution_path": str(character_result.character_seedream_execution_path),
        "seedream_execution_path": str(character_result.seedream_execution_path),
        "pipeline_stage": "characters_completed",
        "artifact_revision": utc_now(),
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    propagate_shared_result(
        context,
        task_ids={str(task.payload["source_task_id"]), pipeline_root_task_id},
        result=response,
        exclude_task_id=task.task_id,
    )
    image_error = build_requested_image_error(character_result.seedream_execution)
    if image_error:
        raise TaskExecutionError(image_error, result=response)
    return response


def run_scenes_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = _build_stage_response(
        task=task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="scenes",
        pipeline_stage="scene_generation_started",
        pipeline_root_task_id=pipeline_root_task_id,
    )
    persist_task_progress(context, task, partial_response)

    scene_result = run_scene_image_pipeline(
        config=context.config,
        project_root=context.project_root,
        output_root=output_dir,
        submit_scenes=True,
    )
    response = {
        **partial_response,
        "story_title": scene_result.project_package.title,
        "output_dir": str(scene_result.output_dir),
        "character_bible_path": str(scene_result.character_bible_path),
        "character_images_path": str(scene_result.character_images_path),
        "segment_plan_path": str(scene_result.segment_plan_path),
        "scene_images_path": str(scene_result.scene_images_path),
        "seedance_manifest_path": str(scene_result.manifest_path),
        "character_seedream_execution_path": str(scene_result.character_seedream_execution_path),
        "scene_seedream_execution_path": str(scene_result.scene_seedream_execution_path),
        "seedream_execution_path": str(scene_result.seedream_execution_path),
        "pipeline_stage": "scenes_completed",
        "artifact_revision": utc_now(),
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    propagate_shared_result(
        context,
        task_ids={str(task.payload["source_task_id"]), pipeline_root_task_id},
        result=response,
        exclude_task_id=task.task_id,
    )
    scene_error = build_requested_image_error(scene_result.seedream_execution)
    if scene_error:
        raise TaskExecutionError(scene_error, result=response)
    return response


def run_videos_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    source_task = resolve_source_task(context, task)
    output_dir = resolve_output_dir(source_task)
    pipeline_root_task_id = resolve_pipeline_root_task_id(source_task)
    partial_response = _build_stage_response(
        task=task,
        source_task=source_task,
        output_dir=output_dir,
        task_stage="videos",
        pipeline_stage="video_render_started",
        pipeline_root_task_id=pipeline_root_task_id,
    )
    persist_task_progress(context, task, partial_response)

    video_result = run_video_render_pipeline(
        config=context.config,
        project_root=context.project_root,
        output_root=output_dir,
        submit_seedance=True,
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
        "artifact_revision": utc_now(),
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    propagate_shared_result(
        context,
        task_ids={str(task.payload["source_task_id"]), pipeline_root_task_id},
        result=response,
        exclude_task_id=task.task_id,
    )
    video_error = build_requested_video_error(video_result.seedance_execution)
    if video_error:
        raise TaskExecutionError(video_error, result=response)
    return response


def run_full_pipeline_task(context: TaskExecutionContext, task: QueuedTask) -> dict[str, object]:
    brief = StoryBrief.from_dict(task.payload["brief"])
    use_llm = bool(task.payload.get("use_llm", True))
    submit_seedance = bool(task.payload.get("submit_seedance", False))
    output_root = _build_story_output_root(context, task)

    story_result = run_story_generation_pipeline(
        brief=brief,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
        output_root=output_root,
    )
    partial_response: dict[str, object] = {
        "project_id": task.project_id,
        "story_title": story_result.story_source.title,
        "output_dir": str(story_result.output_dir),
        "story_source_path": str(story_result.story_source_path),
        "story_source_revision": utc_now(),
        "pipeline_stage": "story_source_completed",
        "task_stage": "full",
        "pipeline_root_task_id": task.task_id,
        "source_task_id": task.task_id,
        "artifact_revision": utc_now(),
    }
    persist_task_progress(context, task, partial_response)

    analysis_result = run_story_analysis_pipeline(
        story_source=story_result.story_source,
        config=context.config,
        project_root=context.project_root,
        use_llm=use_llm,
        output_root=story_result.output_dir,
    )
    partial_response.update(
        {
            "story_title": analysis_result.novel_package.outline.title,
            "novel_package_path": str(analysis_result.novel_package_path),
            "novel_audit_path": str(analysis_result.novel_audit_path),
            "character_bible_path": str(analysis_result.character_bible_path),
            "character_images_path": str(analysis_result.character_images_path),
            "segment_plan_path": str(analysis_result.segment_plan_path),
            "scene_images_path": str(analysis_result.scene_images_path),
            "seedance_manifest_path": str(analysis_result.seedance_manifest_path),
            "pipeline_stage": "story_analysis_completed",
            "artifact_revision": utc_now(),
        }
    )
    persist_task_progress(context, task, partial_response)

    video_result = run_video_pipeline(
        novel_package=analysis_result.novel_package,
        config=context.config,
        project_root=context.project_root,
        output_root=story_result.output_dir,
        use_llm=use_llm,
        submit_seedance=submit_seedance,
    )

    response: dict[str, object] = {
        "project_id": task.project_id,
        "story_title": analysis_result.novel_package.outline.title,
        "output_dir": str(story_result.output_dir),
        "story_source_path": str(story_result.story_source_path),
        "story_source_revision": partial_response["story_source_revision"],
        "novel_package_path": str(analysis_result.novel_package_path),
        "novel_audit_path": str(analysis_result.novel_audit_path),
        "character_bible_path": str(analysis_result.character_bible_path),
        "character_images_path": str(analysis_result.character_images_path),
        "scene_images_path": str(analysis_result.scene_images_path),
        "seedream_execution_path": str(video_result.seedream_execution_path),
        "seedance_manifest_path": str(video_result.manifest_path),
        "seedance_execution_path": str(video_result.seedance_execution_path),
        "segment_plan_path": str(video_result.segment_plan_path),
        "rendered_clips": [str(path) for path in video_result.rendered_clip_paths],
        "full_story_path": (
            str(video_result.full_story_path) if video_result.full_story_path else None
        ),
        "pipeline_stage": "video_completed",
        "task_stage": "full",
        "pipeline_root_task_id": task.task_id,
        "source_task_id": task.task_id,
        "artifact_revision": utc_now(),
        "seedance_submitted": video_result.seedance_execution.submitted,
    }
    context.project_store.mark_task_result(task.project_id, task.task_id, response)
    media_error = build_requested_media_error(
        requested=submit_seedance,
        seedream_execution=video_result.seedream_execution,
        seedance_execution=video_result.seedance_execution,
    )
    if media_error:
        raise TaskExecutionError(media_error, result=response)
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


def _build_stage_response(
    task: QueuedTask,
    source_task,
    output_dir: Path,
    task_stage: str,
    pipeline_stage: str,
    pipeline_root_task_id: str,
) -> dict[str, object]:
    return {
        "project_id": task.project_id,
        "story_title": resolve_story_title(source_task),
        "output_dir": str(output_dir),
        "novel_package_path": str(source_task.result["novel_package_path"]),
        "novel_audit_path": (
            str(source_task.result["novel_audit_path"])
            if source_task.result and source_task.result.get("novel_audit_path")
            else None
        ),
        "story_source_revision": str(source_task.result.get("story_source_revision", "")),
        "pipeline_stage": pipeline_stage,
        "task_stage": task_stage,
        "pipeline_root_task_id": pipeline_root_task_id,
        "source_task_id": str(task.payload["source_task_id"]),
        "artifact_revision": utc_now(),
    }
