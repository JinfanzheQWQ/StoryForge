from __future__ import annotations

import os

from storyforge.agents.base import AgentBackend, AgentBackendUnavailableError
from storyforge.agents.langchain_agent import LangChainTextAgentBackend
from storyforge.core.config import AppConfig

DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"


def build_agent_backend(config: AppConfig, use_llm: bool = False) -> AgentBackend:
    enabled = use_llm or config.llm.enabled
    if not enabled:
        raise AgentBackendUnavailableError(
            "Live LLM mode is required. Non-LLM DryRun mode has been removed. "
            "Enable [llm].enabled in config or keep use_llm=true."
        )

    api_key = os.getenv(config.llm.api_key_env)
    if not api_key:
        raise AgentBackendUnavailableError(
            f"Missing required API key env: {config.llm.api_key_env}. "
            "Configure DeepSeek credentials before running StoryForge."
        )

    return LangChainTextAgentBackend(
        model_name=config.llm.model,
        temperature=config.llm.temperature,
        provider=config.llm.provider,
        base_url=os.getenv(DEEPSEEK_BASE_URL_ENV) or config.llm.base_url,
        api_key=api_key,
        timeout_seconds=config.llm.timeout_seconds,
    )
