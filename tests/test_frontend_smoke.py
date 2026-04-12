from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FrontendSmokeTestCase(unittest.TestCase):
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
