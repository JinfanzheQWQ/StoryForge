from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from storyforge.api.artifacts import build_task_artifacts
from storyforge.api.serializers import build_task_response
from storyforge.api.schemas import TaskArtifactsResponse, TaskResponse


router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
async def list_tasks(request: Request) -> list[TaskResponse]:
    store = request.app.state.container.task_queue.store
    return [build_task_response(item) for item in store.list()]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, request: Request) -> TaskResponse:
    store = request.app.state.container.task_queue.store
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return build_task_response(task)


@router.get("/{task_id}/artifacts", response_model=TaskArtifactsResponse)
async def get_task_artifacts(task_id: str, request: Request) -> TaskArtifactsResponse:
    container = request.app.state.container
    task = container.task_queue.store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    output_root = container.project_root / container.config.paths.output_dir
    return build_task_artifacts(task, output_root=output_root)
