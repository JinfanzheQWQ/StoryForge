from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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

    def test_build_payload_uses_live_validated_shape(self) -> None:
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
            start_frame_path="start.png",
            end_frame_path="end.png",
            start_frame_url="https://example.com/start.png",
            end_frame_url="https://example.com/end.png",
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
        self.assertEqual(payload["content"][0], {"type": "text", "text": clip.prompt})
        self.assertEqual(payload["content"][1]["role"], "first_frame")
        self.assertEqual(payload["content"][2]["role"], "last_frame")

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
            start_frame_path="start.png",
            end_frame_path="end.png",
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
                start_frame_path="start.png",
                end_frame_path="end.png",
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
                start_frame_path="start.png",
                end_frame_path="end.png",
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


if __name__ == "__main__":
    unittest.main()
