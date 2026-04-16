from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import httpx

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
    VideoScene,
)
from storyforge.integrations.seedream import SeedreamClient  # noqa: E402


class FakeSeedreamResponse:
    def __init__(
        self,
        *,
        payload: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self._payload = payload or {}
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict:
        return self._payload


def build_http_status_error(status_code: int = 400) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://seedream.example.com/images/generations")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} error",
        request=request,
        response=response,
    )


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
            scenes=[],
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
            scene_id="snowport_01",
            scene_title="雪港巷道",
            scene_prompt="前一段场景",
            scene_master_frame_prompt="雪港巷道母图",
            scene_master_frame_path="snowport_master.png",
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
            scene_id="snowport_01",
            scene_title="雪港巷道",
            scene_prompt="后一段场景",
            scene_master_frame_prompt="雪港巷道母图",
            scene_master_frame_path="snowport_master.png",
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
                scene_lookup={
                    "snowport_01": VideoScene(
                        scene_id="snowport_01",
                        chapter_number=1,
                        title="雪港巷道",
                        summary="测试场景",
                        scene_anchor="同一条雪港巷道",
                        involved_characters=["林雪"],
                        segments=[],
                        scene_master_frame_prompt="雪港巷道母图",
                        scene_master_frame_path="snowport_master.png",
                        scene_master_frame_url="https://example.com/master.png",
                        scene_master_frame_status="completed",
                    )
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
                "https://example.com/master.png",
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
            scene_id="duo_scene",
            scene_title="双人场景",
            scene_prompt="双人场景",
            scene_master_frame_prompt="双人场景母图",
            scene_master_frame_path="duo_master.png",
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
                scene_lookup={
                    "duo_scene": VideoScene(
                        scene_id="duo_scene",
                        chapter_number=1,
                        title="双人场景",
                        summary="测试场景",
                        scene_anchor="双人场景",
                        involved_characters=["林雾", "沈砚"],
                        segments=[],
                        scene_master_frame_prompt="双人场景母图",
                        scene_master_frame_path="duo_master.png",
                        scene_master_frame_url="https://example.com/master.png",
                        scene_master_frame_status="completed",
                    )
                },
            )

        self.assertTrue(success)
        self.assertEqual(task.start_frame_url, "https://example.com/start.png")
        self.assertEqual(task.mid_frame_url, "https://example.com/mid.png")
        self.assertEqual(task.end_frame_url, "https://example.com/end.png")
        self.assertEqual(create_image.call_count, 3)
        self.assertEqual(
            create_image.call_args_list[0].kwargs["reference_images"],
            [
                "https://example.com/master.png",
                "https://example.com/char-a.png",
                "https://example.com/char-b.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            [
                "https://example.com/start.png",
                "https://example.com/master.png",
                "https://example.com/char-a.png",
                "https://example.com/char-b.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[2].kwargs["reference_images"],
            [
                "https://example.com/mid.png",
                "https://example.com/master.png",
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
            scene_id="confession_scene",
            scene_title="告白场景",
            scene_prompt="告白场景",
            scene_master_frame_prompt="告白场景母图",
            scene_master_frame_path="confession_master.png",
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
                scene_lookup={
                    "confession_scene": VideoScene(
                        scene_id="confession_scene",
                        chapter_number=1,
                        title="告白场景",
                        summary="测试场景",
                        scene_anchor="花廊",
                        involved_characters=["陈默", "林晚"],
                        segments=[],
                        scene_master_frame_prompt="告白场景母图",
                        scene_master_frame_path="confession_master.png",
                        scene_master_frame_url="https://example.com/master.png",
                        scene_master_frame_status="completed",
                    )
                },
            )

        self.assertTrue(success)
        self.assertEqual(
            create_image.call_args_list[0].kwargs["reference_images"],
            [
                "https://example.com/master.png",
                "https://example.com/chenmo.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            [
                "https://example.com/start.png",
                "https://example.com/master.png",
                "https://example.com/chenmo.png",
                "https://example.com/linwan.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[2].kwargs["reference_images"],
            [
                "https://example.com/mid.png",
                "https://example.com/master.png",
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
            scenes=[
                VideoScene(
                    scene_id="scene-a",
                    chapter_number=1,
                    title="场景A",
                    summary="测试",
                    scene_anchor="场景A",
                    involved_characters=["林雾"],
                    segments=[],
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    scene_master_frame_url="https://example.com/scene-a-master.png",
                    scene_master_frame_status="completed",
                ),
                VideoScene(
                    scene_id="scene-b",
                    chapter_number=1,
                    title="场景B",
                    summary="测试",
                    scene_anchor="场景B",
                    involved_characters=["林雾"],
                    segments=[],
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                    scene_master_frame_url="https://example.com/scene-b-master.png",
                    scene_master_frame_status="completed",
                ),
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_prompt="片段A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    start_frame_prompt="A首帧",
                    end_frame_prompt="A尾帧",
                    reference_images=["char-a.png"],
                    start_frame_path="seg-a_start.png",
                    end_frame_path="seg-a_end.png",
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_id="scene-b",
                    scene_title="场景B",
                    scene_prompt="片段B",
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
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

    def test_generate_scene_images_creates_scene_master_once_per_scene(self) -> None:
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
            scenes=[
                VideoScene(
                    scene_id="scene-a",
                    chapter_number=1,
                    title="场景A",
                    summary="测试",
                    scene_anchor="场景A",
                    involved_characters=["林雾"],
                    segments=[],
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                )
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a1",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_prompt="片段A1",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    start_frame_prompt="A1首帧",
                    end_frame_prompt="A1尾帧",
                    reference_images=["char-a.png"],
                    start_frame_path="seg-a1_start.png",
                    end_frame_path="seg-a1_end.png",
                    provider="seedream-4.5",
                    start_frame_characters=["林雾"],
                    end_frame_characters=["林雾"],
                    involved_characters=["林雾"],
                ),
                SceneImageTask(
                    segment_id="seg-a2",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_prompt="片段A2",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    start_frame_prompt="A2首帧",
                    end_frame_prompt="A2尾帧",
                    reference_images=["char-a.png"],
                    start_frame_path="seg-a2_start.png",
                    end_frame_path="seg-a2_end.png",
                    provider="seedream-4.5",
                    start_frame_characters=["林雾"],
                    end_frame_characters=["林雾"],
                    involved_characters=["林雾"],
                ),
            ],
            seedance_manifest=SeedanceManifest(
                title="测试 manifest",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[],
            ),
        )

        with patch.object(
            client,
            "_create_image",
            side_effect=[
                "https://example.com/scene-master.png",
                "https://example.com/seg-a1-start.png",
                "https://example.com/seg-a1-end.png",
                "https://example.com/seg-a2-start.png",
                "https://example.com/seg-a2-end.png",
            ],
        ) as create_image:
            report = client.generate_scene_images(
                package,
                force_submit=True,
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 5)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(package.scenes[0].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(package.scenes[0].scene_master_frame_status, "completed")
        self.assertEqual(package.scene_images[0].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(package.scene_images[1].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(create_image.call_args_list[0].kwargs["prompt"], "场景A母图")
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            [
                "https://example.com/scene-master.png",
                "https://example.com/char-a.png",
            ],
        )
        self.assertEqual(
            create_image.call_args_list[3].kwargs["reference_images"],
            [
                "https://example.com/scene-master.png",
                "https://example.com/char-a.png",
            ],
        )

    def test_generate_scene_master_frames_only_updates_selected_scene(self) -> None:
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
            character_images=[],
            scenes=[
                VideoScene(
                    scene_id="scene-a",
                    chapter_number=1,
                    title="场景A",
                    summary="测试",
                    scene_anchor="场景A",
                    involved_characters=[],
                    segments=[],
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                ),
                VideoScene(
                    scene_id="scene-b",
                    chapter_number=1,
                    title="场景B",
                    summary="测试",
                    scene_anchor="场景B",
                    involved_characters=[],
                    segments=[],
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                ),
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_prompt="片段A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    start_frame_prompt="A首帧",
                    end_frame_prompt="A尾帧",
                    reference_images=[],
                    start_frame_path="seg-a_start.png",
                    end_frame_path="seg-a_end.png",
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_id="scene-b",
                    scene_title="场景B",
                    scene_prompt="片段B",
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                    start_frame_prompt="B首帧",
                    end_frame_prompt="B尾帧",
                    reference_images=[],
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

        with patch.object(
            client,
            "_create_image",
            return_value="https://example.com/scene-b-master.png",
        ) as create_image:
            report = client.generate_scene_master_frames(
                package,
                force_submit=True,
                scene_ids={"scene-b"},
                force_regenerate=True,
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(create_image.call_count, 1)
        self.assertEqual(create_image.call_args.kwargs["prompt"], "场景B母图")
        self.assertEqual(package.scenes[0].scene_master_frame_url, "")
        self.assertEqual(package.scenes[1].scene_master_frame_url, "https://example.com/scene-b-master.png")
        self.assertEqual(package.scene_images[0].scene_master_frame_url, "")
        self.assertEqual(package.scene_images[1].scene_master_frame_url, "https://example.com/scene-b-master.png")
        self.assertEqual(package.scene_images[1].scene_master_frame_status, "completed")

    def test_generate_scene_master_frames_force_regenerates_completed_scene(self) -> None:
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
            character_images=[],
            scenes=[
                VideoScene(
                    scene_id="scene-a",
                    chapter_number=1,
                    title="场景A",
                    summary="测试",
                    scene_anchor="场景A",
                    involved_characters=[],
                    segments=[],
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    scene_master_frame_url="https://example.com/old-scene-a-master.png",
                    scene_master_frame_status="completed",
                )
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_prompt="片段A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    start_frame_prompt="A首帧",
                    end_frame_prompt="A尾帧",
                    reference_images=[],
                    start_frame_path="seg-a_start.png",
                    end_frame_path="seg-a_end.png",
                    provider="seedream-4.5",
                    scene_master_frame_url="https://example.com/old-scene-a-master.png",
                    scene_master_frame_status="completed",
                )
            ],
            seedance_manifest=SeedanceManifest(
                title="测试 manifest",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[],
            ),
        )

        with patch.object(
            client,
            "_create_image",
            return_value="https://example.com/new-scene-a-master.png",
        ) as create_image:
            report = client.generate_scene_master_frames(
                package,
                force_submit=True,
                scene_ids={"scene-a"},
                force_regenerate=True,
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(create_image.call_count, 1)
        self.assertEqual(package.scenes[0].scene_master_frame_url, "https://example.com/new-scene-a-master.png")
        self.assertEqual(package.scene_images[0].scene_master_frame_url, "https://example.com/new-scene-a-master.png")
        self.assertEqual(package.scene_images[0].scene_master_frame_status, "completed")

    def test_create_image_falls_back_from_image_to_reference_images_payload(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        http_client = Mock()
        http_client.post.side_effect = [
            FakeSeedreamResponse(error=build_http_status_error()),
            FakeSeedreamResponse(
                payload={"data": [{"url": "https://example.com/generated.png"}]},
            ),
        ]

        with patch.object(
            client,
            "_candidate_endpoints",
            return_value=["https://seedream.example.com/images/generations"],
        ):
            image_url = client._create_image(
                http_client,
                prompt="测试多参考图 fallback",
                reference_images=[
                    "https://example.com/ref-a.png",
                    "https://example.com/ref-b.png",
                ],
            )

        self.assertEqual(image_url, "https://example.com/generated.png")
        self.assertEqual(
            http_client.post.call_args_list[0].kwargs["json"]["image"],
            [
                "https://example.com/ref-a.png",
                "https://example.com/ref-b.png",
            ],
        )
        self.assertEqual(
            http_client.post.call_args_list[1].kwargs["json"]["reference_images"],
            [
                "https://example.com/ref-a.png",
                "https://example.com/ref-b.png",
            ],
        )

    def test_create_image_reduces_reference_count_after_full_multi_ref_failures(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        http_client = Mock()
        http_client.post.side_effect = [
            FakeSeedreamResponse(error=build_http_status_error()),
            FakeSeedreamResponse(error=build_http_status_error()),
            FakeSeedreamResponse(error=build_http_status_error()),
            FakeSeedreamResponse(
                payload={"data": [{"url": "https://example.com/generated-shorter.png"}]},
            ),
        ]
        reference_images = [
            "https://example.com/start.png",
            "https://example.com/master.png",
            "https://example.com/char-a.png",
            "https://example.com/char-b.png",
        ]

        with patch.object(
            client,
            "_candidate_endpoints",
            return_value=["https://seedream.example.com/images/generations"],
        ):
            image_url = client._create_image(
                http_client,
                prompt="测试多参考图递减",
                reference_images=reference_images,
            )

        self.assertEqual(image_url, "https://example.com/generated-shorter.png")
        self.assertEqual(
            http_client.post.call_args_list[3].kwargs["json"]["image"],
            reference_images[:2],
        )

    def test_build_frame_reference_urls_prioritizes_temporal_scene_and_first_two_active_characters(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        character_images = [
            CharacterImageTask(
                character_name="林栀",
                prompt="角色图A",
                output_path="linzhi.png",
                provider="seedream-4.5",
                generated_url="https://example.com/linzhi.png",
            ),
            CharacterImageTask(
                character_name="周骁",
                prompt="角色图B",
                output_path="zhouxiao.png",
                provider="seedream-4.5",
                generated_url="https://example.com/zhouxiao.png",
            ),
            CharacterImageTask(
                character_name="第三人",
                prompt="角色图C",
                output_path="third.png",
                provider="seedream-4.5",
                generated_url="https://example.com/third.png",
            ),
        ]

        reference_urls = client._build_frame_reference_urls(
            temporal_anchor_urls=["https://example.com/prev.png"],
            scene_master_reference_urls=["https://example.com/master.png"],
            frame_character_names=["林栀", "周骁", "第三人"],
            character_images=character_images,
            fallback_urls=[],
        )

        self.assertEqual(
            reference_urls,
            [
                "https://example.com/prev.png",
                "https://example.com/master.png",
                "https://example.com/linzhi.png",
                "https://example.com/zhouxiao.png",
            ],
        )


if __name__ == "__main__":
    unittest.main()
