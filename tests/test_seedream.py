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

    def test_generate_scene_frames_builds_mid_frame_when_required(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        task = SceneImageTask(
            segment_id="duo_01",
            scene_prompt="双人场景",
            start_frame_prompt="首帧",
            mid_frame_prompt="中段",
            end_frame_prompt="尾帧",
            reference_images=["char-a.png", "char-b.png"],
            start_frame_path="duo_start.png",
            mid_frame_path="duo_mid.png",
            end_frame_path="duo_end.png",
            provider="seedream-4.5",
            involved_characters=["林雾", "沈砚"],
            start_frame_characters=["林雾", "沈砚"],
            mid_frame_characters=["林雾", "沈砚"],
            end_frame_characters=["林雾", "沈砚"],
            requires_mid_frame=True,
        )
        character_images = [
            CharacterImageTask(
                character_name="林雾",
                prompt="角色图A",
                output_path="char-a.png",
                provider="seedream-4.5",
                generated_url="https://example.com/char-a.png",
            ),
            CharacterImageTask(
                character_name="沈砚",
                prompt="角色图B",
                output_path="char-b.png",
                provider="seedream-4.5",
                generated_url="https://example.com/char-b.png",
            ),
        ]

        with patch.object(
            client,
            "_create_image",
            side_effect=[
                "https://example.com/start.png",
                "https://example.com/mid.png",
                "https://example.com/end.png",
            ],
        ) as create_image:
            success = client._generate_scene_frames(
                client=Mock(),
                task=task,
                character_images=character_images,
                scene_map={task.segment_id: task},
            )

        self.assertTrue(success)
        self.assertEqual(task.start_frame_url, "https://example.com/start.png")
        self.assertEqual(task.mid_frame_url, "https://example.com/mid.png")
        self.assertEqual(task.end_frame_url, "https://example.com/end.png")
        self.assertEqual(create_image.call_count, 3)
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            [
                "https://example.com/start.png",
                "https://example.com/char-a.png",
                "https://example.com/char-b.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[2].kwargs["reference_images"],
            [
                "https://example.com/mid.png",
                "https://example.com/char-a.png",
                "https://example.com/char-b.png",
            ],
        )

    def test_generate_scene_frames_uses_frame_specific_character_references(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        task = SceneImageTask(
            segment_id="confession_01",
            scene_prompt="告白场景",
            start_frame_prompt="陈默独自等待",
            mid_frame_prompt="林晚走近陈默",
            end_frame_prompt="陈默仍独自望向小径",
            reference_images=["chenmo.png", "linwan.png"],
            start_frame_path="start.png",
            mid_frame_path="mid.png",
            end_frame_path="end.png",
            provider="seedream-4.5",
            involved_characters=["陈默", "林晚"],
            start_frame_characters=["陈默"],
            mid_frame_characters=["陈默", "林晚"],
            end_frame_characters=["陈默"],
            requires_mid_frame=True,
        )
        character_images = [
            CharacterImageTask(
                character_name="陈默",
                prompt="角色图A",
                output_path="chenmo.png",
                provider="seedream-4.5",
                generated_url="https://example.com/chenmo.png",
            ),
            CharacterImageTask(
                character_name="林晚",
                prompt="角色图B",
                output_path="linwan.png",
                provider="seedream-4.5",
                generated_url="https://example.com/linwan.png",
            ),
        ]

        with patch.object(
            client,
            "_create_image",
            side_effect=[
                "https://example.com/start.png",
                "https://example.com/mid.png",
                "https://example.com/end.png",
            ],
        ) as create_image:
            success = client._generate_scene_frames(
                client=Mock(),
                task=task,
                character_images=character_images,
                scene_map={task.segment_id: task},
            )

        self.assertTrue(success)
        self.assertEqual(
            create_image.call_args_list[0].kwargs["reference_images"],
            ["https://example.com/chenmo.png"],
        )
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            [
                "https://example.com/start.png",
                "https://example.com/chenmo.png",
                "https://example.com/linwan.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[2].kwargs["reference_images"],
            [
                "https://example.com/mid.png",
                "https://example.com/chenmo.png",
            ],
        )

    def test_generate_scene_images_only_processes_selected_segment(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        package = VideoProjectPackage(
            title="测试项目",
            character_profiles=[],
            character_images=[
                CharacterImageTask(
                    character_name="林雾",
                    prompt="角色图",
                    output_path="char-a.png",
                    provider="seedream-4.5",
                    generated_url="https://example.com/char-a.png",
                )
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_prompt="片段A",
                    start_frame_prompt="A首帧",
                    end_frame_prompt="A尾帧",
                    reference_images=["char-a.png"],
                    start_frame_path="seg-a_start.png",
                    end_frame_path="seg-a_end.png",
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_prompt="片段B",
                    start_frame_prompt="B首帧",
                    end_frame_prompt="B尾帧",
                    reference_images=["char-a.png"],
                    start_frame_path="seg-b_start.png",
                    end_frame_path="seg-b_end.png",
                    provider="seedream-4.5",
                ),
            ],
            seedance_manifest=SeedanceManifest(
                title="测试 manifest",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[],
            ),
        )

        with patch.object(client, "_generate_scene_frames", return_value=True) as generate_scene_frames:
            report = client.generate_scene_images(
                package,
                force_submit=True,
                segment_ids={"seg-b"},
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 2)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(generate_scene_frames.call_count, 1)
        self.assertEqual(generate_scene_frames.call_args.args[1].segment_id, "seg-b")
        self.assertEqual(package.scene_images[0].status, "planned")


if __name__ == "__main__":
    unittest.main()
