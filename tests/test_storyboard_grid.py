from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.domains.video.contracts import SeedanceClipTask, SeedanceManifest, VideoSegment  # noqa: E402
from storyforge.pipelines.storyboard_grid import (  # noqa: E402
    _build_storyboard_reference_bindings,
    build_storyboard_grid_prompt,
    build_storyboard_scene_descriptions,
)
from storyforge.pipelines.video_reference_sync import sync_seedance_tail_frame_handoffs  # noqa: E402


class StoryboardGridPromptTestCase(unittest.TestCase):
    def test_scene_descriptions_keep_dialogue_after_nine_beat_limit(self) -> None:
        segment = _make_segment(
            timed_beats=[f"{index}-{index + 1}秒：动作{index}" for index in range(10)],
            dialogue_lines=["林屿：苏晚。"],
        )

        descriptions = build_storyboard_scene_descriptions(segment)

        self.assertEqual(len(descriptions), 9)
        self.assertIn("对白：林屿：苏晚。", descriptions[-1])
        self.assertTrue(descriptions[-1].startswith("格9"))

    def test_scene_descriptions_expand_sparse_beats_to_nine_cells(self) -> None:
        segment = _make_segment(
            timed_beats=[
                "0-2秒：林屿停在门口。",
                "2-5秒：林屿走向花径。",
                "5-8秒：苏晚抬头看向林屿。",
            ],
        )

        descriptions = build_storyboard_scene_descriptions(segment)

        self.assertEqual(len(descriptions), 9)
        self.assertTrue(descriptions[0].startswith("格1"))
        self.assertTrue(descriptions[-1].startswith("格9"))
        self.assertIn("画面演进", descriptions[0])
        self.assertIn("苏晚抬头看向林屿", descriptions[-1])
        self.assertIn("起始关键帧", descriptions[0])
        self.assertIn("推进关键帧", "\n".join(descriptions))
        self.assertIn("结果关键帧", "\n".join(descriptions))

    def test_scene_descriptions_remove_tail_frame_handoff_language(self) -> None:
        segment = _make_segment(
            timed_beats=[
                "0-3秒：承接上一场尾部，林屿站在长椅前与苏晚对视。",
                "3-8秒：林屿坐到长椅右侧。",
            ],
        )

        descriptions = build_storyboard_scene_descriptions(segment)
        combined = "\n".join(descriptions)

        self.assertNotIn("承接上一场", combined)
        self.assertNotIn("承接上一段", combined)
        self.assertIn("当前片段开场状态", combined)

    def test_grid_prompt_uses_selected_aspect_ratio(self) -> None:
        segment = _make_segment(timed_beats=["0-2秒：林屿走向花径。"])

        prompt = build_storyboard_grid_prompt(
            segment=segment,
            scene_descriptions=build_storyboard_scene_descriptions(segment),
            reference_bindings=[
                {
                    "label": "图片1",
                    "description": "场景母图",
                    "url": "https://example.com/scene.png",
                }
            ],
            uses_previous_last_frame=False,
            aspect_ratio="9:16",
        )

        self.assertIn("画面规格：9:16", prompt)
        self.assertNotIn("画面规格：横版 16:9", prompt)

    def test_tail_frame_is_available_for_grid_storyboard_video_generation(self) -> None:
        manifest = SeedanceManifest(
            title="尾帧测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc01-seg01",
                    title="上一段",
                    prompt="上一段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/seg01.mp4",
                    scene_id="ch01-sc01",
                    video_url="https://example.com/seg01.mp4",
                    last_frame_url="https://example.com/seg01-last.png",
                ),
                SeedanceClipTask(
                    segment_id="ch01-sc01-seg02",
                    title="九宫格段",
                    prompt="九宫格段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/seg02.mp4",
                    scene_id="ch01-sc01",
                    video_mode="grid_storyboard",
                ),
            ],
        )

        sync_seedance_tail_frame_handoffs(manifest)

        self.assertEqual(manifest.clips[1].previous_clip_segment_id, "ch01-sc01-seg01")
        self.assertEqual(manifest.clips[1].previous_clip_video_url, "https://example.com/seg01.mp4")
        self.assertEqual(manifest.clips[1].first_frame_url, "https://example.com/seg01-last.png")

    def test_storyboard_generation_references_exclude_tail_frame(self) -> None:
        clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg02",
            title="九宫格段",
            prompt="九宫格段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/seg02.mp4",
            scene_id="ch01-sc01",
            video_mode="grid_storyboard",
            scene_master_url="https://example.com/scene.png",
            first_frame_url="https://example.com/seg01-last.png",
            character_image_urls=["https://example.com/linyu.png"],
            visible_characters=["林屿"],
        )

        bindings = _build_storyboard_reference_bindings(clip)

        self.assertEqual([item["kind"] for item in bindings], ["scene_master", "character"])
        self.assertNotIn("https://example.com/seg01-last.png", [item["url"] for item in bindings])


def _make_segment(
    *,
    timed_beats: list[str],
    dialogue_lines: list[str] | None = None,
) -> VideoSegment:
    return VideoSegment(
        segment_id="ch01-sc01-seg01",
        chapter_number=1,
        scene_id="ch01-sc01",
        scene_title="花径",
        scene_summary="傍晚花径",
        scene_anchor="花径",
        title="靠近",
        summary="林屿走向花径。",
        involved_characters=["林屿"],
        narration="",
        dialogue_lines=dialogue_lines or [],
        subtitle_lines=[],
        sound_effects=[],
        music_direction="",
        timed_beats=timed_beats,
        duration_seconds=8,
    )
