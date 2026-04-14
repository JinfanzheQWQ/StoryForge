from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from storyforge.application.persistence.mysql_backend import MySQLBackend
from storyforge.application.persistence.mysql_utils import json_dump, json_load
from storyforge.application.tasks import QueuedTask, TaskRecord, TaskStore, utc_now


class MySQLTaskStore(TaskStore):
    def __init__(self, backend: MySQLBackend) -> None:
        self._backend = backend

    def create(self, project_id: str, task_type: str, payload: dict[str, Any]) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid4()),
            project_id=project_id,
            task_type=task_type,
            status="queued",
            payload=payload,
            created_at=utc_now(),
        )
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tasks (
                        task_id,
                        project_id,
                        task_type,
                        status,
                        payload_json,
                        created_at,
                        started_at,
                        finished_at,
                        result_json,
                        error_text
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL)
                    """,
                    (
                        record.task_id,
                        record.project_id,
                        record.task_type,
                        record.status,
                        json_dump(record.payload),
                        record.created_at,
                    ),
                )
        finally:
            connection.close()
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        task_id,
                        project_id,
                        task_type,
                        status,
                        payload_json,
                        created_at,
                        started_at,
                        finished_at,
                        result_json,
                        error_text
                    FROM tasks
                    WHERE task_id = %s
                    """,
                    (task_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _task_from_row(row) if row else None

    def get_many(self, task_ids: Iterable[str]) -> dict[str, TaskRecord]:
        unique_ids = _unique_values(task_ids)
        if not unique_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(unique_ids))
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        task_id,
                        project_id,
                        task_type,
                        status,
                        payload_json,
                        created_at,
                        started_at,
                        finished_at,
                        result_json,
                        error_text
                    FROM tasks
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(unique_ids),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        records = [_task_from_row(row) for row in rows]
        return {record.task_id: record for record in records}

    def list(self, project_id: str | None = None) -> list[TaskRecord]:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                if project_id is None:
                    cursor.execute(
                        """
                        SELECT
                            task_id,
                            project_id,
                            task_type,
                            status,
                            payload_json,
                            created_at,
                            started_at,
                            finished_at,
                            result_json,
                            error_text
                        FROM tasks
                        ORDER BY created_at DESC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            task_id,
                            project_id,
                            task_type,
                            status,
                            payload_json,
                            created_at,
                            started_at,
                            finished_at,
                            result_json,
                            error_text
                        FROM tasks
                        WHERE project_id = %s
                        ORDER BY created_at DESC
                        """,
                        (project_id,),
                    )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_task_from_row(row) for row in rows]

    def delete_project_tasks(self, project_id: str) -> int:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tasks WHERE project_id = %s",
                    (project_id,),
                )
                return int(cursor.rowcount)
        finally:
            connection.close()

    def list_grouped(self, project_ids: Iterable[str]) -> dict[str, list[TaskRecord]]:
        unique_ids = _unique_values(project_ids)
        if not unique_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(unique_ids))
        grouped = {project_id: [] for project_id in unique_ids}
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        task_id,
                        project_id,
                        task_type,
                        status,
                        payload_json,
                        created_at,
                        started_at,
                        finished_at,
                        result_json,
                        error_text
                    FROM tasks
                    WHERE project_id IN ({placeholders})
                    ORDER BY created_at DESC
                    """,
                    tuple(unique_ids),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        for row in rows:
            record = _task_from_row(row)
            grouped.setdefault(record.project_id, []).append(record)
        return grouped

    def queued_tasks(self) -> list[QueuedTask]:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        task_id,
                        project_id,
                        task_type,
                        status,
                        payload_json,
                        created_at,
                        started_at,
                        finished_at,
                        result_json,
                        error_text
                    FROM tasks
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    """
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [
            QueuedTask(
                task_id=str(row["task_id"]),
                project_id=str(row["project_id"]),
                task_type=str(row["task_type"]),
                payload=json_load(row["payload_json"], default={}),
            )
            for row in rows
        ]

    def recover_running_tasks(self) -> None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tasks
                    SET
                        status = 'queued',
                        started_at = NULL,
                        finished_at = NULL,
                        error_text = NULL
                    WHERE status = 'running'
                    """,
                )
        finally:
            connection.close()

    def mark_running(self, task_id: str) -> None:
        self._update_task(
            """
            UPDATE tasks
            SET status = 'running', started_at = %s, finished_at = NULL, error_text = NULL
            WHERE task_id = %s
            """,
            (utc_now(), task_id),
        )

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        self._update_task(
            """
            UPDATE tasks
            SET status = 'completed', result_json = %s, finished_at = %s, error_text = NULL
            WHERE task_id = %s
            """,
            (json_dump(result), utc_now(), task_id),
        )

    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        connection = self._backend.connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT result_json
                    FROM tasks
                    WHERE task_id = %s
                    FOR UPDATE
                    """,
                    (task_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(task_id)
                merged = dict(json_load(row["result_json"], default={}) or {})
                merged.update(result)
                cursor.execute(
                    """
                    UPDATE tasks
                    SET result_json = %s
                    WHERE task_id = %s
                    """,
                    (json_dump(merged), task_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_failed(
        self,
        task_id: str,
        error: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        if result is None:
            self._update_task(
                """
                UPDATE tasks
                SET status = 'failed', error_text = %s, finished_at = %s
                WHERE task_id = %s
                """,
                (error, utc_now(), task_id),
            )
            return

        self._update_task(
            """
            UPDATE tasks
            SET status = 'failed', result_json = %s, error_text = %s, finished_at = %s
            WHERE task_id = %s
            """,
            (json_dump(result), error, utc_now(), task_id),
        )

    def _update_task(self, sql: str, params: tuple[Any, ...]) -> None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
        finally:
            connection.close()


def _task_from_row(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        task_id=str(row["task_id"]),
        project_id=str(row["project_id"]),
        task_type=str(row["task_type"]),
        status=str(row["status"]),
        payload=json_load(row["payload_json"], default={}),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row.get("started_at") else None,
        finished_at=str(row["finished_at"]) if row.get("finished_at") else None,
        result=json_load(row["result_json"], default=None),
        error=str(row["error_text"]) if row.get("error_text") else None,
    )


def _unique_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
