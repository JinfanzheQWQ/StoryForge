from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status

from storyforge.api.schemas_agent import (
    AgentMessageCreateRequest,
    AgentMessageResponse,
    AgentMessagesResponse,
    AgentSessionCreateRequest,
    AgentSessionDeletedResponse,
    AgentSessionEventResponse,
    AgentSessionEventsResponse,
    AgentSessionProgressResponse,
    AgentSessionResponse,
    AgentSessionsResponse,
    AgentSessionWithMessagesResponse,
)
from storyforge.api.routers.projects import delete_project_records
from storyforge.application.agent_intent import AgentIntentPlanner, AgentIntentPlanningError
from storyforge.application.agent_orchestrator import AgentSessionRunner, StageTaskGateway
from storyforge.application.agent_sessions import (
    AgentMessageRecord,
    AgentSessionEventRecord,
    AgentSessionRecord,
)
from storyforge.application.tasks import utc_now


router = APIRouter(prefix="/v1/agent-sessions", tags=["agent-sessions"])


@router.post("", response_model=AgentSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_session(
    payload: AgentSessionCreateRequest,
    request: Request,
) -> AgentSessionResponse:
    store = request.app.state.container.agent_session_store
    session = store.create_session(
        product_type=payload.product_type,
        mode=payload.mode,
        status="created",
        current_stage="created",
        settings=payload.settings,
    )
    store.append_event(
        session_id=session.session_id,
        stage="created",
        status="created",
        message="Agent 创作会话已创建。",
    )
    return _build_session_response(store.get_session(session.session_id) or session)


@router.get("", response_model=AgentSessionsResponse)
async def list_agent_sessions(request: Request, limit: int = 50) -> AgentSessionsResponse:
    store = request.app.state.container.agent_session_store
    sessions = store.list_sessions(limit=limit)
    return AgentSessionsResponse(sessions=[_build_session_response(item) for item in sessions])


@router.get("/{session_id}", response_model=AgentSessionResponse)
async def get_agent_session(session_id: str, request: Request) -> AgentSessionResponse:
    session = await _advance_or_404(request, session_id)
    return _build_session_response(session)


@router.delete("/{session_id}", response_model=AgentSessionDeletedResponse)
async def delete_agent_session(
    session_id: str,
    request: Request,
    delete_project: bool = False,
) -> AgentSessionDeletedResponse:
    store = request.app.state.container.agent_session_store
    session = _get_session_or_404(request, session_id)
    project_deleted = False
    if delete_project and session.project_id:
        try:
            project_deleted = delete_project_records(session.project_id, request.app.state.container).deleted
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    deleted = store.delete_session(session.session_id)
    return AgentSessionDeletedResponse(
        session_id=session.session_id,
        deleted=deleted,
        project_id=session.project_id,
        project_deleted=project_deleted,
    )


@router.post("/{session_id}/messages", response_model=AgentSessionWithMessagesResponse)
async def create_agent_message(
    session_id: str,
    payload: AgentMessageCreateRequest,
    request: Request,
) -> AgentSessionWithMessagesResponse:
    store = request.app.state.container.agent_session_store
    session = _get_session_or_404(request, session_id)
    store.append_message(
        session_id=session.session_id,
        role="user",
        type="text",
        content=payload.content,
    )
    if _is_pause_command(payload.content):
        session = _pause_session(store, session)
    elif _is_resume_command(payload.content):
        session = _resume_session(store, session)
        session = await _advance_session(request, session)
    elif _is_rerun_current_stage_command(payload.content):
        session = await _rerun_current_stage(request, store, session)
    elif _is_stop_command(payload.content):
        session = _cancel_session(store, session)
    elif _is_start_command(payload.content):
        session = _confirm_session_start(store, session)
        session = await _advance_session(request, session)
    else:
        if _is_locked_for_replanning(session):
            _append_locked_replanning_message(store, session)
            messages = store.list_messages(session.session_id)
            return AgentSessionWithMessagesResponse(
                session=_build_session_response(session),
                messages=[_build_message_response(item) for item in messages],
            )
        session = _plan_session(request, store, session, payload)
    messages = store.list_messages(session.session_id)
    return AgentSessionWithMessagesResponse(
        session=_build_session_response(session),
        messages=[_build_message_response(item) for item in messages],
    )


@router.post("/{session_id}/rerun-current-stage", response_model=AgentSessionWithMessagesResponse)
async def rerun_agent_session_current_stage(
    session_id: str,
    request: Request,
) -> AgentSessionWithMessagesResponse:
    store = request.app.state.container.agent_session_store
    session = _get_session_or_404(request, session_id)
    session = await _rerun_current_stage(request, store, session)
    messages = store.list_messages(session.session_id)
    return AgentSessionWithMessagesResponse(
        session=_build_session_response(session),
        messages=[_build_message_response(item) for item in messages],
    )


@router.get("/{session_id}/messages", response_model=AgentMessagesResponse)
async def list_agent_messages(session_id: str, request: Request) -> AgentMessagesResponse:
    await _advance_or_404(request, session_id)
    store = request.app.state.container.agent_session_store
    return AgentMessagesResponse(
        messages=[_build_message_response(item) for item in store.list_messages(session_id)]
    )


@router.get("/{session_id}/events", response_model=AgentSessionEventsResponse)
async def list_agent_events(session_id: str, request: Request) -> AgentSessionEventsResponse:
    await _advance_or_404(request, session_id)
    store = request.app.state.container.agent_session_store
    return AgentSessionEventsResponse(
        events=[_build_event_response(item) for item in store.list_events(session_id)]
    )


def _plan_session(
    request: Request,
    store,
    session: AgentSessionRecord,
    payload: AgentMessageCreateRequest,
) -> AgentSessionRecord:
    planner = AgentIntentPlanner(config=request.app.state.container.config)
    merged_settings = dict(session.settings or {})
    merged_settings.update(payload.settings or {})
    planning_prompt = _build_planning_prompt(session, payload.content)
    try:
        planned = planner.build_plan(planning_prompt, merged_settings)
    except (ValueError, AgentIntentPlanningError) as exc:
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="error",
            content=str(exc),
        )
        store.append_event(
            session_id=session.session_id,
            stage="planning",
            status="failed",
            message=str(exc),
        )
        return store.update_session(
            session.session_id,
            status="failed",
            current_stage="planning",
            error=str(exc),
        )

    updated = store.update_session(
        session.session_id,
        status="waiting_confirmation",
        current_stage="waiting_confirmation",
        user_prompt=planning_prompt,
        intent=planned.brief,
        plan=planned.plan,
        settings=planned.settings,
        error=None,
    )
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="plan",
        content=planned.assistant_message,
        payload={
            "brief": planned.brief,
            "settings": planned.settings,
            "plan": planned.plan,
            "actions": ["开始", "修改需求"],
        },
    )
    store.append_event(
        session_id=session.session_id,
        stage="waiting_confirmation",
        status="waiting_confirmation",
        message="Agent 已生成生产计划，等待用户确认。",
        payload={"plan": planned.plan},
    )
    return updated


def _confirm_session_start(store, session: AgentSessionRecord) -> AgentSessionRecord:
    if session.status != "waiting_confirmation":
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前会话还没有可执行的生产计划，请先输入创意。",
        )
        return session
    updated = store.update_session(
        session.session_id,
        status="running",
        current_stage="ready_to_submit_story",
        error=None,
    )
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="progress",
        content="已确认生产计划，准备开始生成小说正文。",
        payload={"next_stage": "submitting_story"},
    )
    store.append_event(
        session_id=session.session_id,
        stage="ready_to_submit_story",
        status="running",
        message="用户已确认生产计划，Session Runner 可以开始提交小说任务。",
    )
    return updated


def _pause_session(store, session: AgentSessionRecord) -> AgentSessionRecord:
    if session.status == "paused":
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前 Agent 创作已经暂停。你可以发送“继续”接着跑，或发送“终止”结束会话。",
            payload={"status": session.status},
        )
        return session
    if session.status not in {"running", "waiting_task"}:
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前阶段不需要暂停。确认计划前可以继续修改需求，或发送“终止”结束会话。",
            payload={"status": session.status},
        )
        return session
    updated = store.update_session(
        session.session_id,
        status="paused",
        error=None,
    )
    payload = {
        "paused_stage": session.current_stage,
        "current_task_id": session.current_task_id,
        "project_id": session.project_id,
        "source_task_id": session.source_task_id,
    }
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="progress",
        content="已暂停 Agent 自动创作。当前会话会保留进度；已有子任务如果正在底层执行，可能仍会跑完，但不会自动提交下一阶段。",
        payload=payload,
    )
    store.append_event(
        session_id=session.session_id,
        stage=session.current_stage,
        status="paused",
        message="用户已暂停 Agent 自动创作。",
        task_id=session.current_task_id,
        payload=payload,
    )
    return updated


def _resume_session(store, session: AgentSessionRecord) -> AgentSessionRecord:
    if session.status != "paused":
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前没有暂停中的 Agent 创作。运行中可以发送“暂停”，已终止的会话不能恢复。",
            payload={"status": session.status},
        )
        return session
    next_status = "waiting_task" if session.current_task_id else "running"
    updated = store.update_session(
        session.session_id,
        status=next_status,
        error=None,
        finished_at=None,
    )
    payload = {
        "resumed_stage": session.current_stage,
        "current_task_id": session.current_task_id,
        "project_id": session.project_id,
        "source_task_id": session.source_task_id,
    }
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="progress",
        content="已继续 Agent 自动创作，将从暂停前的当前进度接着跑。",
        payload=payload,
    )
    store.append_event(
        session_id=session.session_id,
        stage=session.current_stage,
        status="running",
        message="用户已继续 Agent 自动创作。",
        task_id=session.current_task_id,
        payload=payload,
    )
    return updated


async def _rerun_current_stage(request: Request, store, session: AgentSessionRecord) -> AgentSessionRecord:
    if session.status == "canceled":
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前 Agent 会话已经终止，终止状态不可恢复，也不能重新跑当前阶段。",
            payload={"status": session.status},
        )
        return session
    container = request.app.state.container
    gateway = StageTaskGateway(container.project_store, container.task_queue)
    runner = AgentSessionRunner(store, gateway)
    try:
        rerun_session = await runner.rerun_current_stage(session.session_id)
    except ValueError as exc:
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content=str(exc),
            payload={"status": session.status, "current_stage": session.current_stage},
        )
        return session
    return rerun_session or session


def _cancel_session(store, session: AgentSessionRecord) -> AgentSessionRecord:
    if session.status in {"completed", "failed", "canceled"}:
        store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="text",
            content="当前会话已经结束，不需要再次停止。",
            payload={"status": session.status},
        )
        return session
    updated = store.update_session(
        session.session_id,
        status="canceled",
        current_stage="canceled",
        error="用户已终止 Agent 自动创作。",
        finished_at=utc_now(),
    )
    payload = {
        "previous_stage": session.current_stage,
        "current_task_id": session.current_task_id,
        "project_id": session.project_id,
        "source_task_id": session.source_task_id,
    }
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="progress",
        content="已停止 Agent 自动创作。当前会话不会继续提交后续阶段；如果已有子任务正在底层执行，完成后也不会触发下一步。",
        payload=payload,
    )
    store.append_event(
        session_id=session.session_id,
        stage="canceled",
        status="canceled",
        message="用户已终止 Agent 自动创作。",
        task_id=session.current_task_id,
        payload=payload,
    )
    return updated


def _is_locked_for_replanning(session: AgentSessionRecord) -> bool:
    return session.status in {"running", "waiting_task", "completed", "failed", "paused", "canceled"}


def _append_locked_replanning_message(store, session: AgentSessionRecord) -> None:
    if session.status == "paused":
        content = "当前 Agent 创作已暂停。请发送“继续”接着跑，或发送“终止”结束会话；暂停状态下不能重写生产计划。"
    else:
        content = "当前自动创作已经开始，不能再用普通消息重写生产计划。请进入项目工作台修改具体产物。"
    store.append_message(
        session_id=session.session_id,
        role="assistant",
        type="text",
        content=content,
    )


def _build_planning_prompt(session: AgentSessionRecord, latest_content: str) -> str:
    latest = latest_content.strip()
    if session.status != "waiting_confirmation" or not str(session.user_prompt or "").strip():
        return latest
    context = {
        "previous_user_prompt": session.user_prompt,
        "previous_intent": session.intent,
        "previous_plan": session.plan,
        "previous_settings": session.settings,
        "latest_user_message": latest,
    }
    return (
        "这是同一个 StoryForge Agent 创作会话里的计划修改，不是一个全新项目。\n"
        "请保留上一轮用户创意、题材、人物、场景、情绪和风格；"
        "只用最新用户消息覆盖其明确要求修改的部分。\n"
        "如果最新用户消息只是在修改字数、模型、比例、水印或流程参数，"
        "不要把这些参数本身当成故事题材，也不要丢弃上一轮故事内容。\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


async def _advance_or_404(request: Request, session_id: str) -> AgentSessionRecord:
    session = _get_session_or_404(request, session_id)
    return await _advance_session(request, session)


async def _advance_session(request: Request, session: AgentSessionRecord) -> AgentSessionRecord:
    container = request.app.state.container
    gateway = StageTaskGateway(container.project_store, container.task_queue)
    runner = AgentSessionRunner(container.agent_session_store, gateway)
    advanced = await runner.advance(session.session_id)
    return advanced or session


def _get_session_or_404(request: Request, session_id: str) -> AgentSessionRecord:
    session = request.app.state.container.agent_session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Agent session {session_id} not found")
    return session


def _is_start_command(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {"开始", "确认", "开始生成", "start", "go"}


def _is_pause_command(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {"暂停", "暂停生成", "先暂停", "pause"}


def _is_resume_command(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {"继续", "恢复", "接着跑", "继续生成", "resume", "continue"}


def _is_rerun_current_stage_command(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {
        "重新跑当前阶段",
        "重跑当前阶段",
        "重新生成当前阶段",
        "rerun current stage",
        "rerun",
    }


def _is_stop_command(content: str) -> bool:
    normalized = content.strip().lower()
    return normalized in {"停止", "停下", "终止", "取消", "停止生成", "终止生成", "取消生成", "stop", "cancel"}


def _build_session_response(session: AgentSessionRecord) -> AgentSessionResponse:
    return AgentSessionResponse(
        session_id=session.session_id,
        project_id=session.project_id,
        source_task_id=session.source_task_id,
        current_task_id=session.current_task_id,
        product_type=session.product_type,
        mode=session.mode,
        status=session.status,
        current_stage=session.current_stage,
        user_prompt=session.user_prompt,
        intent=session.intent,
        plan=session.plan,
        settings=session.settings,
        result=session.result,
        error=session.error,
        progress=_build_progress(session.current_stage, session.status),
        created_at=session.created_at,
        updated_at=session.updated_at,
        finished_at=session.finished_at,
    )


def _build_progress(current_stage: str, status: str) -> AgentSessionProgressResponse:
    if status == "completed":
        return AgentSessionProgressResponse(completed_steps=9, total_steps=9, percent=100)
    completed_by_stage = {
        "created": 0,
        "planning": 0,
        "waiting_confirmation": 0,
        "ready_to_submit_story": 0,
        "waiting_story": 1,
        "waiting_scene_structure": 2,
        "waiting_segment_contracts": 3,
        "waiting_characters": 4,
        "waiting_scenes": 5,
        "waiting_storyboards": 6,
        "waiting_videos": 7,
        "waiting_merge": 8,
    }
    completed = completed_by_stage.get(current_stage, 0)
    return AgentSessionProgressResponse(
        completed_steps=completed,
        total_steps=9,
        percent=round(completed / 9 * 100),
    )


def _build_message_response(message: AgentMessageRecord) -> AgentMessageResponse:
    return AgentMessageResponse(
        message_id=message.message_id,
        session_id=message.session_id,
        role=message.role,
        type=message.type,
        content=message.content,
        payload=message.payload,
        created_at=message.created_at,
    )


def _build_event_response(event: AgentSessionEventRecord) -> AgentSessionEventResponse:
    return AgentSessionEventResponse(
        event_id=event.event_id,
        session_id=event.session_id,
        stage=event.stage,
        status=event.status,
        message=event.message,
        task_id=event.task_id,
        payload=event.payload,
        created_at=event.created_at,
    )
