from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from storyforge.application.projects import ProjectStore
from storyforge.application.task_handlers import (
    run_image_generation_task,
    run_characters_task,
    run_continuity_repair_batch_task,
    run_continuity_repair_task,
    run_scene_structure_task,
    run_segment_contracts_task,
    run_scenes_task,
    run_story_task,
    run_videos_task,
)
from storyforge.application.tasks import QueuedTask, TaskHandler, TaskStore
from storyforge.core.config import AppConfig


@dataclass(slots=True)
class TaskExecutionContext:
    project_root: Path
    config: AppConfig
    project_store: ProjectStore
    task_store: TaskStore


def build_task_handler(context: TaskExecutionContext) -> TaskHandler:
    async def handle_task(task: QueuedTask) -> dict[str, object]:
        return await asyncio.to_thread(dispatch_task, context, task)

    return handle_task


def dispatch_task(
    context: TaskExecutionContext,
    task: QueuedTask,
) -> dict[str, object]:
    handlers = {
        "image.generate": run_image_generation_task,
        "project.story": run_story_task,
        "project.scene_structure": run_scene_structure_task,
        "project.segment_contracts": run_segment_contracts_task,
        "project.continuity_repair": run_continuity_repair_task,
        "project.continuity_repair_batch": run_continuity_repair_batch_task,
        "project.characters": run_characters_task,
        "project.scenes": run_scenes_task,
        "project.videos": run_videos_task,
    }
    try:
        handler = handlers[task.task_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported task_type={task.task_type}") from exc
    return handler(context, task)
