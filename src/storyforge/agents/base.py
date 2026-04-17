from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar


@dataclass(slots=True)
class PromptRequest:
    system_prompt: str
    user_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


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
