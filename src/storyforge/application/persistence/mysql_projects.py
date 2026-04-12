from __future__ import annotations

from typing import Any
from uuid import uuid4

from storyforge.application.persistence.mysql_backend import MySQLBackend
from storyforge.application.persistence.mysql_utils import json_dump, json_load
from storyforge.application.projects import ProjectRecord, ProjectStore
from storyforge.application.tasks import utc_now


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
                        json_dump(record.brief),
                        record.created_at,
                        record.updated_at,
                        json_dump(record.task_ids),
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
                        json_dump(record.brief),
                        record.updated_at,
                        json_dump(record.task_ids),
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


def _project_from_row(row: dict[str, Any]) -> ProjectRecord:
    return ProjectRecord(
        project_id=str(row["project_id"]),
        title_hint=str(row["title_hint"]),
        brief=json_load(row["brief_json"], default={}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        task_ids=json_load(row["task_ids_json"], default=[]),
        latest_task_id=str(row["latest_task_id"]) if row.get("latest_task_id") else None,
        story_title=str(row["story_title"]) if row.get("story_title") else None,
        last_output_dir=str(row["last_output_dir"]) if row.get("last_output_dir") else None,
    )
