from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.application.projects import ProjectStore
from storyforge.application.task_runtime import TaskExecutionContext, build_task_handler
from storyforge.application.tasks import AsyncTaskQueue, TaskStore
from storyforge.core.config import AppConfig


@dataclass(slots=True)
class AppContainer:
    project_root: Path
    config: AppConfig
    project_store: ProjectStore
    task_queue: AsyncTaskQueue


def build_container(project_root: Path, config: AppConfig) -> AppContainer:
    state_dir = project_root / config.paths.workspace_dir / "state"
    if config.database.enabled:
        from storyforge.application.persistence.mysql_backend import MySQLBackend
        from storyforge.application.persistence.mysql_projects import MySQLProjectStore
        from storyforge.application.persistence.mysql_tasks import MySQLTaskStore

        database_backend = MySQLBackend(config.database)
        project_store = MySQLProjectStore(database_backend)
        task_store = MySQLTaskStore(database_backend)
    else:
        project_store = ProjectStore(state_dir / "projects.json")
        task_store = TaskStore(state_dir / "tasks.json")

    context = TaskExecutionContext(
        project_root=project_root,
        config=config,
        project_store=project_store,
        task_store=task_store,
    )
    task_queue = AsyncTaskQueue(
        concurrency=config.queue.concurrency,
        handler=build_task_handler(context),
        store=task_store,
    )
    return AppContainer(
        project_root=project_root,
        config=config,
        project_store=project_store,
        task_queue=task_queue,
    )
