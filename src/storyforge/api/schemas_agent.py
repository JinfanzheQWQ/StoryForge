from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AgentSessionCreateRequest(BaseModel):
    product_type: Literal["novel_to_video"] = "novel_to_video"
    mode: Literal["auto_full_pipeline"] = "auto_full_pipeline"
    settings: dict[str, Any] = Field(default_factory=dict)


class AgentMessageCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_content(self) -> "AgentMessageCreateRequest":
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("消息内容不能为空。")
        return self


class AgentMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    type: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentSessionEventResponse(BaseModel):
    event_id: str
    session_id: str
    stage: str
    status: str
    message: str
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentSessionProgressResponse(BaseModel):
    completed_steps: int = 0
    total_steps: int = 9
    percent: int = 0


class AgentSessionResponse(BaseModel):
    session_id: str
    project_id: str | None = None
    source_task_id: str | None = None
    current_task_id: str | None = None
    product_type: str
    mode: str
    status: str
    current_stage: str
    user_prompt: str = ""
    intent: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    progress: AgentSessionProgressResponse = Field(default_factory=AgentSessionProgressResponse)
    created_at: str
    updated_at: str
    finished_at: str | None = None


class AgentSessionDeletedResponse(BaseModel):
    session_id: str
    deleted: bool
    project_id: str | None = None
    project_deleted: bool = False


class AgentSessionWithMessagesResponse(BaseModel):
    session: AgentSessionResponse
    messages: list[AgentMessageResponse] = Field(default_factory=list)


class AgentSessionsResponse(BaseModel):
    sessions: list[AgentSessionResponse] = Field(default_factory=list)


class AgentMessagesResponse(BaseModel):
    messages: list[AgentMessageResponse] = Field(default_factory=list)


class AgentSessionEventsResponse(BaseModel):
    events: list[AgentSessionEventResponse] = Field(default_factory=list)
