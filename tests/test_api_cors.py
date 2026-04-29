from __future__ import annotations

from pathlib import Path
import sys
import unittest

from fastapi.middleware.cors import CORSMiddleware


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.api.main import create_app  # noqa: E402


class ApiCorsTestCase(unittest.TestCase):
    def test_react_dev_server_origin_is_allowed(self) -> None:
        app = create_app(project_root=ROOT, config_path=ROOT / "configs/storyforge.example.toml")
        cors_layers = [layer for layer in app.user_middleware if layer.cls is CORSMiddleware]
        self.assertEqual(len(cors_layers), 1)
        self.assertIn("http://localhost:5173", cors_layers[0].kwargs["allow_origins"])
        self.assertIn("http://127.0.0.1:5173", cors_layers[0].kwargs["allow_origins"])


if __name__ == "__main__":
    unittest.main()
