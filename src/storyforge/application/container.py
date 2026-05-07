from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.application.agent_sessions import AgentSessionStore
from storyforge.application.projects import ProjectStore
from storyforge.application.persistence.mysql_agent_sessions import MySQLAgentSessionStore
from storyforge.application.persistence.mysql_backend import MySQLBackend
from storyforge.application.persistence.mysql_projects import MySQLProjectStore
from storyforge.application.persistence.mysql_tasks import MySQLTaskStore
from storyforge.application.task_runtime import TaskExecutionContext, build_task_handler
from storyforge.application.tasks import AsyncTaskQueue
from storyforge.core.config import AppConfig


@dataclass(slots=True)
class AppContainer:
    project_root: Path
    config: AppConfig
    agent_session_store: AgentSessionStore
    project_store: ProjectStore
    task_queue: AsyncTaskQueue


def build_container(project_root: Path, config: AppConfig) -> AppContainer:
    database_backend = MySQLBackend(config.database)
    agent_session_store = MySQLAgentSessionStore(database_backend)
    project_store = MySQLProjectStore(database_backend)
    task_store = MySQLTaskStore(database_backend)

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
        agent_session_store=agent_session_store,
        project_store=project_store,
        task_queue=task_queue,
    )
