from __future__ import annotations

from storyforge.api.schemas import ProjectDetailResponse, ProjectSummaryResponse, StoryBriefInput, TaskResponse
from storyforge.application.projects import ProjectRecord
from storyforge.application.tasks import TaskRecord, TaskStore


def build_task_response(task: TaskRecord) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        project_id=task.project_id,
        task_type=task.task_type,
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        payload=task.payload,
        result=task.result,
        error=task.error,
    )


def build_project_summary_response(
    project: ProjectRecord,
    task_store: TaskStore,
) -> ProjectSummaryResponse:
    latest_task = (
        task_store.get_many([project.latest_task_id]).get(project.latest_task_id)
        if project.latest_task_id
        else None
    )
    tasks = task_store.list(project_id=project.project_id)
    return _build_project_summary_response(project, tasks, latest_task)


def build_project_summary_responses(
    projects: list[ProjectRecord],
    task_store: TaskStore,
) -> list[ProjectSummaryResponse]:
    if not projects:
        return []

    tasks_by_project = task_store.list_grouped(project.project_id for project in projects)
    latest_task_map = task_store.get_many(
        project.latest_task_id for project in projects if project.latest_task_id
    )
    return [
        _build_project_summary_response(
            project,
            tasks_by_project.get(project.project_id, []),
            latest_task_map.get(project.latest_task_id or ""),
        )
        for project in projects
    ]


def _build_project_summary_response(
    project: ProjectRecord,
    tasks: list[TaskRecord],
    latest_task: TaskRecord | None,
) -> ProjectSummaryResponse:
    logical_runs = _group_tasks_by_run(tasks)
    latest_tasks = [
        _select_latest_task(items)
        for items in logical_runs.values()
        if items
    ]
    return ProjectSummaryResponse(
        project_id=project.project_id,
        title_hint=project.title_hint,
        product_type=_resolve_project_product_type(project),
        story_title=project.story_title,
        created_at=project.created_at,
        updated_at=project.updated_at,
        latest_task_id=project.latest_task_id,
        latest_status=latest_task.status if latest_task else None,
        latest_output_dir=project.last_output_dir,
        run_count=len(logical_runs),
        completed_run_count=sum(1 for item in latest_tasks if item.status == "completed"),
        failed_run_count=sum(1 for item in latest_tasks if item.status == "failed"),
        full_story_count=sum(
            1
            for run_tasks in logical_runs.values()
            if any(item.result and item.result.get("full_story_path") for item in run_tasks)
        ),
    )


def build_project_detail_response(
    project: ProjectRecord,
    task_store: TaskStore,
) -> ProjectDetailResponse:
    summary = build_project_summary_response(project, task_store)
    tasks = [build_task_response(item) for item in task_store.list(project_id=project.project_id)]
    return ProjectDetailResponse(
        **summary.model_dump(),
        brief=StoryBriefInput(**project.brief),
        tasks=tasks,
    )


def _group_tasks_by_run(tasks: list[TaskRecord]) -> dict[str, list[TaskRecord]]:
    grouped: dict[str, list[TaskRecord]] = {}
    for task in tasks:
        run_id = _logical_run_id(task)
        grouped.setdefault(run_id, []).append(task)
    return grouped


def _logical_run_id(task: TaskRecord) -> str:
    if task.result and task.result.get("pipeline_root_task_id"):
        return str(task.result["pipeline_root_task_id"])
    if task.payload and task.payload.get("pipeline_root_task_id"):
        return str(task.payload["pipeline_root_task_id"])
    return task.task_id


def _select_latest_task(tasks: list[TaskRecord]) -> TaskRecord:
    return max(tasks, key=lambda item: (item.created_at, item.finished_at or ""))


def _resolve_project_product_type(project: ProjectRecord) -> str:
    project_kind = str(project.brief.get("project_kind", ""))
    if project_kind in {"image_generation", "image_studio"}:
        return "image_generation"
    return "novel_to_video"
