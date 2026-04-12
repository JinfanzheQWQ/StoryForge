from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import SeedreamConfig  # noqa: E402
from storyforge.domains.video.contracts import (  # noqa: E402
    CharacterImageTask,
    SceneImageTask,
    SeedanceManifest,
    VideoProjectPackage,
)
from storyforge.integrations.seedream import SeedreamClient  # noqa: E402


class SeedreamClientTestCase(unittest.TestCase):
    def test_force_submit_executes_even_when_auto_submit_is_disabled(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=False,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        package = VideoProjectPackage(
            title="测试项目",
            character_profiles=[],
            character_images=[],
            segments=[],
            scene_images=[],
            seedance_manifest=SeedanceManifest(
                title="测试 manifest",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[],
            ),
        )

        report = client.generate_project_images(package, force_submit=True)

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 0)
        self.assertEqual(report.failed_count, 0)

    def test_reuse_previous_end_frame_as_next_start_frame(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        previous_task = SceneImageTask(
            segment_id="snowport_01_01",
            scene_prompt="前一段场景",
            start_frame_prompt="前一段首帧",
            end_frame_prompt="前一段尾帧",
            reference_images=["char-sheet.png"],
            start_frame_path="prev_start.png",
            end_frame_path="prev_end.png",
            provider="seedream-4.5",
            end_frame_url="https://example.com/prev-end.png",
        )
        current_task = SceneImageTask(
            segment_id="snowport_01_02",
            scene_prompt="后一段场景",
            start_frame_prompt="后一段首帧",
            end_frame_prompt="后一段尾帧",
            reference_images=["char-sheet.png"],
            start_frame_path="curr_start.png",
            end_frame_path="curr_end.png",
            provider="seedream-4.5",
            reuse_previous_end_frame=True,
            continuity_source_segment_id="snowport_01_01",
        )
        character_images = [
            CharacterImageTask(
                character_name="林雪",
                prompt="角色图",
                output_path="char-sheet.png",
                provider="seedream-4.5",
                generated_url="https://example.com/char-sheet.png",
            )
        ]

        with patch.object(
            client,
            "_create_image",
            return_value="https://example.com/current-end.png",
        ) as create_image:
            success = client._generate_scene_frames(
                client=Mock(),
                task=current_task,
                character_images=character_images,
                scene_map={
                    previous_task.segment_id: previous_task,
                    current_task.segment_id: current_task,
                },
            )

        self.assertTrue(success)
        self.assertEqual(current_task.start_frame_url, "https://example.com/prev-end.png")
        self.assertEqual(current_task.end_frame_url, "https://example.com/current-end.png")
        create_image.assert_called_once_with(
            unittest.mock.ANY,
            prompt="后一段尾帧",
            reference_images=[
                "https://example.com/prev-end.png",
                "https://example.com/char-sheet.png",
            ],
        )


if __name__ == "__main__":
    unittest.main()
