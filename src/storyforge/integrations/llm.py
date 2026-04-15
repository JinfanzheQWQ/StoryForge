from __future__ import annotations

import os
from dataclasses import replace

from storyforge.agents.base import AgentBackend, AgentBackendUnavailableError
from storyforge.agents.langchain_agent import LangChainTextAgentBackend
from storyforge.core.config import AppConfig

DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"


def build_agent_backend(
    config: AppConfig,
    use_llm: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> AgentBackend:
    enabled = use_llm or config.llm.enabled
    if not enabled:
        raise AgentBackendUnavailableError(
            "Live LLM mode is required. Non-LLM DryRun mode has been removed. "
            "Enable [llm].enabled in config or keep use_llm=true."
        )

    resolved_llm = _resolve_llm_config(config, provider=provider, model=model)
    api_key = os.getenv(resolved_llm.api_key_env)
    if not api_key:
        raise AgentBackendUnavailableError(
            f"Missing required API key env: {resolved_llm.api_key_env}. "
            f"Configure {resolved_llm.provider} credentials before running StoryForge."
        )

    return LangChainTextAgentBackend(
        model_name=resolved_llm.model,
        temperature=resolved_llm.temperature,
        provider=resolved_llm.provider,
        base_url=_resolve_base_url(resolved_llm),
        api_key=api_key,
        timeout_seconds=resolved_llm.timeout_seconds,
    )


def _resolve_llm_config(
    config: AppConfig,
    *,
    provider: str | None,
    model: str | None,
):
    resolved_provider = str(provider or config.llm.provider).strip().lower()
    if resolved_provider == "deepseek":
        resolved = replace(
            config.llm,
            provider="deepseek",
            model=str(model or config.llm.model or "deepseek-chat").strip() or "deepseek-chat",
            api_key_env="DEEPSEEK_API_KEY",
            base_url=config.llm.base_url or "https://api.deepseek.com/v1",
        )
        return resolved
    if resolved_provider == "openai":
        resolved = replace(
            config.llm,
            provider="openai",
            model=str(model or "gpt-5.4").strip() or "gpt-5.4",
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
        )
        return resolved
    raise AgentBackendUnavailableError(
        f"Unsupported LLM provider: {resolved_provider}. Expected one of: deepseek, openai."
    )


def _resolve_base_url(llm_config) -> str:
    if llm_config.provider == "deepseek":
        return os.getenv(DEEPSEEK_BASE_URL_ENV) or llm_config.base_url
    if llm_config.provider == "openai":
        return os.getenv(OPENAI_BASE_URL_ENV) or llm_config.base_url
    return llm_config.base_url
