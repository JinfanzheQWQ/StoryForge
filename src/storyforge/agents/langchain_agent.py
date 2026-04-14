from __future__ import annotations

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

    Designed around LangChain >= 1.2 create_agent API.
    """

    def __init__(
        self,
        model_name: str,
        temperature: float = 0.7,
        provider: str = "deepseek",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.model_name = model_name
        self.temperature = temperature
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
        structured_model = model.with_structured_output(
            schema,
            # Keep structured generation inside LangChain, but avoid
            # create_agent + ToolStrategy's multi-turn tool repair flow.
            # DeepSeek's OpenAI-compatible endpoint is happier with a direct
            # single-turn structured call.
            method="function_calling",
            strict=True,
        )
        structured = structured_model.invoke(
            [
                SystemMessage(content=request.system_prompt),
                HumanMessage(content=request.user_prompt),
            ]
        )
        if isinstance(structured, schema):
            return structured
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
            "timeout": self.timeout_seconds,
        }

        # DeepSeek exposes an OpenAI-compatible API, so we route it through the
        # OpenAI-compatible initializer while preserving a custom base URL.
        if self.base_url:
            kwargs.update(
                {
                    "model_provider": "openai",
                    "base_url": self.base_url,
                    "api_key": self.api_key,
                }
            )

        return init_chat_model(**kwargs)
