from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import AppConfig  # noqa: E402
from storyforge.core.env import load_env_file  # noqa: E402


class ConfigTestCase(unittest.TestCase):
    def test_load_example_config(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        self.assertEqual(config.llm.provider, "deepseek")
        self.assertEqual(config.llm.model, "deepseek-chat")
        self.assertEqual(config.llm.available_providers, ("deepseek", "openai"))
        self.assertTrue(config.llm.enabled)
        self.assertEqual(config.video.segment_duration_seconds, 5)
        self.assertEqual(config.video.character_image_provider, "seedream-4.5")
        self.assertEqual(config.video.scene_image_provider, "seedream-4.5")
        self.assertEqual(config.seedream.model, "doubao-seedream-4-5-251128")
        self.assertEqual(config.seedream.response_format, "url")
        self.assertEqual(config.seedance.model, "doubao-seedance-2-0-260128")
        self.assertFalse(config.seedance.auto_submit)
        self.assertEqual(config.seedance.subtitle_mode, "burned_in")
        self.assertEqual(config.seedance.poll_interval_seconds, 5.0)
        self.assertEqual(config.database.host, "127.0.0.1")
        self.assertEqual(config.database.port, 3306)
        self.assertEqual(config.database.user, "root")
        self.assertEqual(config.database.database, "storyforge")
        self.assertEqual(config.queue.concurrency, 2)

    def test_load_live_config(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.live.example.toml")
        self.assertTrue(config.llm.enabled)
        self.assertTrue(config.seedream.auto_submit)
        self.assertTrue(config.seedance.auto_submit)
        self.assertEqual(config.seedance.subtitle_mode, "burned_in")
        self.assertEqual(config.novel.chapter_scene_count, 1)

    def test_database_password_can_resolve_from_environment(self) -> None:
        with patch.dict(os.environ, {"STORYFORGE_DB_PASSWORD": "root"}, clear=False):
            config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
            self.assertEqual(config.database.resolved_password(), "root")

    def test_env_file_can_override_stale_shell_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            env_path = Path(raw_dir) / ".env"
            env_path.write_text("SEEDREAM_BASE_URL=https://from-dot-env.example.com\n")
            with patch.dict(
                os.environ,
                {"SEEDREAM_BASE_URL": "not-a-valid-host"},
                clear=False,
            ):
                load_env_file(env_path, override=True)
                self.assertEqual(
                    os.environ["SEEDREAM_BASE_URL"],
                    "https://from-dot-env.example.com",
                )


if __name__ == "__main__":
    unittest.main()
