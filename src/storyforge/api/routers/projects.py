from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from storyforge.api.serializers import (
    build_project_detail_response,
    build_project_summary_responses,
)
from storyforge.api.schemas import (
    BuildProjectRequest,
    CreateStageTaskRequest,
    CreateStoryTaskRequest,
    JobAcceptedResponse,
    ProjectDeletedResponse,
    ProjectDetailResponse,
    ProjectSummaryResponse,
    StorySourceResponse,
    UpdateStorySourceRequest,
)
from storyforge.application.tasks import utc_now
from storyforge.application.project_deletion import delete_project_output_dirs
from storyforge.application.task_support import resolve_pipeline_root_task_id
from storyforge.core.io import read_json
from storyforge.domains.novel.contracts import DraftChapter, StorySourcePackage
from storyforge.pipelines.story_files import (
    clear_story_derived_artifacts,
    prune_story_derived_result,
    write_story_source_files,
)


router = APIRouter(prefix="/v1/projects", tags=["projects"])


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


@router.get("", response_model=list[ProjectSummaryResponse])
async def list_projects(request: Request) -> list[ProjectSummaryResponse]:
    container = request.app.state.container
    return build_project_summary_responses(
        container.project_store.list(),
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
    container = request.app.state.container
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
    record = await container.task_queue.submit(
        project_id=project_id,
        task_type="project.story",
        payload=task_payload,
    )
    project_store.attach_task(project_id, record.task_id, payload.brief.model_dump())
    return JobAcceptedResponse(project_id=project_id, task_id=record.task_id, status=record.status)


@router.post("/images", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_image_job(
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
    if payload.use_llm is not None:
        task_payload["use_llm"] = payload.use_llm
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)

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


@router.post("/story-analysis", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_story_analysis_job(
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
    existing_task = _find_existing_story_analysis_task(
        container,
        project_id=payload.project_id,
        source_task_id=payload.source_task_id,
        pipeline_root_task_id=resolve_pipeline_root_task_id(source_task),
        story_source_revision=str(source_task.result.get("story_source_revision", "")),
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
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
    record = await container.task_queue.submit(
        project_id=payload.project_id,
        task_type="project.story_analysis",
        payload=task_payload,
    )
    container.project_store.attach_task(payload.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=payload.project_id,
        task_id=record.task_id,
        status=record.status,
    )


def _find_existing_story_analysis_task(
    container,
    *,
    project_id: str,
    source_task_id: str,
    pipeline_root_task_id: str,
    story_source_revision: str,
):
    for task in container.task_queue.store.list(project_id=project_id):
        if task.task_type != "project.story_analysis":
            continue
        if str(task.payload.get("source_task_id", "")) != source_task_id:
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
):
    expected_segment_id = segment_id or ""
    expected_scene_id = scene_id or ""
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
        if task.status in {"queued", "running"}:
            return task
    return None


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
    if payload.use_llm is not None:
        task_payload["use_llm"] = payload.use_llm
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)

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

    existing_task = _find_existing_stage_task(
        container,
        project_id=payload.project_id,
        task_type="project.scenes",
        source_task_id=payload.source_task_id,
        segment_id=payload.segment_id,
        scene_id=payload.scene_id,
        master_only=payload.master_only,
        merge_only=False,
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
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    if payload.scene_id:
        task_payload["scene_id"] = payload.scene_id
    if payload.master_only:
        task_payload["master_only"] = True
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)

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
        merge_only=payload.merge_only,
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
    if payload.merge_only:
        task_payload["merge_only"] = True
    if payload.segment_id:
        task_payload["segment_id"] = payload.segment_id
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)
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
    _ensure_live_llm_requested(payload.use_llm)
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

    task_payload = {
        "project_id": project_id,
        "brief": payload.brief.model_dump(),
        "use_llm": payload.use_llm,
        "submit_seedance": payload.submit_seedance,
    }
    _apply_llm_selection(task_payload, payload.llm_provider, payload.llm_model)

    record = await queue.submit(
        project_id=project_id,
        task_type="project.build",
        payload=task_payload,
    )
    project_store.attach_task(project_id, record.task_id, payload.brief.model_dump())
    return JobAcceptedResponse(project_id=project_id, task_id=record.task_id, status=record.status)


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
