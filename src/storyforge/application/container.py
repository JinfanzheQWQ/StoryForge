from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from storyforge.agents.orchestrator import StoryForgeOrchestrator
from storyforge.application.projects import ProjectStore
from storyforge.application.tasks import (
    AsyncTaskQueue,
    QueuedTask,
    TaskExecutionError,
    TaskStore,
    utc_now,
)
from storyforge.core.config import AppConfig
from storyforge.core.io import read_json
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief
from storyforge.integrations.seedance import SeedanceClient
from storyforge.pipelines.story_pipeline import run_story_pipeline
from storyforge.pipelines.video_pipeline import (
    run_character_image_pipeline,
    run_image_pipeline,
    run_scene_image_pipeline,
    run_video_pipeline,
    run_video_render_pipeline,
)


@dataclass(slots=True)
class AppContainer:
    project_root: Path
    config: AppConfig
    orchestrator: StoryForgeOrchestrator
    seedance_client: SeedanceClient
    project_store: ProjectStore
    task_queue: AsyncTaskQueue


def build_container(project_root: Path, config: AppConfig) -> AppContainer:
    orchestrator = StoryForgeOrchestrator(project_root=project_root, config=config)
    seedance_client = SeedanceClient(config.seedance)
    state_dir = project_root / config.paths.workspace_dir / "state"
    if config.database.enabled:
        from storyforge.application.mysql_store import MySQLBackend, MySQLProjectStore, MySQLTaskStore

        database_backend = MySQLBackend(config.database)
        project_store = MySQLProjectStore(database_backend)
        task_store = MySQLTaskStore(database_backend)
    else:
        project_store = ProjectStore(state_dir / "projects.json")
        task_store = TaskStore(state_dir / "tasks.json")

    async def handle_task(task: QueuedTask) -> dict[str, object]:
        if task.task_type == "project.build":
            return await asyncio.to_thread(_run_full_pipeline_task, task)
        if task.task_type == "project.story":
            return await asyncio.to_thread(_run_story_task, task)
        if task.task_type == "project.characters":
            return await asyncio.to_thread(_run_characters_task, task)
        if task.task_type == "project.scenes":
            return await asyncio.to_thread(_run_scenes_task, task)
        if task.task_type == "project.images":
            return await asyncio.to_thread(_run_images_task, task)
        if task.task_type == "project.videos":
            return await asyncio.to_thread(_run_videos_task, task)
        raise ValueError(f"Unsupported task_type={task.task_type}")

    def _run_story_task(task: QueuedTask) -> dict[str, object]:
        brief = StoryBrief.from_dict(task.payload["brief"])
        use_llm = bool(task.payload.get("use_llm", False))
        output_root = (
            project_root
            / config.paths.output_dir
            / "projects"
            / task.project_id
            / "runs"
            / task.task_id
        )
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=project_root,
            use_llm=use_llm,
            output_root=output_root,
        )
        response = {
            "project_id": task.project_id,
            "story_title": story_result.novel_package.outline.title,
            "output_dir": str(story_result.output_dir),
            "novel_package_path": str(story_result.novel_package_path),
            "pipeline_stage": "story_completed",
            "task_stage": "story",
            "pipeline_root_task_id": task.task_id,
            "source_task_id": task.task_id,
            "artifact_revision": utc_now(),
        }
        project_store.mark_task_result(task.project_id, task.task_id, response)
        return response

    def _run_images_task(task: QueuedTask) -> dict[str, object]:
        source_task = _resolve_source_task(task)
        output_dir = _resolve_output_dir(source_task)
        novel_package = _load_novel_package(source_task)
        use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", False)))
        pipeline_root_task_id = _pipeline_root_task_id(source_task)
        partial_response = {
            "project_id": task.project_id,
            "story_title": _resolve_story_title(source_task),
            "output_dir": str(output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "pipeline_stage": "image_generation_started",
            "task_stage": "images",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        task_store.update_result(task.task_id, partial_response)
        project_store.mark_task_result(task.project_id, task.task_id, partial_response)

        image_result = run_image_pipeline(
            novel_package=novel_package,
            config=config,
            project_root=project_root,
            output_root=output_dir,
            use_llm=use_llm,
            submit_images=True,
        )
        response = {
            "project_id": task.project_id,
            "story_title": image_result.project_package.title,
            "output_dir": str(image_result.output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "character_bible_path": str(image_result.character_bible_path),
            "character_images_path": str(image_result.character_images_path),
            "segment_plan_path": str(image_result.segment_plan_path),
            "scene_images_path": str(image_result.scene_images_path),
            "seedream_execution_path": str(image_result.seedream_execution_path),
            "seedance_manifest_path": str(image_result.manifest_path),
            "pipeline_stage": "images_completed",
            "task_stage": "images",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        project_store.mark_task_result(task.project_id, task.task_id, response)
        _propagate_shared_result(
            task_ids={task.payload["source_task_id"], pipeline_root_task_id},
            result=response,
            exclude_task_id=task.task_id,
        )
        image_error = _build_requested_image_error(image_result.seedream_execution)
        if image_error:
            raise TaskExecutionError(image_error, result=response)
        return response

    def _run_characters_task(task: QueuedTask) -> dict[str, object]:
        source_task = _resolve_source_task(task)
        output_dir = _resolve_output_dir(source_task)
        novel_package = _load_novel_package(source_task)
        use_llm = bool(task.payload.get("use_llm", source_task.payload.get("use_llm", False)))
        pipeline_root_task_id = _pipeline_root_task_id(source_task)
        partial_response = {
            "project_id": task.project_id,
            "story_title": _resolve_story_title(source_task),
            "output_dir": str(output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "pipeline_stage": "character_generation_started",
            "task_stage": "characters",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        task_store.update_result(task.task_id, partial_response)
        project_store.mark_task_result(task.project_id, task.task_id, partial_response)

        character_result = run_character_image_pipeline(
            novel_package=novel_package,
            config=config,
            project_root=project_root,
            output_root=output_dir,
            use_llm=use_llm,
            submit_characters=True,
        )
        response = {
            "project_id": task.project_id,
            "story_title": character_result.project_package.title,
            "output_dir": str(character_result.output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "character_bible_path": str(character_result.character_bible_path),
            "character_images_path": str(character_result.character_images_path),
            "segment_plan_path": str(character_result.segment_plan_path),
            "scene_images_path": str(character_result.scene_images_path),
            "seedance_manifest_path": str(character_result.manifest_path),
            "character_seedream_execution_path": str(character_result.character_seedream_execution_path),
            "seedream_execution_path": str(character_result.seedream_execution_path),
            "pipeline_stage": "characters_completed",
            "task_stage": "characters",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        project_store.mark_task_result(task.project_id, task.task_id, response)
        _propagate_shared_result(
            task_ids={task.payload["source_task_id"], pipeline_root_task_id},
            result=response,
            exclude_task_id=task.task_id,
        )
        image_error = _build_requested_image_error(character_result.seedream_execution)
        if image_error:
            raise TaskExecutionError(image_error, result=response)
        return response

    def _run_scenes_task(task: QueuedTask) -> dict[str, object]:
        source_task = _resolve_source_task(task)
        output_dir = _resolve_output_dir(source_task)
        pipeline_root_task_id = _pipeline_root_task_id(source_task)
        partial_response = {
            "project_id": task.project_id,
            "story_title": _resolve_story_title(source_task),
            "output_dir": str(output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "pipeline_stage": "scene_generation_started",
            "task_stage": "scenes",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        task_store.update_result(task.task_id, partial_response)
        project_store.mark_task_result(task.project_id, task.task_id, partial_response)

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=project_root,
            output_root=output_dir,
            submit_scenes=True,
        )
        response = {
            "project_id": task.project_id,
            "story_title": scene_result.project_package.title,
            "output_dir": str(scene_result.output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "character_bible_path": str(scene_result.character_bible_path),
            "character_images_path": str(scene_result.character_images_path),
            "segment_plan_path": str(scene_result.segment_plan_path),
            "scene_images_path": str(scene_result.scene_images_path),
            "seedance_manifest_path": str(scene_result.manifest_path),
            "character_seedream_execution_path": str(scene_result.character_seedream_execution_path),
            "scene_seedream_execution_path": str(scene_result.scene_seedream_execution_path),
            "seedream_execution_path": str(scene_result.seedream_execution_path),
            "pipeline_stage": "scenes_completed",
            "task_stage": "scenes",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        project_store.mark_task_result(task.project_id, task.task_id, response)
        _propagate_shared_result(
            task_ids={task.payload["source_task_id"], pipeline_root_task_id},
            result=response,
            exclude_task_id=task.task_id,
        )
        scene_error = _build_requested_image_error(scene_result.seedream_execution)
        if scene_error:
            raise TaskExecutionError(scene_error, result=response)
        return response

    def _run_videos_task(task: QueuedTask) -> dict[str, object]:
        source_task = _resolve_source_task(task)
        output_dir = _resolve_output_dir(source_task)
        pipeline_root_task_id = _pipeline_root_task_id(source_task)
        partial_response = {
            "project_id": task.project_id,
            "story_title": _resolve_story_title(source_task),
            "output_dir": str(output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "pipeline_stage": "video_render_started",
            "task_stage": "videos",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "artifact_revision": utc_now(),
        }
        task_store.update_result(task.task_id, partial_response)
        project_store.mark_task_result(task.project_id, task.task_id, partial_response)

        video_result = run_video_render_pipeline(
            config=config,
            project_root=project_root,
            output_root=output_dir,
            submit_seedance=True,
        )
        response = {
            "project_id": task.project_id,
            "story_title": _resolve_story_title(source_task),
            "output_dir": str(video_result.output_dir),
            "novel_package_path": str(source_task.result["novel_package_path"]),
            "seedance_manifest_path": str(video_result.manifest_path),
            "seedance_execution_path": str(video_result.seedance_execution_path),
            "rendered_clips": [str(path) for path in video_result.rendered_clip_paths],
            "full_story_path": (
                str(video_result.full_story_path)
                if video_result.full_story_path
                else None
            ),
            "pipeline_stage": "video_completed",
            "task_stage": "videos",
            "pipeline_root_task_id": pipeline_root_task_id,
            "source_task_id": str(task.payload["source_task_id"]),
            "seedance_submitted": video_result.seedance_execution.submitted,
            "artifact_revision": utc_now(),
        }
        project_store.mark_task_result(task.project_id, task.task_id, response)
        _propagate_shared_result(
            task_ids={task.payload["source_task_id"], pipeline_root_task_id},
            result=response,
            exclude_task_id=task.task_id,
        )
        video_error = _build_requested_video_error(video_result.seedance_execution)
        if video_error:
            raise TaskExecutionError(video_error, result=response)
        return response

    def _run_full_pipeline_task(task: QueuedTask) -> dict[str, object]:
        brief = StoryBrief.from_dict(task.payload["brief"])
        use_llm = bool(task.payload.get("use_llm", False))
        submit_seedance = bool(task.payload.get("submit_seedance", False))
        output_root = (
            project_root
            / config.paths.output_dir
            / "projects"
            / task.project_id
            / "runs"
            / task.task_id
        )

        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=project_root,
            use_llm=use_llm,
            output_root=output_root,
        )
        partial_response: dict[str, object] = {
            "project_id": task.project_id,
            "story_title": story_result.novel_package.outline.title,
            "output_dir": str(story_result.output_dir),
            "novel_package_path": str(story_result.novel_package_path),
            "pipeline_stage": "story_completed",
            "task_stage": "full",
            "pipeline_root_task_id": task.task_id,
            "source_task_id": task.task_id,
            "artifact_revision": utc_now(),
        }
        task_store.update_result(task.task_id, partial_response)
        project_store.mark_task_result(task.project_id, task.task_id, partial_response)

        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=project_root,
            output_root=story_result.output_dir,
            use_llm=use_llm,
            submit_seedance=submit_seedance,
        )

        response: dict[str, object] = {
            "project_id": task.project_id,
            "story_title": story_result.novel_package.outline.title,
            "output_dir": str(story_result.output_dir),
            "novel_package_path": str(story_result.novel_package_path),
            "seedream_execution_path": str(video_result.seedream_execution_path),
            "seedance_manifest_path": str(video_result.manifest_path),
            "seedance_execution_path": str(video_result.seedance_execution_path),
            "segment_plan_path": str(video_result.segment_plan_path),
            "rendered_clips": [str(path) for path in video_result.rendered_clip_paths],
            "full_story_path": (
                str(video_result.full_story_path)
                if video_result.full_story_path
                else None
            ),
            "pipeline_stage": "video_completed",
            "task_stage": "full",
            "pipeline_root_task_id": task.task_id,
            "source_task_id": task.task_id,
            "artifact_revision": utc_now(),
        }
        response["seedance_submitted"] = video_result.seedance_execution.submitted
        project_store.mark_task_result(task.project_id, task.task_id, response)
        media_error = _build_requested_media_error(
            requested=submit_seedance,
            seedream_execution=video_result.seedream_execution,
            seedance_execution=video_result.seedance_execution,
        )
        if media_error:
            raise TaskExecutionError(media_error, result=response)
        return response

    def _resolve_source_task(task: QueuedTask):
        source_task_id = str(task.payload["source_task_id"])
        source_task = task_store.get(source_task_id)
        if source_task is None or source_task.project_id != task.project_id:
            raise ValueError(f"Source task {source_task_id} not found for project {task.project_id}")
        if source_task.status != "completed":
            raise ValueError(f"Source task {source_task_id} is not completed yet")
        return source_task

    def _resolve_output_dir(source_task) -> Path:
        raw_output_dir = source_task.result.get("output_dir") if source_task.result else None
        if not raw_output_dir:
            raise ValueError(f"Source task {source_task.task_id} has no output_dir")
        return Path(str(raw_output_dir))

    def _load_novel_package(source_task) -> NovelPackage:
        raw_package_path = source_task.result.get("novel_package_path") if source_task.result else None
        if not raw_package_path:
            raise ValueError(f"Source task {source_task.task_id} has no novel_package_path")
        package_path = Path(str(raw_package_path))
        if not package_path.exists():
            raise FileNotFoundError(f"Novel package not found at {package_path}")
        return NovelPackage.from_dict(read_json(package_path))

    def _resolve_story_title(source_task) -> str:
        if source_task.result and source_task.result.get("story_title"):
            return str(source_task.result["story_title"])
        if source_task.payload and source_task.payload.get("brief"):
            return str(source_task.payload["brief"].get("title_hint", source_task.task_id))
        return source_task.task_id

    def _pipeline_root_task_id(source_task) -> str:
        if source_task.result and source_task.result.get("pipeline_root_task_id"):
            return str(source_task.result["pipeline_root_task_id"])
        if source_task.payload and source_task.payload.get("pipeline_root_task_id"):
            return str(source_task.payload["pipeline_root_task_id"])
        return source_task.task_id

    def _propagate_shared_result(
        task_ids: set[str],
        result: dict[str, object],
        exclude_task_id: str | None = None,
    ) -> None:
        shared_result = {
            key: value
            for key, value in result.items()
            if key not in {"task_stage", "source_task_id"}
        }
        for task_id in task_ids:
            if not task_id or task_id == exclude_task_id:
                continue
            if task_store.get(task_id) is None:
                continue
            task_store.update_result(task_id, shared_result)

    task_queue = AsyncTaskQueue(
        concurrency=config.queue.concurrency,
        handler=handle_task,
        store=task_store,
    )
    return AppContainer(
        project_root=project_root,
        config=config,
        orchestrator=orchestrator,
        seedance_client=seedance_client,
        project_store=project_store,
        task_queue=task_queue,
    )


def _build_requested_media_error(
    requested: bool,
    seedream_execution: object | None,
    seedance_execution: object,
) -> str:
    if not requested:
        return ""

    errors: list[str] = []
    if seedream_execution is None:
        errors.append("Seedream did not return an execution report.")
    else:
        seedream_submitted = bool(getattr(seedream_execution, "submitted", False))
        seedream_failed_count = int(getattr(seedream_execution, "failed_count", 0))
        if not seedream_submitted or seedream_failed_count > 0:
            errors.append(
                "Seedream media generation failed: "
                f"submitted={seedream_submitted}, "
                f"generated_count={getattr(seedream_execution, 'generated_count', 0)}, "
                f"failed_count={seedream_failed_count}, "
                f"note={getattr(seedream_execution, 'note', '')}"
            )

    seedance_submitted = bool(getattr(seedance_execution, "submitted", False))
    seedance_failed_count = int(getattr(seedance_execution, "failed_count", 0))
    seedance_pending_count = int(getattr(seedance_execution, "pending_count", 0))
    if not seedance_submitted or seedance_failed_count > 0 or seedance_pending_count > 0:
        errors.append(
            "Seedance video generation failed: "
            f"submitted={seedance_submitted}, "
            f"completed_count={getattr(seedance_execution, 'completed_count', 0)}, "
            f"failed_count={seedance_failed_count}, "
            f"pending_count={seedance_pending_count}, "
            f"note={getattr(seedance_execution, 'note', '')}"
        )

    return " | ".join(errors)


def _build_requested_image_error(seedream_execution: object | None) -> str:
    if seedream_execution is None:
        return "Seedream did not return an execution report."

    seedream_submitted = bool(getattr(seedream_execution, "submitted", False))
    seedream_failed_count = int(getattr(seedream_execution, "failed_count", 0))
    if seedream_submitted and seedream_failed_count == 0:
        return ""
    return (
        "Seedream image generation failed: "
        f"submitted={seedream_submitted}, "
        f"generated_count={getattr(seedream_execution, 'generated_count', 0)}, "
        f"failed_count={seedream_failed_count}, "
        f"note={getattr(seedream_execution, 'note', '')}"
    )


def _build_requested_video_error(seedance_execution: object) -> str:
    seedance_submitted = bool(getattr(seedance_execution, "submitted", False))
    seedance_failed_count = int(getattr(seedance_execution, "failed_count", 0))
    seedance_pending_count = int(getattr(seedance_execution, "pending_count", 0))
    if seedance_submitted and seedance_failed_count == 0 and seedance_pending_count == 0:
        return ""
    return (
        "Seedance video generation failed: "
        f"submitted={seedance_submitted}, "
        f"completed_count={getattr(seedance_execution, 'completed_count', 0)}, "
        f"failed_count={seedance_failed_count}, "
        f"pending_count={seedance_pending_count}, "
        f"note={getattr(seedance_execution, 'note', '')}"
    )
