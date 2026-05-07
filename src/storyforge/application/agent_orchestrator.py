from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from storyforge.application.agent_sessions import AgentSessionRecord, AgentSessionStore
from storyforge.application.projects import ProjectStore
from storyforge.application.task_support import resolve_pipeline_root_task_id
from storyforge.application.tasks import AsyncTaskQueue, TaskRecord, utc_now


@dataclass(frozen=True, slots=True)
class StageSubmission:
    task_type: str
    submitting_stage: str
    waiting_stage: str
    message: str
    merge_only: bool = False


STORY_SUBMISSION = StageSubmission(
    task_type="project.story",
    submitting_stage="submitting_story",
    waiting_stage="waiting_story",
    message="正在生成小说正文...",
)

NEXT_STAGE_BY_WAITING_STAGE: dict[str, StageSubmission] = {
    "waiting_story": StageSubmission(
        task_type="project.scene_structure",
        submitting_stage="submitting_scene_structure",
        waiting_stage="waiting_scene_structure",
        message="小说正文已完成，正在拆分场景结构...",
    ),
    "waiting_scene_structure": StageSubmission(
        task_type="project.segment_contracts",
        submitting_stage="submitting_segment_contracts",
        waiting_stage="waiting_segment_contracts",
        message="场景结构已完成，正在生成分段合同...",
    ),
    "waiting_segment_contracts": StageSubmission(
        task_type="project.characters",
        submitting_stage="submitting_characters",
        waiting_stage="waiting_characters",
        message="分段合同已完成，正在生成角色图...",
    ),
    "waiting_characters": StageSubmission(
        task_type="project.scenes",
        submitting_stage="submitting_scenes",
        waiting_stage="waiting_scenes",
        message="角色图已完成，正在生成场景母图...",
    ),
    "waiting_scenes": StageSubmission(
        task_type="project.storyboards",
        submitting_stage="submitting_storyboards",
        waiting_stage="waiting_storyboards",
        message="场景母图已完成，正在生成九宫格分镜图...",
    ),
    "waiting_storyboards": StageSubmission(
        task_type="project.videos",
        submitting_stage="submitting_videos",
        waiting_stage="waiting_videos",
        message="九宫格分镜图已完成，正在生成分段视频...",
    ),
    "waiting_videos": StageSubmission(
        task_type="project.videos",
        submitting_stage="submitting_merge",
        waiting_stage="waiting_merge",
        message="分段视频已完成，正在合并总片...",
        merge_only=True,
    ),
}

RERUN_SUBMISSION_BY_STAGE: dict[str, StageSubmission] = {
    "ready_to_submit_story": STORY_SUBMISSION,
    STORY_SUBMISSION.submitting_stage: STORY_SUBMISSION,
    STORY_SUBMISSION.waiting_stage: STORY_SUBMISSION,
}
for _submission in NEXT_STAGE_BY_WAITING_STAGE.values():
    RERUN_SUBMISSION_BY_STAGE[_submission.submitting_stage] = _submission
    RERUN_SUBMISSION_BY_STAGE[_submission.waiting_stage] = _submission


class StageTaskGateway:
    def __init__(self, project_store: ProjectStore, task_queue: AsyncTaskQueue) -> None:
        self._project_store = project_store
        self._task_queue = task_queue

    async def submit_story(self, session: AgentSessionRecord) -> tuple[str, TaskRecord]:
        brief = dict(session.intent or {})
        if not brief:
            raise ValueError("Agent session 缺少可执行的小说 brief。")

        project = self._project_store.create(brief)
        record = await self._submit_story_task(project.project_id, brief, session.settings)
        return project.project_id, record

    async def resubmit_story(self, session: AgentSessionRecord) -> tuple[str, TaskRecord]:
        brief = dict(session.intent or {})
        if not brief:
            raise ValueError("Agent session 缺少可执行的小说 brief。")

        project_id = session.project_id
        if project_id:
            project = self._project_store.get(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found.")
        else:
            project = self._project_store.create(brief)
            project_id = project.project_id
        record = await self._submit_story_task(project_id, brief, session.settings)
        return project_id, record

    async def _submit_story_task(
        self,
        project_id: str,
        brief: dict[str, Any],
        settings: dict[str, Any],
    ) -> TaskRecord:
        payload = {
            "project_id": project_id,
            "brief": brief,
            "use_llm": True,
        }
        _apply_common_settings(payload, settings)
        record = await self._task_queue.submit(
            project_id=project_id,
            task_type=STORY_SUBMISSION.task_type,
            payload=payload,
        )
        self._project_store.attach_task(project_id, record.task_id, brief)
        return record

    async def submit_stage(
        self,
        session: AgentSessionRecord,
        submission: StageSubmission,
    ) -> TaskRecord:
        project_id = _required(session.project_id, "project_id")
        source_task_id = _required(session.source_task_id, "source_task_id")
        project = self._project_store.get(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found.")

        source_task = self._task_queue.store.get(source_task_id)
        if source_task is None or source_task.project_id != project_id:
            raise ValueError(f"Source task {source_task_id} not found for project {project_id}.")

        payload: dict[str, object] = {
            "project_id": project_id,
            "source_task_id": source_task_id,
            "pipeline_root_task_id": resolve_pipeline_root_task_id(source_task),
        }
        if submission.task_type in {"project.scene_structure", "project.segment_contracts"}:
            payload["use_llm"] = True
        if submission.task_type == "project.storyboards":
            payload["video_mode"] = "grid_storyboard"
        if submission.merge_only:
            payload["merge_only"] = True
        _apply_common_settings(payload, session.settings)

        record = await self._task_queue.submit(
            project_id=project_id,
            task_type=submission.task_type,
            payload=payload,
        )
        self._project_store.attach_task(project_id, record.task_id, project.brief)
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        return self._task_queue.store.get(task_id)


class AgentSessionRunner:
    def __init__(self, store: AgentSessionStore, gateway: StageTaskGateway) -> None:
        self._store = store
        self._gateway = gateway

    async def advance(self, session_id: str) -> AgentSessionRecord | None:
        session = self._store.get_session(session_id)
        if session is None or session.status in {"completed", "failed", "paused", "canceled"}:
            return session

        if session.status == "running" and session.current_stage == "ready_to_submit_story":
            return await self._submit_story(session)

        if session.status != "waiting_task":
            return session

        task = self._get_current_task(session)
        if task is None:
            return self._fail_session(
                session,
                message=f"当前阶段任务 {session.current_task_id or ''} 不存在。",
                task_id=session.current_task_id,
            )
        if task.status in {"queued", "running"}:
            return session
        if task.status == "failed":
            return self._fail_session(
                session,
                message=task.error or f"任务 {task.task_id} 执行失败。",
                task_id=task.task_id,
            )
        if task.status != "completed":
            return session
        if session.current_stage == "waiting_merge":
            return self._complete_session(session, task)

        submission = NEXT_STAGE_BY_WAITING_STAGE.get(session.current_stage)
        if submission is None:
            return session
        return await self._submit_stage(session, submission)

    async def rerun_current_stage(self, session_id: str) -> AgentSessionRecord | None:
        session = self._store.get_session(session_id)
        if session is None:
            return None
        if session.status == "canceled":
            raise ValueError("已终止的 Agent 会话不可恢复，也不能重新跑当前阶段。")
        if session.status not in {"paused", "failed"}:
            raise ValueError("当前状态不能重新跑当前阶段；运行中的会话请先暂停。")

        submission = RERUN_SUBMISSION_BY_STAGE.get(session.current_stage)
        if submission is None:
            raise ValueError(f"当前阶段 {session.current_stage} 没有可重新提交的生产任务。")
        if submission is STORY_SUBMISSION:
            return await self._resubmit_story(session)
        return await self._resubmit_stage(session, submission)

    async def _submit_story(self, session: AgentSessionRecord) -> AgentSessionRecord:
        submitting = self._store.update_session(
            session.session_id,
            status="running",
            current_stage=STORY_SUBMISSION.submitting_stage,
            error=None,
        )
        try:
            project_id, task = await self._gateway.submit_story(submitting)
        except Exception as exc:
            return self._fail_session(submitting, message=str(exc))
        updated = self._store.update_session(
            session.session_id,
            project_id=project_id,
            source_task_id=task.task_id,
            current_task_id=task.task_id,
            status="waiting_task",
            current_stage=STORY_SUBMISSION.waiting_stage,
            error=None,
        )
        self._append_progress(updated, STORY_SUBMISSION, task)
        return updated

    async def _submit_stage(
        self,
        session: AgentSessionRecord,
        submission: StageSubmission,
    ) -> AgentSessionRecord:
        submitting = self._store.update_session(
            session.session_id,
            status="running",
            current_stage=submission.submitting_stage,
            error=None,
        )
        try:
            task = await self._gateway.submit_stage(submitting, submission)
        except Exception as exc:
            return self._fail_session(submitting, message=str(exc))
        updated = self._store.update_session(
            session.session_id,
            current_task_id=task.task_id,
            status="waiting_task",
            current_stage=submission.waiting_stage,
            error=None,
        )
        self._append_progress(updated, submission, task)
        return updated

    async def _resubmit_story(self, session: AgentSessionRecord) -> AgentSessionRecord:
        submitting = self._store.update_session(
            session.session_id,
            status="running",
            current_stage=STORY_SUBMISSION.submitting_stage,
            error=None,
            finished_at=None,
        )
        try:
            project_id, task = await self._gateway.resubmit_story(submitting)
        except Exception as exc:
            return self._fail_session(submitting, message=str(exc))
        updated = self._store.update_session(
            session.session_id,
            project_id=project_id,
            source_task_id=task.task_id,
            current_task_id=task.task_id,
            status="waiting_task",
            current_stage=STORY_SUBMISSION.waiting_stage,
            error=None,
            finished_at=None,
        )
        self._append_progress(
            updated,
            STORY_SUBMISSION,
            task,
            content="已重新提交当前阶段：小说正文。正在等待新任务完成。",
            payload_extra={"action": "rerun_current_stage"},
        )
        return updated

    async def _resubmit_stage(
        self,
        session: AgentSessionRecord,
        submission: StageSubmission,
    ) -> AgentSessionRecord:
        submitting = self._store.update_session(
            session.session_id,
            status="running",
            current_stage=submission.submitting_stage,
            error=None,
            finished_at=None,
        )
        try:
            task = await self._gateway.submit_stage(submitting, submission)
        except Exception as exc:
            return self._fail_session(submitting, message=str(exc))
        updated = self._store.update_session(
            session.session_id,
            current_task_id=task.task_id,
            status="waiting_task",
            current_stage=submission.waiting_stage,
            error=None,
            finished_at=None,
        )
        self._append_progress(
            updated,
            submission,
            task,
            content=f"已重新提交当前阶段：{_stage_label(submission.waiting_stage)}。正在等待新任务完成。",
            payload_extra={"action": "rerun_current_stage"},
        )
        return updated

    def _get_current_task(self, session: AgentSessionRecord) -> TaskRecord | None:
        task_id = str(session.current_task_id or "").strip()
        if not task_id:
            return None
        return self._gateway.get_task(task_id)

    def _append_progress(
        self,
        session: AgentSessionRecord,
        submission: StageSubmission,
        task: TaskRecord,
        *,
        content: str | None = None,
        payload_extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "project_id": task.project_id,
            "next_stage": submission.waiting_stage,
        }
        if payload_extra:
            payload.update(payload_extra)
        self._store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="progress",
            content=content or submission.message,
            payload=payload,
        )
        self._store.append_event(
            session_id=session.session_id,
            stage=submission.waiting_stage,
            status="waiting_task",
            message=content or submission.message,
            task_id=task.task_id,
            payload=payload,
        )

    def _fail_session(
        self,
        session: AgentSessionRecord,
        *,
        message: str,
        task_id: str | None = None,
    ) -> AgentSessionRecord:
        updated = self._store.update_session(
            session.session_id,
            status="failed",
            error=message,
            finished_at=utc_now(),
        )
        self._store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="error",
            content=f"自动创作失败：{message}",
            payload={"stage": updated.current_stage, "task_id": task_id or updated.current_task_id},
        )
        self._store.append_event(
            session_id=session.session_id,
            stage=updated.current_stage,
            status="failed",
            message=message,
            task_id=task_id or updated.current_task_id,
        )
        return updated

    def _complete_session(self, session: AgentSessionRecord, task: TaskRecord) -> AgentSessionRecord:
        result = _build_session_result(session, task)
        updated = self._store.update_session(
            session.session_id,
            status="completed",
            current_stage="completed",
            result=result,
            error=None,
            finished_at=utc_now(),
        )
        content = "成片已完成。你可以直接预览视频，也可以进入项目工作台继续修改。"
        self._store.append_message(
            session_id=session.session_id,
            role="assistant",
            type="result",
            content=content,
            payload=result,
        )
        self._store.append_event(
            session_id=session.session_id,
            stage="completed",
            status="completed",
            message=content,
            task_id=task.task_id,
            payload=result,
        )
        return updated


def _apply_common_settings(payload: dict[str, object], settings: dict[str, Any]) -> None:
    continuity_review_mode = str(settings.get("continuity_review_mode") or "auto").strip().lower()
    if continuity_review_mode in {"off", "auto", "on"}:
        payload["continuity_review_mode"] = continuity_review_mode
    for source_key, target_key in (
        ("llm_provider", "llm_provider"),
        ("llm_model", "llm_model"),
        ("video_mode", "video_mode"),
        ("image_model", "image_model"),
        ("image_size", "image_size"),
        ("image_aspect_ratio", "image_aspect_ratio"),
        ("storyboard_image_model", "storyboard_image_model"),
        ("storyboard_size", "storyboard_size"),
        ("storyboard_aspect_ratio", "storyboard_aspect_ratio"),
    ):
        value = str(settings.get(source_key) or "").strip()
        if value:
            payload[target_key] = value

    image_model = str(settings.get("image_model") or "").strip()
    image_size = str(settings.get("image_size") or "").strip()
    image_aspect_ratio = str(settings.get("image_aspect_ratio") or "").strip()
    if image_model:
        payload.setdefault("storyboard_image_model", image_model)
    if image_size:
        payload.setdefault("storyboard_size", image_size)
    if image_aspect_ratio:
        payload.setdefault("storyboard_aspect_ratio", image_aspect_ratio)

    for key in ("seedream_watermark", "seedance_watermark"):
        if key in settings:
            payload[key] = bool(settings[key])


def _required(value: str | None, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Agent session 缺少 {field_name}。")
    return normalized


def _stage_label(stage: str) -> str:
    labels = {
        "waiting_story": "小说正文",
        "waiting_scene_structure": "场景结构",
        "waiting_segment_contracts": "分段合同",
        "waiting_characters": "角色图",
        "waiting_scenes": "场景母图",
        "waiting_storyboards": "九宫格分镜图",
        "waiting_videos": "分段视频",
        "waiting_merge": "合并成片",
    }
    return labels.get(stage, stage)


def _build_session_result(session: AgentSessionRecord, task: TaskRecord) -> dict[str, Any]:
    task_result = dict(task.result or {})
    project_id = str(session.project_id or task.project_id)
    source_task_id = str(session.source_task_id or "")
    return {
        "project_id": project_id,
        "source_task_id": source_task_id,
        "workspace_url": f"/projects/{project_id}/workflow/{source_task_id}",
        "merge_task_id": task.task_id,
        "full_story_path": task_result.get("full_story_path"),
        "rendered_clips": task_result.get("rendered_clips", []),
        "output_dir": task_result.get("output_dir"),
        "merged_clip_count": task_result.get("merged_clip_count", 0),
        "skipped_clip_count": task_result.get("skipped_clip_count", 0),
    }
