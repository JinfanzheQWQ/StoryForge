from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from storyforge.core.io import read_json, write_json


TaskStatus = Literal["queued", "running", "completed", "failed"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    project_id: str
    task_type: str
    status: TaskStatus
    payload: dict[str, Any]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=str(raw["task_id"]),
            project_id=str(raw["project_id"]),
            task_type=str(raw["task_type"]),
            status=str(raw["status"]),  # type: ignore[arg-type]
            payload=dict(raw.get("payload", {})),
            created_at=str(raw["created_at"]),
            started_at=str(raw["started_at"]) if raw.get("started_at") else None,
            finished_at=str(raw["finished_at"]) if raw.get("finished_at") else None,
            result=dict(raw["result"]) if isinstance(raw.get("result"), dict) else raw.get("result"),
            error=str(raw["error"]) if raw.get("error") else None,
        )


@dataclass(slots=True)
class QueuedTask:
    task_id: str
    project_id: str
    task_type: str
    payload: dict[str, Any]


TaskHandler = Callable[[QueuedTask], Awaitable[dict[str, Any]]]


class TaskExecutionError(RuntimeError):
    def __init__(self, message: str, result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.result = result


class TaskStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._tasks: dict[str, TaskRecord] = {}
        self._load()

    def create(self, project_id: str, task_type: str, payload: dict[str, Any]) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid4()),
            project_id=project_id,
            task_type=task_type,
            status="queued",
            payload=payload,
            created_at=utc_now(),
        )
        self._tasks[record.task_id] = record
        self._save()
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_many(self, task_ids: Iterable[str]) -> dict[str, TaskRecord]:
        unique_ids = {str(task_id) for task_id in task_ids if task_id}
        return {
            task_id: self._tasks[task_id]
            for task_id in unique_ids
            if task_id in self._tasks
        }

    def list(self, project_id: str | None = None) -> list[TaskRecord]:
        values = self._tasks.values()
        if project_id is not None:
            values = [item for item in values if item.project_id == project_id]
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def list_grouped(self, project_ids: Iterable[str]) -> dict[str, list[TaskRecord]]:
        project_id_set = {str(project_id) for project_id in project_ids if project_id}
        grouped = {project_id: [] for project_id in project_id_set}
        for item in sorted(self._tasks.values(), key=lambda record: record.created_at, reverse=True):
            if item.project_id not in project_id_set:
                continue
            grouped.setdefault(item.project_id, []).append(item)
        return grouped

    def queued_tasks(self) -> list[QueuedTask]:
        return [
            QueuedTask(
                task_id=item.task_id,
                project_id=item.project_id,
                task_type=item.task_type,
                payload=item.payload,
            )
            for item in sorted(self._tasks.values(), key=lambda record: record.created_at)
            if item.status == "queued"
        ]

    def recover_running_tasks(self) -> None:
        changed = False
        for record in self._tasks.values():
            if record.status != "running":
                continue
            # A process restart should not permanently fail a long-running job.
            # Keep partial result data and send it back to the queue so the task
            # can resume from the last persisted stage inputs.
            record.status = "queued"
            record.started_at = None
            record.finished_at = None
            record.error = None
            changed = True
        if changed:
            self._save()

    def mark_running(self, task_id: str) -> None:
        record = self._tasks[task_id]
        record.status = "running"
        record.started_at = utc_now()
        record.finished_at = None
        record.error = None
        self._save()

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        record = self._tasks[task_id]
        record.status = "completed"
        record.result = result
        record.finished_at = utc_now()
        self._save()

    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        record = self._tasks[task_id]
        merged = dict(record.result or {})
        merged.update(result)
        record.result = merged
        self._save()

    def mark_failed(
        self,
        task_id: str,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        record = self._tasks[task_id]
        record.status = "failed"
        record.error = error
        if result is not None:
            record.result = result
        record.finished_at = utc_now()
        self._save()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return

        raw = read_json(self._path)
        if not isinstance(raw, list):
            return

        self._tasks = {
            item["task_id"]: TaskRecord.from_dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("task_id")
        }

    def _save(self) -> None:
        if self._path is None:
            return
        write_json(self._path, list(self._tasks.values()))


class AsyncTaskQueue:
    def __init__(
        self,
        concurrency: int,
        handler: TaskHandler,
        store: TaskStore | None = None,
    ) -> None:
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._store = store or TaskStore()
        self._handler = handler
        self._concurrency = concurrency
        self._workers: list[asyncio.Task[None]] = []

    @property
    def store(self) -> TaskStore:
        return self._store

    async def start(self) -> None:
        if self._workers:
            return
        self._store.recover_running_tasks()
        for task in self._store.queued_tasks():
            await self._queue.put(task)
        for index in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(index)))

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._workers.clear()

    async def submit(self, project_id: str, task_type: str, payload: dict[str, Any]) -> TaskRecord:
        record = self._store.create(project_id=project_id, task_type=task_type, payload=payload)
        await self._queue.put(
            QueuedTask(
                task_id=record.task_id,
                project_id=project_id,
                task_type=task_type,
                payload=payload,
            )
        )
        return record

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            task = await self._queue.get()
            self._store.mark_running(task.task_id)
            try:
                # Pipeline work can be heavy and long-running; keeping it behind
                # an explicit queue makes API requests quick and observable.
                result = await self._handler(task)
            except Exception as exc:
                self._store.mark_failed(task.task_id, str(exc), getattr(exc, "result", None))
            else:
                self._store.mark_completed(task.task_id, result)
            finally:
                self._queue.task_done()
