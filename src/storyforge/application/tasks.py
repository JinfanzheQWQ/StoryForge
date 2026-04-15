from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal

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


class TaskStore(ABC):
    @abstractmethod
    def create(self, project_id: str, task_type: str, payload: dict[str, Any]) -> TaskRecord:
        raise NotImplementedError

    @abstractmethod
    def get(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_many(self, task_ids: Iterable[str]) -> dict[str, TaskRecord]:
        raise NotImplementedError

    @abstractmethod
    def list(self, project_id: str | None = None) -> list[TaskRecord]:
        raise NotImplementedError

    @abstractmethod
    def delete_project_tasks(self, project_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_grouped(self, project_ids: Iterable[str]) -> dict[str, list[TaskRecord]]:
        raise NotImplementedError

    @abstractmethod
    def queued_tasks(self) -> list[QueuedTask]:
        raise NotImplementedError

    @abstractmethod
    def recover_running_tasks(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_running(self, task_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_failed(
        self,
        task_id: str,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError


class AsyncTaskQueue:
    def __init__(
        self,
        concurrency: int,
        handler: TaskHandler,
        store: TaskStore,
    ) -> None:
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._store = store
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
