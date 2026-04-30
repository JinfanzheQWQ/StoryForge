from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel
from storyforge.agents.base import AgentBackend, AgentResult, PromptRequest


def _message_to_text(message: Any) -> str:
    if isinstance(message, str):
        return message

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", message)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, str):
                fragments.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    fragments.append(str(text))
        return "\n".join(fragments).strip()

    return str(content if content is not None else message)


class LangChainTextAgentBackend(AgentBackend):
    """
    Minimal LangChain backend.

    Uses LangChain >= 1.2 in two modes:
    - plain text generation via create_agent()
    - structured generation via ChatModel.with_structured_output()
    """

    def __init__(
        self,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        provider: str = "deepseek",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max(256, int(max_tokens))
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def generate(self, request: PromptRequest) -> AgentResult:
        from langchain.agents import create_agent

        model = self._build_model()
        agent = create_agent(
            model=model,
            tools=[],
            system_prompt=request.system_prompt,
        )
        raw = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": request.user_prompt,
                    }
                ]
            }
        )
        content = self._extract_text(raw)
        return AgentResult(content=content, provider="langchain", raw=raw)

    def generate_structured(self, request: PromptRequest, schema: type[BaseModel]) -> BaseModel:
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self._build_model()
        messages = [
            SystemMessage(content=request.system_prompt),
            HumanMessage(content=request.user_prompt),
        ]
        method = self._structured_output_method()
        structured_model = model.with_structured_output(
            schema,
            # Provider-specific structured strategy:
            # - DeepSeek OpenAI-style endpoints are more stable with
            #   function_calling than full Structured Outputs.
            # - OpenAI GPT structured calls should use json_schema to avoid
            #   chat-completions tool_choice conflicts on GPT-5.x.
            method=method,
            include_raw=True,
            strict=True,
        )
        structured = structured_model.invoke(messages)
        if isinstance(structured, dict) and "parsed" in structured:
            parsed = structured.get("parsed")
            if parsed is not None:
                return parsed if isinstance(parsed, schema) else schema.model_validate(parsed)

            raw = structured.get("raw")
            raw_text = _message_to_text(raw).strip()
            raw_json = self._extract_json_object(raw_text)
            if raw_json is not None:
                return schema.model_validate(raw_json)

            parsing_error = structured.get("parsing_error")
            raw_summary = self._summarize_structured_raw(raw, raw_text)
            fallback_error: Exception | None = None
            try:
                return self._invoke_plain_json_fallback(
                    model=model,
                    request=request,
                    schema=schema,
                )
            except Exception as exc:
                fallback_error = exc

            fallback_note = f" plain_json_fallback_error={fallback_error!s}." if fallback_error else ""
            if parsing_error is not None:
                raise RuntimeError(
                    f"LangChain structured parsing failed for schema={schema.__name__}: "
                    f"{parsing_error}. {raw_summary}.{fallback_note}"
                )
            raise RuntimeError(
                f"LangChain structured output was empty for schema={schema.__name__}: "
                "the model did not return a tool call or valid JSON. "
                f"{raw_summary}.{fallback_note}"
            )
        if isinstance(structured, schema):
            return structured
        if structured is None:
            try:
                return self._invoke_plain_json_fallback(
                    model=model,
                    request=request,
                    schema=schema,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"LangChain structured output was empty for schema={schema.__name__}: "
                    "the model returned None. "
                    f"plain_json_fallback_error={exc!s}"
                ) from exc
        return schema.model_validate(structured)

    def _extract_text(self, raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            if "output" in raw:
                return str(raw["output"])
            messages = raw.get("messages")
            if isinstance(messages, list) and messages:
                return _message_to_text(messages[-1])
        return str(raw)

    def _build_model(self) -> Any:
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as exc:  # pragma: no cover - optional runtime dependency
            raise RuntimeError(
                "LangChain is not installed. Run `uv sync` before using --llm mode."
            ) from exc

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout_seconds,
        }

        # DeepSeek exposes an OpenAI-style API, so we route it through the
        # OpenAI initializer while preserving a custom base URL.
        if self.base_url:
            kwargs.update(
                {
                    "model_provider": "openai",
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                }
            )

        return init_chat_model(**kwargs)

    def _structured_output_method(self) -> str:
        if self.provider == "openai":
            return "json_schema"
        return "function_calling"

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None

        normalized = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", normalized, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            normalized = fenced.group(1).strip()

        candidates = [normalized]
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start >= 0 and end > start:
            candidates.append(normalized[start : end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _summarize_structured_raw(self, raw: Any, raw_text: str) -> str:
        content = " ".join(raw_text.split())
        if len(content) > 500:
            content = content[:500] + "..."

        tool_calls = getattr(raw, "tool_calls", None)
        if tool_calls is None:
            additional_kwargs = getattr(raw, "additional_kwargs", {})
            if isinstance(additional_kwargs, dict):
                tool_calls = additional_kwargs.get("tool_calls")
        tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        response_metadata = getattr(raw, "response_metadata", {})
        finish_reason = ""
        if isinstance(response_metadata, dict):
            finish_reason = str(response_metadata.get("finish_reason", "") or "")
        return (
            f"raw_content={content!r}; tool_call_count={tool_count}; "
            f"finish_reason={finish_reason!r}"
        )

    def _invoke_plain_json_fallback(
        self,
        *,
        model: Any,
        request: PromptRequest,
        schema: type[BaseModel],
    ) -> BaseModel:
        from langchain_core.messages import HumanMessage, SystemMessage

        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        request.system_prompt
                        + "\n\n"
                        + "上一次结构化返回为空或不可解析。"
                        + "现在不要使用 tool call，不要输出解释，不要输出 Markdown。"
                        + "你必须只返回一个合法 JSON object，且字段严格符合给定 schema。"
                    )
                ),
                HumanMessage(
                    content=(
                        request.user_prompt
                        + "\n\n请只返回一个 JSON object。目标 schema 如下：\n"
                        + schema_json
                    )
                ),
            ]
        )
        raw_text = _message_to_text(response).strip()
        raw_json = self._extract_json_object(raw_text)
        if raw_json is None:
            raise RuntimeError(
                "plain JSON fallback did not return a valid JSON object. "
                + self._summarize_structured_raw(response, raw_text)
            )
        return schema.model_validate(raw_json)
