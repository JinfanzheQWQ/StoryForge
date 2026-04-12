from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from storyforge.api.serializers import build_project_detail_response, build_project_summary_response
from storyforge.api.schemas import (
    BuildProjectRequest,
    CreateStageTaskRequest,
    CreateStoryTaskRequest,
    JobAcceptedResponse,
    ProjectDetailResponse,
    ProjectSummaryResponse,
)


router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummaryResponse])
async def list_projects(request: Request) -> list[ProjectSummaryResponse]:
    container = request.app.state.container
    return [
        build_project_summary_response(item, container.task_queue.store)
        for item in container.project_store.list()
    ]


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: str, request: Request) -> ProjectDetailResponse:
    container = request.app.state.container
    project = container.project_store.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return build_project_detail_response(project, container.task_queue.store)


@router.post("/novel", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_story_job(
    payload: CreateStoryTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
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

    record = await container.task_queue.submit(
        project_id=project_id,
        task_type="project.story",
        payload={
            "project_id": project_id,
            "brief": payload.brief.model_dump(),
            "use_llm": payload.use_llm,
        },
    )
    project_store.attach_task(project_id, record.task_id, payload.brief.model_dump())
    return JobAcceptedResponse(project_id=project_id, task_id=record.task_id, status=record.status)


@router.post("/images", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_image_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
    if payload.use_llm is not None:
        task_payload["use_llm"] = payload.use_llm

    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.images",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.post("/characters", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_character_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
    if payload.use_llm is not None:
        task_payload["use_llm"] = payload.use_llm

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


@router.post("/scenes", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scene_job(
    payload: CreateStageTaskRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.get(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {payload.project_id} not found")

    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.scenes",
        payload={
            "project_id": payload.project_id,
            "source_task_id": payload.source_task_id,
        },
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

    task_payload = {
        "project_id": payload.project_id,
        "source_task_id": payload.source_task_id,
    }
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


@router.post("/novel-to-video", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_project_job(
    payload: BuildProjectRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    queue = container.task_queue
    project_store = container.project_store
    project_id = payload.project_id
    if project_id:
        project = project_store.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    else:
        project = project_store.create(payload.brief.model_dump())
        project_id = project.project_id

    record = await queue.submit(
        project_id=project_id,
        task_type="project.build",
        payload={
            "project_id": project_id,
            "brief": payload.brief.model_dump(),
            "use_llm": payload.use_llm,
            "submit_seedance": payload.submit_seedance,
        },
    )
    project_store.attach_task(project_id, record.task_id, payload.brief.model_dump())
    return JobAcceptedResponse(project_id=project_id, task_id=record.task_id, status=record.status)
