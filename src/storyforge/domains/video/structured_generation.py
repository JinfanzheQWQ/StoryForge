from __future__ import annotations

from typing import Callable, TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackendUnavailableError,
    PromptRequest,
    attach_prompt_metrics,
)
from storyforge.domains.video.errors import VideoStructuredGenerationError


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class VideoStructuredGenerationMixin:
    """Runs structured LLM calls with retry, validation, and response coercion."""

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT] | None = None,
    ) -> StructuredModelT:
        attempts = self.structured_retry_attempts
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=attempts,
            validator=validator,
            request_builder=self._build_retry_request,
            response_coercer=self._coerce_structured_response,
            failure_builder=lambda last_error: VideoStructuredGenerationError(
                task=str(request.metadata.get("task", "structured-agent")),
                schema_name=schema.__name__,
                attempts=attempts,
                cause=last_error or RuntimeError("unknown structured generation failure"),
                metadata=dict(request.metadata),
            ),
        )

    def _run_strict_structured_agent(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT],
        attempts: int = 3,
    ) -> StructuredModelT:
        total_attempts = max(1, attempts)
        task_name = str(request.metadata.get("task", "structured-repair"))
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=total_attempts,
            validator=validator,
            request_builder=self._build_repair_retry_request,
            response_coercer=self._validate_structured_response,
            failure_builder=lambda last_error: RuntimeError(
                f"Structured repair failed for task={task_name} schema={schema.__name__} "
                f"after {total_attempts} attempts: {last_error or 'unknown error'}"
            ),
        )

    def _execute_structured_request(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        attempts: int,
        validator: Callable[[StructuredModelT], StructuredModelT] | None,
        request_builder: Callable[..., PromptRequest],
        response_coercer: Callable[[object, type[StructuredModelT]], StructuredModelT],
        failure_builder: Callable[[Exception | None], Exception],
    ) -> StructuredModelT:
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            attempt_request = request_builder(
                request=request,
                schema=schema,
                attempt=attempt,
                last_error=last_error,
            )
            attempt_request = attach_prompt_metrics(attempt_request)
            request.metadata.update(
                {
                    "system_prompt_chars": attempt_request.metadata["system_prompt_chars"],
                    "user_prompt_chars": attempt_request.metadata["user_prompt_chars"],
                    "total_prompt_chars": attempt_request.metadata["total_prompt_chars"],
                }
            )
            try:
                response = self.backend.generate_structured(attempt_request, schema)
                candidate = response_coercer(response, schema)
                if validator is not None:
                    return validator(candidate)
                return candidate
            except AgentBackendUnavailableError:
                raise
            except Exception as exc:
                last_error = exc
        raise failure_builder(last_error)

    def _coerce_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        if response is None:
            raise RuntimeError(
                f"模型没有返回 {schema.__name__} 结构化对象；"
                "可能是本轮没有触发 tool call，也没有返回可解析 JSON。"
            )
        return schema.model_validate(response)

    def _validate_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        return schema.model_validate(response)
