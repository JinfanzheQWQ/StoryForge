from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.agents.base import AgentBackendUnavailableError  # noqa: E402
from storyforge.core.config import AppConfig, LLMConfig  # noqa: E402
from storyforge.integrations.llm import build_agent_backend  # noqa: E402


class LlmIntegrationTestCase(unittest.TestCase):
    def _config(self) -> AppConfig:
        return AppConfig(
            llm=LLMConfig(
                enabled=True,
                provider="deepseek",
                model="deepseek-chat",
            )
        )

    def test_build_agent_backend_supports_deepseek(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}, clear=True):
            backend = build_agent_backend(self._config(), use_llm=True, provider="deepseek")

        self.assertEqual(backend.provider, "deepseek")
        self.assertEqual(backend.model_name, "deepseek-chat")
        self.assertEqual(backend.api_key, "test-deepseek-key")
        self.assertEqual(backend.base_url, "https://api.deepseek.com/v1")

    def test_build_agent_backend_supports_openai(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "OPENAI_BASE_URL": "https://api.openai-proxy.example/v1",
            },
            clear=True,
        ):
            backend = build_agent_backend(self._config(), use_llm=True, provider="openai")

        self.assertEqual(backend.provider, "openai")
        self.assertEqual(backend.model_name, "gpt-5.4")
        self.assertEqual(backend.api_key, "test-openai-key")
        self.assertEqual(backend.base_url, "https://api.openai-proxy.example/v1")

    def test_build_agent_backend_raises_clear_error_when_api_key_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AgentBackendUnavailableError) as ctx:
                build_agent_backend(self._config(), use_llm=True, provider="openai")

        self.assertIn("OPENAI_API_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
