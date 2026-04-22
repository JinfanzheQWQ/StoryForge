from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar


@dataclass(slots=True)
class PromptRequest:
    system_prompt: str
    user_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


def attach_prompt_metrics(
    request: PromptRequest,
    *,
    soft_limit_chars: int | None = None,
) -> PromptRequest:
    system_prompt_chars = len(request.system_prompt)
    user_prompt_chars = len(request.user_prompt)
    total_prompt_chars = system_prompt_chars + user_prompt_chars
    request.metadata.update(
        {
            "system_prompt_chars": system_prompt_chars,
            "user_prompt_chars": user_prompt_chars,
            "total_prompt_chars": total_prompt_chars,
        }
    )
    if soft_limit_chars is not None:
        exceeded = total_prompt_chars > soft_limit_chars
        request.metadata.update(
            {
                "prompt_soft_limit_chars": soft_limit_chars,
                "prompt_soft_limit_exceeded": exceeded,
                "prompt_size_status": "warn" if exceeded else "ok",
            }
        )
        if exceeded:
            request.metadata["prompt_warning"] = (
                f"prompt length {total_prompt_chars} exceeds soft limit {soft_limit_chars}"
            )
    return request


@dataclass(slots=True)
class AgentResult:
    content: str
    provider: str
    raw: Any = None


StructuredT = TypeVar("StructuredT")


class AgentBackend(Protocol):
    def generate(self, request: PromptRequest) -> AgentResult:
        """Generate a text response from an agent backend."""

    def generate_structured(self, request: PromptRequest, schema: type[StructuredT]) -> StructuredT:
        """Generate a structured response validated against the given schema."""


class AgentBackendUnavailableError(RuntimeError):
    """Raised when no live LLM backend is configured for runtime execution."""


class UnavailableAgentBackend:
    def __init__(self, message: str = "LLM backend is unavailable.") -> None:
        self.message = message

    def generate(self, request: PromptRequest) -> AgentResult:
        raise AgentBackendUnavailableError(self.message)

    def generate_structured(self, request: PromptRequest, schema: type[StructuredT]) -> StructuredT:
        raise AgentBackendUnavailableError(self.message)
