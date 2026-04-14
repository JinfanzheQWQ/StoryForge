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
        self.assertTrue(captured["kwargs"]["include_raw"])
        self.assertTrue(captured["kwargs"]["strict"])
        self.assertEqual(len(captured["messages"]), 2)

    def test_structured_generation_parses_raw_json_when_tool_call_is_missing(self) -> None:
        class FakeRawMessage:
            content = """
```json
{
  "title": "雨夜站台",
  "premise": "雨夜站台上的一次坦白。",
  "theme": "勇气",
  "setting": "末班车站台",
  "story_engine": "倒计时迫使两个人说出真心。",
  "visual_motifs": ["雨", "灯牌"],
  "tone_notes": ["克制"]
}
```
"""
            tool_calls: list[object] = []

        class FakeStructuredModel:
            def invoke(self, messages):
                return {
                    "raw": FakeRawMessage(),
                    "parsed": None,
                    "parsing_error": None,
                }

        class FakeModel:
            def with_structured_output(self, schema, **kwargs):
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

        self.assertEqual(result.title, "雨夜站台")
        self.assertEqual(result.visual_motifs, ["雨", "灯牌"])

    def test_structured_generation_raises_clear_error_when_parsed_output_is_empty(self) -> None:
        class FakeRawMessage:
            content = "我无法按要求输出。"
            tool_calls: list[object] = []

        class FakeStructuredModel:
            def invoke(self, messages):
                return {
                    "raw": FakeRawMessage(),
                    "parsed": None,
                    "parsing_error": None,
                }

        class FakeModel:
            def with_structured_output(self, schema, **kwargs):
                return FakeStructuredModel()

        backend = LangChainTextAgentBackend(model_name="deepseek-chat")
        with patch.object(backend, "_build_model", return_value=FakeModel()):
            with self.assertRaises(RuntimeError) as ctx:
                backend.generate_structured(
                    PromptRequest(
                        system_prompt="system",
                        user_prompt="user",
                        metadata={"task": "story-architect"},
                    ),
                    StoryArchitectureSchema,
                )

        self.assertIn("structured output was empty", str(ctx.exception))
        self.assertIn("tool_call_count=0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
