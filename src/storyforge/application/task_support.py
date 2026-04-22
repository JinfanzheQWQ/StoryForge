from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from storyforge.application.tasks import QueuedTask, TaskRecord
from storyforge.core.io import read_json
from storyforge.domains.novel.contracts import NovelPackage, StorySourcePackage

if TYPE_CHECKING:
    from storyforge.application.task_runtime import TaskExecutionContext


def persist_task_progress(
    context: TaskExecutionContext,
    task: QueuedTask,
    result: dict[str, object],
) -> None:
    context.task_store.update_result(task.task_id, result)
    context.project_store.mark_task_result(task.project_id, task.task_id, result)


def resolve_source_task(
    context: TaskExecutionContext,
    task: QueuedTask,
) -> TaskRecord:
    source_task_id = str(task.payload["source_task_id"])
    source_task = context.task_store.get(source_task_id)
    if source_task is None or source_task.project_id != task.project_id:
        raise ValueError(f"Source task {source_task_id} not found for project {task.project_id}")
    if source_task.status != "completed":
        raise ValueError(f"Source task {source_task_id} is not completed yet")
    return source_task


def resolve_output_dir(source_task: TaskRecord) -> Path:
    raw_output_dir = source_task.result.get("output_dir") if source_task.result else None
    if not raw_output_dir:
        raise ValueError(f"Source task {source_task.task_id} has no output_dir")
    return Path(str(raw_output_dir))


def load_novel_package(source_task: TaskRecord) -> NovelPackage:
    raw_package_path = source_task.result.get("novel_package_path") if source_task.result else None
    if not raw_package_path:
        raise ValueError(f"Source task {source_task.task_id} has no novel_package_path")
    package_path = Path(str(raw_package_path))
    if not package_path.exists():
        raise FileNotFoundError(f"Novel package not found at {package_path}")
    return NovelPackage.from_dict(read_json(package_path))


def load_story_source(source_task: TaskRecord) -> StorySourcePackage:
    raw_story_source_path = source_task.result.get("story_source_path") if source_task.result else None
    if not raw_story_source_path:
        raise ValueError(f"Source task {source_task.task_id} has no story_source_path")
    story_source_path = Path(str(raw_story_source_path))
    if not story_source_path.exists():
        raise FileNotFoundError(f"Story source not found at {story_source_path}")
    return StorySourcePackage.from_dict(read_json(story_source_path))


def resolve_story_title(source_task: TaskRecord) -> str:
    if source_task.result and source_task.result.get("story_title"):
        return str(source_task.result["story_title"])
    if source_task.payload and source_task.payload.get("brief"):
        return str(source_task.payload["brief"].get("title_hint", source_task.task_id))
    return source_task.task_id


def resolve_pipeline_root_task_id(source_task: TaskRecord) -> str:
    if source_task.result and source_task.result.get("pipeline_root_task_id"):
        return str(source_task.result["pipeline_root_task_id"])
    if source_task.payload and source_task.payload.get("pipeline_root_task_id"):
        return str(source_task.payload["pipeline_root_task_id"])
    return source_task.task_id


def resolve_llm_selection(task: QueuedTask | TaskRecord, source_task: TaskRecord | None = None) -> tuple[str | None, str | None]:
    payload = task.payload or {}
    if payload.get("llm_provider") or payload.get("llm_model"):
        return (
            str(payload.get("llm_provider") or "").strip() or None,
            str(payload.get("llm_model") or "").strip() or None,
        )
    if source_task is not None and source_task.payload:
        return (
            str(source_task.payload.get("llm_provider") or "").strip() or None,
            str(source_task.payload.get("llm_model") or "").strip() or None,
        )
    return (None, None)


def resolve_continuity_review_mode(
    task: QueuedTask | TaskRecord,
    source_task: TaskRecord | None = None,
    default: str = "auto",
) -> str:
    payload = task.payload or {}
    mode = str(payload.get("continuity_review_mode") or "").strip().lower()
    if mode in {"off", "auto", "on"}:
        return mode

    task_result = getattr(task, "result", None)
    if task_result:
        mode = str(task_result.get("continuity_review_mode") or "").strip().lower()
        if mode in {"off", "auto", "on"}:
            return mode

    if source_task is not None:
        source_payload = source_task.payload or {}
        mode = str(source_payload.get("continuity_review_mode") or "").strip().lower()
        if mode in {"off", "auto", "on"}:
            return mode
        if source_task.result:
            mode = str(source_task.result.get("continuity_review_mode") or "").strip().lower()
            if mode in {"off", "auto", "on"}:
                return mode

    return default


def resolve_media_watermark(
    task: QueuedTask | TaskRecord,
    *,
    target: str,
    source_task: TaskRecord | None = None,
    default: bool,
) -> bool:
    key = f"{str(target).strip().lower()}_watermark"
    for candidate in (
        getattr(task, "payload", None),
        getattr(task, "result", None),
        getattr(source_task, "payload", None) if source_task is not None else None,
        getattr(source_task, "result", None) if source_task is not None else None,
    ):
        if not candidate or key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(default)


def propagate_shared_result(
    context: TaskExecutionContext,
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
        if context.task_store.get(task_id) is None:
            continue
        context.task_store.update_result(task_id, shared_result)


def refresh_artifact_revision_for_tasks(
    context: TaskExecutionContext,
    task_ids: set[str],
    artifact_revision: str,
    exclude_task_id: str | None = None,
) -> None:
    for task_id in task_ids:
        if not task_id or task_id == exclude_task_id:
            continue
        record = context.task_store.get(task_id)
        if record is None or record.result is None:
            continue
        updated_result = dict(record.result)
        updated_result["artifact_revision"] = artifact_revision
        context.task_store.update_result(task_id, updated_result)
        context.project_store.mark_task_result(record.project_id, task_id, updated_result)

def build_requested_image_error(seedream_execution: object | None) -> str:
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


def build_requested_video_error(seedance_execution: object) -> str:
    seedance_submitted = bool(getattr(seedance_execution, "submitted", False))
    seedance_failed_count = int(getattr(seedance_execution, "failed_count", 0))
    seedance_pending_count = int(getattr(seedance_execution, "pending_count", 0))
    if seedance_submitted and seedance_failed_count == 0 and seedance_pending_count == 0:
        return ""
    base_message = (
        "Seedance video generation failed: "
        f"submitted={seedance_submitted}, "
        f"completed_count={getattr(seedance_execution, 'completed_count', 0)}, "
        f"failed_count={seedance_failed_count}, "
        f"pending_count={seedance_pending_count}, "
        f"note={getattr(seedance_execution, 'note', '')}"
    )
    clip_error_details = _build_seedance_clip_error_details(seedance_execution)
    if clip_error_details:
        return f"{base_message} | {clip_error_details}"
    return base_message


def _build_seedance_clip_error_details(seedance_execution: object) -> str:
    raw_clip_results = getattr(seedance_execution, "clip_results", None)
    if not raw_clip_results:
        return ""

    details: list[str] = []
    for item in raw_clip_results:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("segment_id") or "unknown-segment")
            error = str(item.get("error") or "").strip()
        else:
            title = str(
                getattr(item, "title", "")
                or getattr(item, "segment_id", "")
                or "unknown-segment"
            )
            error = str(getattr(item, "error", "") or "").strip()
        if not error:
            continue
        details.append(f"{title}: {error}")
        if len(details) >= 2:
            break
    return " | ".join(details)
