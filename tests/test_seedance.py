from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import SeedanceConfig  # noqa: E402
from storyforge.domains.video.contracts import SeedanceClipTask, SeedanceManifest  # noqa: E402
from storyforge.integrations.seedance import SeedanceClient  # noqa: E402


class SeedanceClientTestCase(unittest.TestCase):
    def test_force_submit_executes_even_when_auto_submit_is_disabled(self) -> None:
        client = SeedanceClient(
            SeedanceConfig(
                auto_submit=False,
                download_outputs=False,
            )
        )
        client.api_key = "test-key"
        manifest = SeedanceManifest(
            title="测试 manifest",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[],
        )

        report = client.execute_manifest(manifest, force_submit=True)

        self.assertTrue(report.submitted)
        self.assertEqual(report.completed_count, 0)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(report.pending_count, 0)

    def test_build_payload_uses_scene_master_and_character_references(self) -> None:
        client = SeedanceClient(
            SeedanceConfig(
                model="doubao-seedance-2-0-260128",
                watermark=False,
            )
        )
        clip = SeedanceClipTask(
            segment_id="ch01-seg01",
            title="测试片段",
            prompt="冷色灯光下，角色从站台走向广播室。",
            narration="旁白测试。",
            dialogue_lines=["角色A：你终于来了。"],
            subtitle_lines=["角色A：你终于来了。", "旁白测试。"],
            sound_effects=["风声", "脚步声"],
            music_direction="低频悬疑氛围",
            timed_beats=["[0s-2s] 角色入场。"],
            scene_master_url="https://example.com/scene.png",
            character_image_urls=["https://example.com/role-a.png", "https://example.com/role-b.png"],
            visible_characters=["角色A", "角色B"],
            duration_seconds=5,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-seg01.mp4",
        )

        payload = client.build_payload(clip)

        self.assertEqual(payload["model"], "doubao-seedance-2-0-260128")
        self.assertEqual(payload["ratio"], "16:9")
        self.assertEqual(payload["duration"], 5)
        self.assertFalse(payload["watermark"])
        self.assertTrue(payload["generate_audio"])
        self.assertIn("提交素材绑定", payload["content"][0]["text"])
        self.assertIn("图片1：场景母图", payload["content"][0]["text"])
        self.assertIn("图片2：角色A 的角色图", payload["content"][0]["text"])
        self.assertIn("图片3：角色B 的角色图", payload["content"][0]["text"])
        self.assertIn("角色图只用于身份参考，不是视频时间帧", payload["content"][0]["text"])
        self.assertEqual(
            [item.get("role", "text") for item in payload["content"]],
            ["text", "reference_image", "reference_image", "reference_image"],
        )
        self.assertEqual(payload["content"][1]["image_url"]["url"], "https://example.com/scene.png")
        self.assertEqual(payload["content"][2]["image_url"]["url"], "https://example.com/role-a.png")
        self.assertEqual(payload["content"][3]["image_url"]["url"], "https://example.com/role-b.png")

    def test_build_payload_prefers_scene_master_and_character_references(self) -> None:
        client = SeedanceClient(SeedanceConfig(model="doubao-seedance-2-0-260128"))
        clip = SeedanceClipTask(
            segment_id="ch01-seg-v2",
            scene_id="ch01-sc01",
            title="喊住",
            prompt="在图片1的樱花石板路场景中，陈屿喊住苏晚，苏晚停步摘下一边耳机并回头。",
            narration="",
            dialogue_lines=["陈屿：苏晚。"],
            subtitle_lines=["苏晚"],
            sound_effects=["微风", "脚步声"],
            music_direction="青春电影感",
            timed_beats=["0-2秒：陈屿吸气。", "2-8秒：苏晚停步回头。"],
            scene_master_path="scene.png",
            scene_master_url="https://example.com/scene.png",
            character_image_paths=["chen.png", "su.png"],
            character_image_urls=["https://example.com/chen.png", "https://example.com/su.png"],
            visible_characters=["陈屿", "苏晚"],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-seg-v2.mp4",
        )

        payload, resolved_prompt, bindings = client._build_payload_with_metadata(clip)

        self.assertIn("图片1：场景母图", resolved_prompt)
        self.assertIn("图片2：陈屿 的角色图", resolved_prompt)
        self.assertIn("图片3：苏晚 的角色图", resolved_prompt)
        self.assertIn("角色图只用于身份参考，不是视频时间帧", resolved_prompt)
        self.assertNotIn("严格按 图片1 -> 图片2", resolved_prompt)
        self.assertEqual(payload["content"][1]["image_url"]["url"], "https://example.com/scene.png")
        self.assertEqual(payload["content"][2]["image_url"]["url"], "https://example.com/chen.png")
        self.assertEqual(payload["content"][3]["image_url"]["url"], "https://example.com/su.png")
        self.assertEqual([item["kind"] for item in bindings], ["scene_master", "character", "character"])

    def test_build_payload_without_references_stays_text_only(self) -> None:
        client = SeedanceClient(SeedanceConfig())
        clip = SeedanceClipTask(
            segment_id="ch01-seg02",
            title="测试片段",
            prompt="测试",
            narration="测试",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-seg02.mp4",
        )

        payload = client.build_payload(clip)

        self.assertEqual(
            [item.get("role", "text") for item in payload["content"]],
            ["text"],
        )
        self.assertNotIn("提交素材绑定", payload["content"][0]["text"])

    def test_submit_clip_reports_timeline_payload_rejection_without_retry(self) -> None:
        client = SeedanceClient(SeedanceConfig())
        clip = SeedanceClipTask(
            segment_id="seg-retry",
            title="回退测试",
            prompt="测试",
            narration="测试",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            scene_master_url="https://example.com/scene.png",
            character_image_urls=["https://example.com/role.png"],
            visible_characters=["角色"],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/seg-retry.mp4",
        )

        request = httpx.Request("POST", "https://example.com/tasks")
        responses = [
            httpx.Response(
                400,
                json={"error": {"message": "reference_image is invalid"}},
                request=request,
            ),
        ]

        class FakeClient:
            def __init__(self, response_queue):
                self.response_queue = list(response_queue)
                self.calls = []

            def post(self, endpoint, json, headers):
                self.calls.append(
                    {
                        "endpoint": endpoint,
                        "payload": json,
                        "headers": headers,
                    }
                )
                return self.response_queue.pop(0)

        fake_client = FakeClient(responses)

        with self.assertRaisesRegex(RuntimeError, "reference_image is invalid"):
            client._submit_clip(fake_client, clip)

        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(clip.submit_variant, "scene_character_motion")
        self.assertIn("提交素材绑定", clip.submitted_prompt)
        self.assertTrue(clip.submitted_reference_bindings)
        self.assertEqual(clip.submitted_reference_bindings[0]["kind"], "scene_master")
        self.assertEqual(clip.submitted_reference_bindings[1]["kind"], "character")
        self.assertEqual(clip.submitted_reference_bindings[0]["label"], "图片1")
        self.assertEqual(clip.submitted_request_info["provider"], "seedance")
        self.assertEqual(clip.submitted_request_info["variant"], "scene_character_motion")
        self.assertEqual(
            clip.submitted_request_info["payload"]["content"][1]["image_url"]["url"],
            "https://example.com/scene.png",
        )
        self.assertEqual(
            [item.get("role", "text") for item in fake_client.calls[0]["payload"]["content"]],
            ["text", "reference_image", "reference_image"],
        )
        self.assertIn("图片1：场景母图", fake_client.calls[0]["payload"]["content"][0]["text"])

    def test_submit_clip_raises_detailed_error_after_all_payload_variants_fail(self) -> None:
        client = SeedanceClient(SeedanceConfig())
        clip = SeedanceClipTask(
            segment_id="seg-fail",
            title="失败片段",
            prompt="测试",
            narration="测试",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/seg-fail.mp4",
        )

        request = httpx.Request("POST", "https://example.com/tasks")
        responses = [
            httpx.Response(400, json={"error": {"message": "bad timeline_only"}}, request=request),
        ]

        class FakeClient:
            def __init__(self, response_queue):
                self.response_queue = list(response_queue)

            def post(self, endpoint, json, headers):
                return self.response_queue.pop(0)

        with self.assertRaisesRegex(RuntimeError, "bad timeline_only"):
            client._submit_clip(FakeClient(responses), clip)

    def test_extract_video_url_from_live_status_shape(self) -> None:
        client = SeedanceClient(SeedanceConfig())
        payload = {
            "id": "task-1",
            "status": "succeeded",
            "content": {
                "video_url": "https://example.com/video.mp4",
            },
        }

        self.assertEqual(client._extract_status(payload), "succeeded")
        self.assertEqual(client._extract_video_url(payload), "https://example.com/video.mp4")

    def test_build_payload_rejects_invalid_duration_before_submit(self) -> None:
        client = SeedanceClient(SeedanceConfig())
        clip = SeedanceClipTask(
            segment_id="too-long",
            title="无效时长片段",
            prompt="测试",
            narration="测试",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=30,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/too-long.mp4",
        )

        with self.assertRaisesRegex(ValueError, "between 2 and 12 seconds"):
            client.build_payload(clip)

    def test_execute_manifest_resumes_pending_clip_without_resubmitting_completed_clips(self) -> None:
        with TemporaryDirectory() as temp_dir:
            completed_path = Path(temp_dir) / "completed.mp4"
            pending_path = Path(temp_dir) / "pending.mp4"
            completed_path.write_bytes(b"completed video")
            completed_clip = SeedanceClipTask(
                segment_id="done",
                title="已完成片段",
                prompt="测试",
                narration="测试",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=[],
                duration_seconds=5,
                aspect_ratio="16:9",
                with_audio=True,
                output_path=str(completed_path),
                remote_task_id="task-done",
                submit_status="completed",
                remote_status="succeeded",
                video_url="https://example.com/done.mp4",
                downloaded_path=str(completed_path),
            )
            pending_clip = SeedanceClipTask(
                segment_id="pending",
                title="待恢复片段",
                prompt="测试",
                narration="测试",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=[],
                duration_seconds=5,
                aspect_ratio="16:9",
                with_audio=True,
                output_path=str(pending_path),
                remote_task_id="task-pending",
                submit_status="timeout",
                remote_status="timeout",
            )
            manifest = SeedanceManifest(
                title="恢复测试",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[completed_clip, pending_clip],
            )
            client = SeedanceClient(
                SeedanceConfig(
                    auto_submit=False,
                    download_outputs=True,
                )
            )
            client.api_key = "test-key"

            def fake_download(_http_client, _video_url, output_path):
                output_path.write_bytes(b"recovered video")

            with (
                patch.object(client, "_submit_clip", side_effect=AssertionError("should not resubmit")) as submit,
                patch.object(
                    client,
                    "fetch_task_status_sync",
                    return_value={
                        "status": "succeeded",
                        "content": {"video_url": "https://example.com/pending.mp4"},
                    },
                ) as fetch,
                patch.object(client, "_download_video", side_effect=fake_download) as download,
            ):
                report = client.execute_manifest(manifest, force_submit=True)

            submit.assert_not_called()
            fetch.assert_called_once()
            download.assert_called_once()
            self.assertEqual(report.completed_count, 2)
            self.assertEqual(report.failed_count, 0)
            self.assertEqual(report.pending_count, 0)
            self.assertTrue(pending_path.exists())
            self.assertEqual(pending_clip.submit_status, "completed")
            self.assertEqual(pending_clip.remote_status, "succeeded")
            self.assertEqual(pending_clip.downloaded_path, str(pending_path))

    def test_execute_manifest_only_processes_selected_segment(self) -> None:
        with TemporaryDirectory() as temp_dir:
            clip_a_path = Path(temp_dir) / "clip-a.mp4"
            clip_b_path = Path(temp_dir) / "clip-b.mp4"
            clip_a = SeedanceClipTask(
                segment_id="seg-a",
                title="片段A",
                prompt="A",
                narration="A",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=[],
                duration_seconds=5,
                aspect_ratio="16:9",
                with_audio=True,
                output_path=str(clip_a_path),
            )
            clip_b = SeedanceClipTask(
                segment_id="seg-b",
                title="片段B",
                prompt="B",
                narration="B",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=[],
                duration_seconds=5,
                aspect_ratio="16:9",
                with_audio=True,
                output_path=str(clip_b_path),
            )
            manifest = SeedanceManifest(
                title="片段选择测试",
                model="doubao-seedance-2-0-260128",
                base_url="",
                clips=[clip_a, clip_b],
            )
            client = SeedanceClient(
                SeedanceConfig(
                    auto_submit=False,
                    download_outputs=False,
                )
            )
            client.api_key = "test-key"

            def fake_submit_clip(_http_client, clip):
                clip.remote_task_id = "task-b"
                clip.submit_status = "submitted"
                clip.remote_status = "submitted"
                return "task-b"

            with (
                patch.object(client, "_submit_clip", side_effect=fake_submit_clip) as submit,
                patch.object(
                    client,
                    "_resolve_clip_status_payload",
                    return_value={
                        "status": "succeeded",
                        "content": {"video_url": "https://example.com/seg-b.mp4"},
                    },
                ) as resolve_status,
                patch.object(client, "_complete_succeeded_clip") as complete_succeeded_clip,
            ):
                report = client.execute_manifest(
                    manifest,
                    force_submit=True,
                    segment_ids={"seg-b"},
                )

        submit.assert_called_once()
        resolve_status.assert_called_once()
        complete_succeeded_clip.assert_called_once()
        self.assertEqual(report.completed_count, 1)
        self.assertEqual(report.failed_count, 0)
        self.assertEqual(report.pending_count, 0)
        self.assertEqual(len(report.clip_results), 1)
        self.assertEqual(report.clip_results[0].segment_id, "seg-b")
        self.assertEqual(clip_a.remote_task_id, "")
        self.assertEqual(clip_b.remote_task_id, "task-b")


if __name__ == "__main__":
    unittest.main()
