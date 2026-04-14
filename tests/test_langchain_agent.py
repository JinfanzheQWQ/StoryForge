from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.agents.base import PromptRequest  # noqa: E402
from storyforge.agents.langchain_agent import LangChainTextAgentBackend  # noqa: E402
from storyforge.domains.novel.schemas import StoryArchitectureSchema  # noqa: E402


class LangChainAgentBackendTestCase(unittest.TestCase):
    def test_structured_generation_uses_langchain_structured_output_wrapper(self) -> None:
        captured: dict[str, object] = {}

        class FakeStructuredModel:
            def invoke(self, messages):
                captured["messages"] = messages
                return StoryArchitectureSchema(
                    title="站台告白",
                    premise="列车离站前的告白。",
                    theme="告别与勇气",
                    setting="夜晚站台",
                    story_engine="离站倒计时逼迫关系表态。",
                    visual_motifs=["站台", "列车", "夜风"],
                    tone_notes=["克制", "电影感"],
                )

        class FakeModel:
            def with_structured_output(self, schema, **kwargs):
                captured["schema"] = schema
                captured["kwargs"] = kwargs
                return FakeStructuredModel()

        backend = LangChainTextAgentBackend(model_name="deepseek-chat")
        with patch.object(backend, "_build_model", return_value=FakeModel()):
            result = backend.generate_structured(
                PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "story-architect"},
                ),
                StoryArchitectureSchema,
            )

        self.assertEqual(result.title, "站台告白")
        self.assertIs(captured["schema"], StoryArchitectureSchema)
        self.assertEqual(captured["kwargs"]["method"], "function_calling")
        self.assertTrue(captured["kwargs"]["strict"])
        self.assertEqual(len(captured["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
