from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from storyforge.application.projects import ProjectRecord, ProjectStore
from storyforge.application.tasks import QueuedTask, TaskRecord, TaskStore, utc_now
from storyforge.core.config import DatabaseConfig
from storyforge.core.io import to_jsonable


class MySQLBackend:
    def __init__(self, config: DatabaseConfig) -> None:
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - dependency is optional until DB is enabled
            raise RuntimeError(
                "Database backend requires PyMySQL. Run `uv sync` to install dependencies."
            ) from exc

        self._pymysql = pymysql
        self._config = config
        if self._config.auto_create_schema:
            self.ensure_schema()

    def connect(self):
        return self._connect(use_database=True)

    def ensure_schema(self) -> None:
        database_name = self._quote_identifier(self._config.database)
        charset = self._config.charset

        bootstrap_connection = self._connect(use_database=False)
        try:
            with bootstrap_connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database_name} "
                    f"CHARACTER SET {charset} COLLATE {charset}_unicode_ci"
                )
        finally:
            bootstrap_connection.close()

        schema_connection = self._connect(use_database=True)
        try:
            with schema_connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        project_id VARCHAR(64) PRIMARY KEY,
                        title_hint VARCHAR(255) NOT NULL,
                        brief_json LONGTEXT NOT NULL,
                        created_at VARCHAR(40) NOT NULL,
                        updated_at VARCHAR(40) NOT NULL,
                        task_ids_json LONGTEXT NOT NULL,
                        latest_task_id VARCHAR(64) NULL,
                        story_title VARCHAR(255) NULL,
                        last_output_dir TEXT NULL,
                        INDEX idx_projects_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id VARCHAR(64) PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL,
                        task_type VARCHAR(120) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        payload_json LONGTEXT NOT NULL,
                        created_at VARCHAR(40) NOT NULL,
                        started_at VARCHAR(40) NULL,
                        finished_at VARCHAR(40) NULL,
                        result_json LONGTEXT NULL,
                        error_text TEXT NULL,
                        INDEX idx_tasks_project_created (project_id, created_at),
                        INDEX idx_tasks_status_created (status, created_at),
                        CONSTRAINT fk_tasks_project
                            FOREIGN KEY (project_id) REFERENCES projects(project_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
        finally:
            schema_connection.close()

    def _connect(self, use_database: bool):
        params: dict[str, Any] = {
            "host": self._config.host,
            "port": self._config.port,
            "user": self._config.user,
            "password": self._config.resolved_password(),
            "charset": self._config.charset,
            "autocommit": True,
            "connect_timeout": self._config.connect_timeout_seconds,
            "cursorclass": self._pymysql.cursors.DictCursor,
        }
        if use_database:
            params["database"] = self._config.database
        return self._pymysql.connect(**params)

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return f"`{value.replace('`', '``')}`"


class MySQLProjectStore(ProjectStore):
    def __init__(self, backend: MySQLBackend) -> None:
        self._backend = backend

    def create(self, brief: dict[str, Any]) -> ProjectRecord:
        now = utc_now()
        record = ProjectRecord(
            project_id=str(uuid4()),
            title_hint=str(brief.get("title_hint", "未命名故事")),
            brief=dict(brief),
            created_at=now,
            updated_at=now,
        )
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (
                        project_id,
                        title_hint,
                        brief_json,
                        created_at,
                        updated_at,
                        task_ids_json,
                        latest_task_id,
                        story_title,
                        last_output_dir
                    ) VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL, NULL)
                    """,
                    (
                        record.project_id,
                        record.title_hint,
                        _json_dump(record.brief),
                        record.created_at,
                        record.updated_at,
                        _json_dump(record.task_ids),
                    ),
                )
        finally:
            connection.close()
        return record

    def get(self, project_id: str) -> ProjectRecord | None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_id,
                        title_hint,
                        brief_json,
                        created_at,
                        updated_at,
                        task_ids_json,
                        latest_task_id,
                        story_title,
                        last_output_dir
                    FROM projects
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _project_from_row(row) if row else None

    def list(self) -> list[ProjectRecord]:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_id,
                        title_hint,
                        brief_json,
                        created_at,
                        updated_at,
                        task_ids_json,
                        latest_task_id,
                        story_title,
                        last_output_dir
                    FROM projects
                    ORDER BY updated_at DESC
                    """
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_project_from_row(row) for row in rows]

    def attach_task(
        self,
        project_id: str,
        task_id: str,
        brief: dict[str, Any],
    ) -> ProjectRecord:
        connection = self._backend.connect()
        try:
            connection.begin()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_id,
                        title_hint,
                        brief_json,
                        created_at,
                        updated_at,
                        task_ids_json,
                        latest_task_id,
                        story_title,
                        last_output_dir
                    FROM projects
                    WHERE project_id = %s
                    FOR UPDATE
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(project_id)
                record = _project_from_row(row)
                if task_id not in record.task_ids:
                    record.task_ids.append(task_id)
                record.latest_task_id = task_id
                record.updated_at = utc_now()
                if brief:
                    record.brief = dict(brief)
                    record.title_hint = str(brief.get("title_hint", record.title_hint))
                cursor.execute(
                    """
                    UPDATE projects
                    SET
                        title_hint = %s,
                        brief_json = %s,
                        updated_at = %s,
                        task_ids_json = %s,
                        latest_task_id = %s
                    WHERE project_id = %s
                    """,
                    (
                        record.title_hint,
                        _json_dump(record.brief),
                        record.updated_at,
                        _json_dump(record.task_ids),
                        record.latest_task_id,
                        record.project_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return record

    def mark_task_result(
        self,
        project_id: str,
        task_id: str,
        result: dict[str, Any],
    ) -> None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE projects
                    SET
                        latest_task_id = %s,
                        updated_at = %s,
                        story_title = COALESCE(%s, story_title),
                        last_output_dir = COALESCE(%s, last_output_dir)
                    WHERE project_id = %s
                    """,
                    (
                        task_id,
                        utc_now(),
                        str(result["story_title"]) if result.get("story_title") else None,
                        str(result["output_dir"]) if result.get("output_dir") else None,
                        project_id,
                    ),
                )
        finally:
            connection.close()


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
                        _json_dump(record.payload),
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
                payload=_json_load(row["payload_json"], default={}),
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
                        status = 'failed',
                        error_text = %s,
                        finished_at = %s
                    WHERE status = 'running'
                    """,
                    ("Task was interrupted by a service restart.", utc_now()),
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
            (_json_dump(result), utc_now(), task_id),
        )

    def update_result(self, task_id: str, result: dict[str, Any]) -> None:
        record = self.get(task_id)
        merged = dict(record.result or {}) if record else {}
        merged.update(result)
        self._update_task(
            """
            UPDATE tasks
            SET result_json = %s
            WHERE task_id = %s
            """,
            (_json_dump(merged), task_id),
        )

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
            (_json_dump(result), error, utc_now(), task_id),
        )

    def _update_task(self, sql: str, params: tuple[Any, ...]) -> None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
        finally:
            connection.close()


def _project_from_row(row: dict[str, Any]) -> ProjectRecord:
    return ProjectRecord(
        project_id=str(row["project_id"]),
        title_hint=str(row["title_hint"]),
        brief=_json_load(row["brief_json"], default={}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        task_ids=_json_load(row["task_ids_json"], default=[]),
        latest_task_id=str(row["latest_task_id"]) if row.get("latest_task_id") else None,
        story_title=str(row["story_title"]) if row.get("story_title") else None,
        last_output_dir=str(row["last_output_dir"]) if row.get("last_output_dir") else None,
    )


def _task_from_row(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord(
        task_id=str(row["task_id"]),
        project_id=str(row["project_id"]),
        task_type=str(row["task_type"]),
        status=str(row["status"]),
        payload=_json_load(row["payload_json"], default={}),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row.get("started_at") else None,
        finished_at=str(row["finished_at"]) if row.get("finished_at") else None,
        result=_json_load(row["result_json"], default=None),
        error=str(row["error_text"]) if row.get("error_text") else None,
    )


def _json_dump(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)
