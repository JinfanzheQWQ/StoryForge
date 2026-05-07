from __future__ import annotations

from typing import Any
from uuid import uuid4

from storyforge.application.agent_sessions import (
    AgentMessageRecord,
    AgentSessionEventRecord,
    AgentSessionRecord,
    AgentSessionStore,
)
from storyforge.application.persistence.mysql_backend import MySQLBackend
from storyforge.application.persistence.mysql_utils import json_dump, json_load
from storyforge.application.tasks import utc_now


class MySQLAgentSessionStore(AgentSessionStore):
    def __init__(self, backend: MySQLBackend) -> None:
        self._backend = backend

    def create_session(
        self,
        *,
        product_type: str,
        mode: str,
        status: str,
        current_stage: str,
        settings: dict[str, Any] | None = None,
    ) -> AgentSessionRecord:
        now = utc_now()
        record = AgentSessionRecord(
            session_id=str(uuid4()),
            product_type=product_type,
            mode=mode,
            status=status,
            current_stage=current_stage,
            user_prompt="",
            intent={},
            plan={},
            settings=dict(settings or {}),
            result={},
            created_at=now,
            updated_at=now,
        )
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_sessions (
                        session_id,
                        project_id,
                        source_task_id,
                        current_task_id,
                        product_type,
                        mode,
                        status,
                        current_stage,
                        user_prompt,
                        intent_json,
                        plan_json,
                        settings_json,
                        result_json,
                        error_text,
                        created_at,
                        updated_at,
                        finished_at
                    ) VALUES (%s, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, NULL)
                    """,
                    (
                        record.session_id,
                        record.product_type,
                        record.mode,
                        record.status,
                        record.current_stage,
                        record.user_prompt,
                        json_dump(record.intent),
                        json_dump(record.plan),
                        json_dump(record.settings),
                        json_dump(record.result),
                        record.created_at,
                        record.updated_at,
                    ),
                )
        finally:
            connection.close()
        return record

    def get_session(self, session_id: str) -> AgentSessionRecord | None:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        session_id,
                        project_id,
                        source_task_id,
                        current_task_id,
                        product_type,
                        mode,
                        status,
                        current_stage,
                        user_prompt,
                        intent_json,
                        plan_json,
                        settings_json,
                        result_json,
                        error_text,
                        created_at,
                        updated_at,
                        finished_at
                    FROM agent_sessions
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        return _session_from_row(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[AgentSessionRecord]:
        safe_limit = max(1, min(int(limit or 50), 200))
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        session_id,
                        project_id,
                        source_task_id,
                        current_task_id,
                        product_type,
                        mode,
                        status,
                        current_stage,
                        user_prompt,
                        intent_json,
                        plan_json,
                        settings_json,
                        result_json,
                        error_text,
                        created_at,
                        updated_at,
                        finished_at
                    FROM agent_sessions
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT %s
                    """,
                    (safe_limit,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_session_from_row(row) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM agent_sessions WHERE session_id = %s",
                    (session_id,),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def update_session(self, session_id: str, **updates: Any) -> AgentSessionRecord:
        if not updates:
            record = self.get_session(session_id)
            if record is None:
                raise KeyError(session_id)
            return record

        allowed = {
            "project_id": "project_id",
            "source_task_id": "source_task_id",
            "current_task_id": "current_task_id",
            "status": "status",
            "current_stage": "current_stage",
            "user_prompt": "user_prompt",
            "intent": "intent_json",
            "plan": "plan_json",
            "settings": "settings_json",
            "result": "result_json",
            "error": "error_text",
            "finished_at": "finished_at",
        }
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            column = allowed[key]
            if key in {"intent", "plan", "settings", "result"}:
                value = json_dump(value or {})
            assignments.append(f"{column} = %s")
            params.append(value)
        assignments.append("updated_at = %s")
        params.append(utc_now())
        params.append(session_id)

        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE agent_sessions
                    SET {", ".join(assignments)}
                    WHERE session_id = %s
                    """,
                    tuple(params),
                )
        finally:
            connection.close()
        record = self.get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        return record

    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        type: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessageRecord:
        record = AgentMessageRecord(
            message_id=str(uuid4()),
            session_id=session_id,
            role=role,
            type=type,
            content=content,
            payload=dict(payload or {}),
            created_at=utc_now(),
        )
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_session_messages (
                        message_id,
                        session_id,
                        role,
                        type,
                        content,
                        payload_json,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.message_id,
                        record.session_id,
                        record.role,
                        record.type,
                        record.content,
                        json_dump(record.payload),
                        record.created_at,
                    ),
                )
        finally:
            connection.close()
        return record

    def list_messages(self, session_id: str) -> list[AgentMessageRecord]:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        message_id,
                        session_id,
                        role,
                        type,
                        content,
                        payload_json,
                        created_at
                    FROM agent_session_messages
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_message_from_row(row) for row in rows]

    def append_event(
        self,
        *,
        session_id: str,
        stage: str,
        status: str,
        message: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentSessionEventRecord:
        record = AgentSessionEventRecord(
            event_id=str(uuid4()),
            session_id=session_id,
            stage=stage,
            status=status,
            message=message,
            task_id=task_id,
            payload=dict(payload or {}),
            created_at=utc_now(),
        )
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_session_events (
                        event_id,
                        session_id,
                        stage,
                        status,
                        message,
                        task_id,
                        payload_json,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.event_id,
                        record.session_id,
                        record.stage,
                        record.status,
                        record.message,
                        record.task_id,
                        json_dump(record.payload),
                        record.created_at,
                    ),
                )
        finally:
            connection.close()
        return record

    def list_events(self, session_id: str) -> list[AgentSessionEventRecord]:
        connection = self._backend.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        event_id,
                        session_id,
                        stage,
                        status,
                        message,
                        task_id,
                        payload_json,
                        created_at
                    FROM agent_session_events
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [_event_from_row(row) for row in rows]


def _session_from_row(row: dict[str, Any]) -> AgentSessionRecord:
    return AgentSessionRecord(
        session_id=str(row["session_id"]),
        project_id=str(row["project_id"]) if row.get("project_id") else None,
        source_task_id=str(row["source_task_id"]) if row.get("source_task_id") else None,
        current_task_id=str(row["current_task_id"]) if row.get("current_task_id") else None,
        product_type=str(row["product_type"]),
        mode=str(row["mode"]),
        status=str(row["status"]),
        current_stage=str(row["current_stage"]),
        user_prompt=str(row.get("user_prompt") or ""),
        intent=json_load(row.get("intent_json"), default={}),
        plan=json_load(row.get("plan_json"), default={}),
        settings=json_load(row.get("settings_json"), default={}),
        result=json_load(row.get("result_json"), default={}),
        error=str(row["error_text"]) if row.get("error_text") else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=str(row["finished_at"]) if row.get("finished_at") else None,
    )


def _message_from_row(row: dict[str, Any]) -> AgentMessageRecord:
    return AgentMessageRecord(
        message_id=str(row["message_id"]),
        session_id=str(row["session_id"]),
        role=str(row["role"]),
        type=str(row["type"]),
        content=str(row["content"]),
        payload=json_load(row.get("payload_json"), default={}),
        created_at=str(row["created_at"]),
    )


def _event_from_row(row: dict[str, Any]) -> AgentSessionEventRecord:
    return AgentSessionEventRecord(
        event_id=str(row["event_id"]),
        session_id=str(row["session_id"]),
        stage=str(row["stage"]),
        status=str(row["status"]),
        message=str(row["message"]),
        task_id=str(row["task_id"]) if row.get("task_id") else None,
        payload=json_load(row.get("payload_json"), default={}),
        created_at=str(row["created_at"]),
    )
