from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FrontendSmokeTestCase(unittest.TestCase):
    def test_detail_assets_module_imports(self) -> None:
        result = subprocess.run(
            [
                "node",
                "-e",
                "import('./src/storyforge/api/static/app/render/detail_assets.js')",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                "detail_assets.js failed to import as an ES module.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

    def test_render_patch_smoke(self) -> None:
        test_file = ROOT / "tests" / "frontend" / "render_patch.test.mjs"
        result = subprocess.run(
            ["node", "--test", str(test_file)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                "Node frontend smoke test failed.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )


if __name__ == "__main__":
    unittest.main()
