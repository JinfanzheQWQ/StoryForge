from __future__ import annotations

import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import GPTImageConfig  # noqa: E402
from storyforge.integrations.gpt_image import GPTImageClient  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict, content: bytes = b"") -> None:
        self._payload = payload
        self.content = content
        self.headers = {"content-type": "image/png"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class GPTImageClientTestCase(unittest.TestCase):
    def test_kie_image_to_image_uses_configured_model_and_reference_urls(self) -> None:
        client = GPTImageClient(
            GPTImageConfig(
                provider="kie",
                kie_base_url="https://kie.example.com",
                poll_interval_seconds=0,
            )
        )

        class FakeClient:
            def __init__(self) -> None:
                self.post_payload: dict = {}

            def post(self, endpoint, json, headers):
                self.post_payload = json
                return FakeResponse({"data": {"taskId": "task-1"}})

            def get(self, endpoint, params, headers):
                return FakeResponse(
                    {
                        "data": {
                            "state": "success",
                            "resultJson": '{"resultUrls":["https://example.com/generated.png"]}',
                        }
                    }
                )

        fake_client = FakeClient()
        with patch.dict("os.environ", {"KIE_API_KEY": "test-key"}, clear=False):
            image_url = client._generate_with_kie(
                fake_client,
                mode="image_to_image",
                prompt="保持构图，改成电影感插画",
                reference_images=["https://example.com/ref.png"],
                aspect_ratio="16:9",
                output_size="1K",
            )

        self.assertEqual(image_url, "https://example.com/generated.png")
        self.assertEqual(fake_client.post_payload["model"], "gpt-image-2-image-to-image")
        self.assertEqual(fake_client.post_payload["input"]["input_urls"], ["https://example.com/ref.png"])
        self.assertEqual(fake_client.post_payload["input"]["resolution"], "1K")
        self.assertEqual(fake_client.post_payload["input"]["aspect_ratio"], "16:9")

    def test_resolves_kie_gpt_image_2_resolution_and_ratio(self) -> None:
        client = GPTImageClient(GPTImageConfig(provider="kie"))

        self.assertEqual(client._resolve_kie_resolution_and_ratio("auto", "auto"), ("1K", "auto"))
        self.assertEqual(client._resolve_kie_resolution_and_ratio("1K", "1:1"), ("1K", "1:1"))
        self.assertEqual(client._resolve_kie_resolution_and_ratio("2K", "3:4"), ("2K", "3:4"))
        self.assertEqual(client._resolve_kie_resolution_and_ratio("4K", "16:9"), ("4K", "16:9"))

    def test_resolves_openai_image_size_presets(self) -> None:
        client = GPTImageClient(GPTImageConfig(provider="openai"))

        self.assertEqual(client._resolve_openai_size("auto", "auto"), "auto")
        self.assertEqual(client._resolve_openai_size("1K", "1:1"), "1024x1024")
        self.assertEqual(client._resolve_openai_size("1K", "2:3"), "1024x1536")
        self.assertEqual(client._resolve_openai_size("1K", "3:2"), "1536x1024")

    def test_rejects_unsupported_gpt_image_2_ratio(self) -> None:
        kie_client = GPTImageClient(GPTImageConfig(provider="kie"))
        openai_client = GPTImageClient(GPTImageConfig(provider="openai"))

        with self.assertRaisesRegex(ValueError, "1K"):
            kie_client._resolve_kie_resolution_and_ratio("1K", "2:3")

        with self.assertRaisesRegex(ValueError, "4K"):
            kie_client._resolve_kie_resolution_and_ratio("4K", "1:1")

        with self.assertRaisesRegex(ValueError, "GPT Image 2"):
            openai_client._resolve_openai_size("2K", "1:1")

    def test_openai_generation_writes_base64_image_to_output_path(self) -> None:
        client = GPTImageClient(GPTImageConfig(provider="openai", openai_base_url="https://openai.example.com/v1"))
        image_bytes = b"fake-image"
        encoded = base64.b64encode(image_bytes).decode("ascii")

        class FakeClient:
            def __init__(self) -> None:
                self.payload: dict = {}

            def post(self, endpoint, json, headers):
                self.payload = json
                return FakeResponse({"data": [{"b64_json": encoded}]})

        fake_client = FakeClient()
        with tempfile.TemporaryDirectory() as raw_dir:
            output_path = Path(raw_dir) / "generated.png"
            image_url = client._create_openai_generation(
                fake_client,
                api_key="test-key",
                prompt="清新科技感图书馆",
                size="2048x1152",
                output_path=output_path,
            )

            self.assertEqual(image_url, "")
            self.assertEqual(output_path.read_bytes(), image_bytes)

        self.assertEqual(fake_client.payload["model"], "gpt-image-2")
        self.assertEqual(fake_client.payload["size"], "2048x1152")
        self.assertEqual(fake_client.payload["quality"], "auto")


if __name__ == "__main__":
    unittest.main()
