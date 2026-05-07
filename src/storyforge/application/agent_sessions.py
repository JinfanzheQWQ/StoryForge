from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


AgentSessionStatus = Literal[
    "created",
    "planning",
    "waiting_confirmation",
    "running",
    "waiting_task",
    "completed",
    "failed",
    "paused",
    "canceled",
]

AgentMessageRole = Literal["user", "assistant", "system"]
AgentMessageType = Literal["text", "plan", "progress", "error", "result", "action"]


@dataclass(slots=True)
class AgentSessionRecord:
    session_id: str
    product_type: str
    mode: str
    status: str
    current_stage: str
    user_prompt: str
    intent: dict[str, Any]
    plan: dict[str, Any]
    settings: dict[str, Any]
    result: dict[str, Any]
    created_at: str
    updated_at: str
    project_id: str | None = None
    source_task_id: str | None = None
    current_task_id: str | None = None
    error: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class AgentMessageRecord:
    message_id: str
    session_id: str
    role: str
    type: str
    content: str
    payload: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class AgentSessionEventRecord:
    event_id: str
    session_id: str
    stage: str
    status: str
    message: str
    payload: dict[str, Any]
    created_at: str
    task_id: str | None = None


class AgentSessionStore(ABC):
    @abstractmethod
    def create_session(
        self,
        *,
        product_type: str,
        mode: str,
        status: str,
        current_stage: str,
        settings: dict[str, Any] | None = None,
    ) -> AgentSessionRecord:
        raise NotImplementedError

    @abstractmethod
    def get_session(self, session_id: str) -> AgentSessionRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, limit: int = 50) -> list[AgentSessionRecord]:
        raise NotImplementedError

    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def update_session(
        self,
        session_id: str,
        **updates: Any,
    ) -> AgentSessionRecord:
        raise NotImplementedError

    @abstractmethod
    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        type: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessageRecord:
        raise NotImplementedError

    @abstractmethod
    def list_messages(self, session_id: str) -> list[AgentMessageRecord]:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def list_events(self, session_id: str) -> list[AgentSessionEventRecord]:
        raise NotImplementedError
