from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.api.template_renderer import render_template  # noqa: E402


class UiTemplateTestCase(unittest.TestCase):
    def test_console_template_renders_all_panels_and_lightbox(self) -> None:
        template_root = ROOT / "src" / "storyforge" / "api" / "templates"

        html = render_template(template_root, "console.html")

        self.assertIn("StoryForge Studio", html)
        self.assertIn('data-page-panel="home"', html)
        self.assertIn('data-page-panel="create"', html)
        self.assertIn('data-page-panel="projects"', html)
        self.assertIn('data-page-panel="queue"', html)
        self.assertIn('id="lightbox"', html)
        self.assertNotIn("{{ include", html)


if __name__ == "__main__":
    unittest.main()
