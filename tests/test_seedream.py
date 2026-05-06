from __future__ import annotations

from pathlib import Path
import tempfile
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
    SceneTransitionContract,
    SceneImageTask,
    SeedanceClipTask,
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
    def test_base_payload_includes_configured_watermark_flag(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                watermark=False,
            )
        )

        payload = client._base_payload("测试 prompt")

        self.assertEqual(payload["model"], client.config.model)
        self.assertEqual(payload["prompt"], "测试 prompt")
        self.assertEqual(payload["size"], client.config.image_size)
        self.assertEqual(payload["response_format"], client.config.response_format)
        self.assertFalse(payload["watermark"])

    def test_single_image_payload_can_include_aspect_ratio(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"

        class FakeClient:
            def __init__(self) -> None:
                self.payload = {}

            def post(self, endpoint, json, headers):
                self.payload = json
                return FakeSeedreamResponse(payload={"data": [{"url": "https://example.com/generated.png"}]})

        fake_client = FakeClient()

        image_url = client._create_image(
            fake_client,
            prompt="清新科技感商业插画",
            aspect_ratio="16:9",
        )

        self.assertEqual(image_url, "https://example.com/generated.png")
        self.assertEqual(fake_client.payload["size"], "2560x1440")
        self.assertEqual(fake_client.payload["aspect_ratio"], "16:9")

    def test_single_image_payload_resolves_portrait_pixel_size(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )

        payload = client._base_payload("竖版海报", aspect_ratio="9:16")

        self.assertEqual(payload["size"], "1440x2560")
        self.assertEqual(payload["aspect_ratio"], "9:16")

    def test_generate_scene_master_frame_records_request_info(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        scene = VideoScene(
            scene_id="scene_01",
            chapter_number=1,
            title="图书馆外",
            summary="测试场景",
            scene_anchor="图书馆外台阶",
            involved_characters=[],
            segments=[],
            scene_master_frame_prompt="无角色场景母图",
            scene_master_frame_path="scene_01_master.png",
            scene_master_reference_images=["https://example.com/previous-master.png"],
        )

        class FakeClient:
            def post(self, endpoint, json, headers):
                return FakeSeedreamResponse(payload={"data": [{"url": "https://example.com/master.png"}]})

        success, generated_now = client._ensure_scene_master_frame(
            FakeClient(),
            scene,
        )

        self.assertTrue(success)
        self.assertTrue(generated_now)
        self.assertEqual(scene.scene_master_frame_url, "https://example.com/master.png")
        self.assertEqual(scene.scene_master_request_info["provider"], "seedream")
        self.assertEqual(scene.scene_master_request_info["payload"]["prompt"], "无角色场景母图")
        self.assertEqual(scene.scene_master_request_info["payload"]["image"], "https://example.com/previous-master.png")
        self.assertEqual(
            scene.scene_master_request_info["reference_bindings"][0]["kind"],
            "previous_scene_master",
        )

    def test_apply_scene_urls_to_seedance_manifest_excludes_scene_master_from_video_refs(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        package = VideoProjectPackage(
            title="测试项目",
            character_profiles=[],
            character_images=[
                CharacterImageTask(
                    character_name="林晨",
                    prompt="角色图",
                    output_path="char-chen.png",
                    provider="seedream-4.5",
                    generated_url="https://example.com/char-chen.png",
                )
            ],
            scenes=[],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="ch01-sc01-seg01",
                    scene_id="ch01-sc01",
                    scene_title="花园等待",
                    scene_master_frame_prompt="场景母图",
                    scene_master_frame_path="scene_master.png",
                    scene_master_frame_url="https://example.com/scene-master.png",
                    reference_images=["char-chen.png"],
                    provider="seedream-4.5",
                    involved_characters=["林晨"],
                )
            ],
            seedance_manifest=SeedanceManifest(
                title="测试 manifest",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[
                    SeedanceClipTask(
                        segment_id="ch01-sc01-seg01",
                        title="花园等待",
                        prompt="测试 prompt",
                        narration="",
                        dialogue_lines=[],
                        subtitle_lines=[],
                        sound_effects=[],
                        music_direction="",
                        timed_beats=[],
                        scene_master_path="scene_master.png",
                        character_image_paths=["char-chen.png"],
                        visible_characters=["林晨"],
                        duration_seconds=8,
                        aspect_ratio="16:9",
                        with_audio=True,
                        output_path="rendered/ch01-sc01-seg01.mp4",
                    )
                ],
            ),
        )

        client._apply_scene_urls_to_seedance_manifest(package)

        clip = package.seedance_manifest.clips[0]
        self.assertEqual(clip.scene_master_url, "https://example.com/scene-master.png")
        self.assertEqual(clip.character_image_urls, ["https://example.com/char-chen.png"])

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
                ),
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=["char-a.png"],
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_id="scene-b",
                    scene_title="场景B",
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                    reference_images=["char-a.png"],
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
            return_value="https://example.com/scene-b-master-new.png",
        ) as create_image:
            report = client.generate_scene_images(
                package,
                force_submit=True,
                segment_ids={"seg-b"},
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(create_image.call_count, 1)
        self.assertEqual(create_image.call_args.kwargs["prompt"], "场景B母图")
        self.assertEqual(package.scenes[0].scene_master_frame_url, "https://example.com/scene-a-master.png")
        self.assertEqual(package.scenes[1].scene_master_frame_url, "https://example.com/scene-b-master-new.png")
        self.assertEqual(package.scene_images[0].scene_master_frame_url, "https://example.com/scene-a-master.png")
        self.assertEqual(package.scene_images[1].scene_master_frame_url, "https://example.com/scene-b-master-new.png")

    def test_generate_scene_images_syncs_scene_master_to_unselected_tasks_in_same_scene(self) -> None:
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
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=["char-a.png"],
                    provider="seedream-4.5",
                    involved_characters=["林雾"],
                ),
                SceneImageTask(
                    segment_id="seg-a2",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=["char-a.png"],
                    provider="seedream-4.5",
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
            return_value="https://example.com/scene-master.png",
        ) as create_image:
            report = client.generate_scene_images(
                package,
                force_submit=True,
                segment_ids={"seg-a1"},
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(report.generated_count, 1)
        self.assertEqual(create_image.call_count, 1)
        self.assertEqual(package.scenes[0].scene_master_frame_status, "completed")
        self.assertEqual(
            package.scene_images[0].scene_master_frame_url,
            "https://example.com/scene-master.png",
        )
        self.assertEqual(
            package.scene_images[1].scene_master_frame_url,
            "https://example.com/scene-master.png",
        )
        self.assertEqual(package.scene_images[1].scene_master_frame_status, "completed")
        self.assertEqual(package.scene_images[1].status, "planned")

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
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=["char-a.png"],
                    provider="seedream-4.5",
                    involved_characters=["林雾"],
                ),
                SceneImageTask(
                    segment_id="seg-a2",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=["char-a.png"],
                    provider="seedream-4.5",
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
            return_value="https://example.com/scene-master.png",
        ) as create_image:
            report = client.generate_scene_images(
                package,
                force_submit=True,
            )

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(package.scenes[0].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(package.scenes[0].scene_master_frame_status, "completed")
        self.assertEqual(package.scene_images[0].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(package.scene_images[1].scene_master_frame_url, "https://example.com/scene-master.png")
        self.assertEqual(create_image.call_args_list[0].kwargs["prompt"], "场景A母图")

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
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=[],
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_id="scene-b",
                    scene_title="场景B",
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                    reference_images=[],
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
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=[],
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

    def test_same_space_scene_generates_new_master_with_previous_master_reference(self) -> None:
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
                    scene_transition_contract=SceneTransitionContract(
                        previous_scene_id="scene-a",
                        transition_mode="direct_continue",
                        scene_spatial_continuity_mode="same_space_progression",
                    ),
                ),
            ],
            segments=[],
            scene_images=[
                SceneImageTask(
                    segment_id="seg-a",
                    scene_id="scene-a",
                    scene_title="场景A",
                    scene_master_frame_prompt="场景A母图",
                    scene_master_frame_path="scene-a_master.png",
                    reference_images=[],
                    provider="seedream-4.5",
                ),
                SceneImageTask(
                    segment_id="seg-b",
                    scene_id="scene-b",
                    scene_title="场景B",
                    scene_master_frame_prompt="场景B母图",
                    scene_master_frame_path="scene-b_master.png",
                    reference_images=[],
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
            side_effect=[
                "https://example.com/scene-a-master.png",
                "https://example.com/scene-b-master.png",
            ],
        ) as create_image:
            report = client.generate_scene_master_frames(package, force_submit=True)

        self.assertTrue(report.submitted)
        self.assertEqual(report.generated_count, 2)
        self.assertEqual(create_image.call_count, 2)
        self.assertEqual(create_image.call_args_list[0].kwargs["reference_images"], [])
        self.assertEqual(
            create_image.call_args_list[1].kwargs["reference_images"],
            ["https://example.com/scene-a-master.png"],
        )
        self.assertEqual(package.scenes[1].scene_master_frame_url, "https://example.com/scene-b-master.png")
        self.assertEqual(package.scenes[1].scene_master_frame_path, "scene-b_master.png")
        self.assertEqual(package.scene_images[1].scene_master_frame_url, "https://example.com/scene-b-master.png")
        self.assertEqual(package.scene_images[1].reference_images, ["https://example.com/scene-a-master.png"])

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

    def test_create_image_uses_image_payload_first_for_single_reference_editing(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        http_client = Mock()
        http_client.post.return_value = FakeSeedreamResponse(
            payload={"data": [{"url": "https://example.com/edited.png"}]}
        )

        with patch.object(
            client,
            "_candidate_endpoints",
            return_value=["https://seedream.example.com/images/generations"],
        ):
            image_url = client._create_image(
                http_client,
                prompt="图文生图编辑指令：基于图片1调整视角。",
                reference_images=["https://example.com/previous-master.png"],
            )

        payload = http_client.post.call_args.kwargs["json"]
        self.assertEqual(image_url, "https://example.com/edited.png")
        self.assertEqual(payload["image"], "https://example.com/previous-master.png")
        self.assertNotIn("reference_images", payload)

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


    def test_generate_character_image_writes_current_on_first_generation(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "林屿_sheet.png"
            task = CharacterImageTask(
                character_name="林屿",
                prompt="角色图",
                output_path=str(output_path),
                provider="seedream-4.5",
            )

            def fake_create_image(http_client, prompt, reference_images=None):
                client._last_request_info = {
                    "provider": "seedream",
                    "endpoint": "https://example.invalid/images/generations",
                    "variant": "text_only; refs=0",
                    "payload": {"prompt": prompt, "watermark": False},
                }
                return "https://example.com/first.png"

            with patch.object(client, "_create_image", side_effect=fake_create_image):
                success = client._generate_character_image(Mock(), task)

            self.assertTrue(success)
            self.assertEqual(task.status, "completed")
            self.assertEqual(task.generated_url, "https://example.com/first.png")
            self.assertEqual(task.candidate_generated_url, "")
            self.assertEqual(task.candidate_output_path, "")
            self.assertEqual(task.request_info["payload"]["prompt"], "角色图")
            self.assertEqual(task.request_info["reference_bindings"], [])

    def test_generate_character_image_writes_candidate_without_replacing_current(self) -> None:
        client = SeedreamClient(
            SeedreamConfig(
                auto_submit=True,
                download_outputs=False,
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "林屿_sheet.png"
            output_path.write_bytes(b"old-image")
            task = CharacterImageTask(
                character_name="林屿",
                prompt="角色图",
                output_path=str(output_path),
                provider="seedream-4.5",
                generated_url="https://example.com/old.png",
            )

            def fake_create_image(http_client, prompt, reference_images=None):
                client._last_request_info = {
                    "provider": "seedream",
                    "endpoint": "https://example.invalid/images/generations",
                    "variant": "text_only; refs=0",
                    "payload": {"prompt": prompt, "watermark": False},
                }
                return "https://example.com/new.png"

            with patch.object(client, "_create_image", side_effect=fake_create_image):
                success = client._generate_character_image(Mock(), task)

            self.assertTrue(success)
            self.assertEqual(task.generated_url, "https://example.com/old.png")
            self.assertEqual(task.request_info["payload"]["prompt"], "角色图")
            self.assertEqual(task.request_info["reference_bindings"], [])
            self.assertEqual(task.candidate_generated_url, "https://example.com/new.png")
            self.assertTrue(Path(task.candidate_output_path).exists())
            self.assertEqual(output_path.read_bytes(), b"old-image")

    def test_download_image_uses_actual_image_suffix(self) -> None:
        client = SeedreamClient(SeedreamConfig(auto_submit=True, download_outputs=True))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "林屿_sheet.png"
            response = httpx.Response(
                200,
                content=b"\xff\xd8\xff\xe0jpeg-bytes",
                headers={"content-type": "image/png"},
                request=httpx.Request("GET", "https://example.com/linyu"),
            )
            http_client = Mock()
            http_client.get.return_value = response

            downloaded_path = client._download_image(http_client, "https://example.com/linyu", output_path)

            self.assertEqual(downloaded_path, output_path.with_suffix(".jpg"))
            self.assertFalse(output_path.exists())
            self.assertEqual(downloaded_path.read_bytes(), b"\xff\xd8\xff\xe0jpeg-bytes")


if __name__ == "__main__":
    unittest.main()
