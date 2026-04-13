from __future__ import annotations

from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import AppConfig  # noqa: E402
from storyforge.domains.novel.contracts import CharacterProfile, StoryBrief  # noqa: E402
from storyforge.domains.novel.heuristics import extract_role_labels_from_brief  # noqa: E402
from storyforge.domains.novel.prompts import (  # noqa: E402
    build_character_user_prompt,
    build_chapter_planner_user_prompt,
)
from storyforge.domains.novel.schemas import StoryArchitectureSchema  # noqa: E402
from storyforge.domains.novel.service import NovelGeneratorService  # noqa: E402
from storyforge.domains.video.contracts import CharacterVisualProfile, VideoSegment  # noqa: E402
from storyforge.domains.video.schemas import CharacterVisualBibleSchema, VideoSegmentPlanSchema  # noqa: E402
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from storyforge.integrations.seedance import SeedanceExecutionReport  # noqa: E402
from storyforge.integrations.seedream import SeedreamExecutionReport  # noqa: E402
from storyforge.pipelines.story_pipeline import run_story_pipeline  # noqa: E402
from storyforge.pipelines.video_pipeline import run_video_pipeline  # noqa: E402


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = ROOT / "tests/.tmp"
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)
        self.temp_root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)

    def test_story_and_video_pipeline(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        self.assertTrue(story_result.outline_path.exists())
        self.assertTrue((story_result.output_dir / "workflow_trace.json").exists())
        self.assertEqual(len(story_result.chapter_paths), brief.chapter_count)
        self.assertIsNotNone(story_result.novel_package.review)
        self.assertIn("story_architect", story_result.novel_package.workflow_trace)
        self.assertIn("story_drafter", story_result.novel_package.workflow_trace)
        self.assertIn("cast_analyzer", story_result.novel_package.workflow_trace)
        self.assertTrue(
            all(item.voice_profile.voice_style for item in story_result.novel_package.outline.characters)
        )
        self.assertTrue(
            all(item.voice_profile.timbre for item in story_result.novel_package.outline.characters)
        )
        self.assertTrue(
            all(item.voice_profile.forbidden_voice_changes for item in story_result.novel_package.outline.characters)
        )

        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
        )
        self.assertTrue(video_result.character_bible_path.exists())
        self.assertTrue(video_result.segment_plan_path.exists())
        self.assertTrue(video_result.manifest_path.exists())
        self.assertTrue(video_result.seedream_execution_path.exists())
        self.assertTrue(video_result.seedance_execution_path.exists())
        self.assertTrue(video_result.concat_script_path.exists())
        self.assertIsNone(video_result.full_story_path)
        self.assertGreater(len(video_result.project_package.segments), 0)
        self.assertGreater(len(video_result.project_package.seedance_manifest.clips), 0)
        self.assertEqual(
            {item.chapter_number for item in video_result.project_package.segments},
            {item.number for item in story_result.novel_package.outline.chapters},
        )
        self.assertTrue(
            all(item.dialogue_lines for item in video_result.project_package.segments)
        )
        self.assertTrue(
            all(item.subtitle_lines for item in video_result.project_package.segments)
        )
        self.assertTrue(
            all(item.sound_effects for item in video_result.project_package.segments)
        )
        self.assertTrue(
            all(item.music_direction for item in video_result.project_package.segments)
        )
        self.assertTrue(
            all(item.timed_beats for item in video_result.project_package.segments)
        )
        self.assertTrue(
            all("角色对白：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all("角色音色锁定：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all("禁止变化：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all("硬字幕样式：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all("硬字幕文案：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all("时间节拍：" in item.prompt for item in video_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all(item.image_kind == "turnaround_sheet" for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.use_as_reference for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.output_path.endswith("_sheet.png") for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.reference_images for item in video_result.project_package.scene_images)
        )
        self.assertTrue(
            all("角色锁定要求" in item.start_frame_prompt for item in video_result.project_package.scene_images)
        )
        self.assertTrue(
            all("稳定年龄感" in item.start_frame_prompt for item in video_result.project_package.scene_images)
        )
        self.assertTrue(
            all("稳定肩宽" in item.start_frame_prompt for item in video_result.project_package.scene_images)
        )
        self.assertFalse(video_result.seedream_execution.submitted)
        self.assertFalse(video_result.seedance_execution.submitted)

    @patch("storyforge.pipelines.video_pipeline.concat_manifest_clips")
    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_character_images")
    def test_video_pipeline_auto_concats_full_story_after_successful_seedance(
        self,
        mock_generate_character_images,
        mock_generate_scene_images,
        mock_execute_manifest,
        mock_concat_manifest_clips,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        def fake_generate_character_images(project_package, force_submit=False):
            self.assertTrue(force_submit)
            for item in project_package.character_images:
                item.generated_url = f"https://example.com/{Path(item.output_path).name}"
                item.status = "completed"
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=3,
                failed_count=0,
                note="ok",
            )

        def fake_generate_scene_images(project_package, force_submit=False):
            self.assertTrue(force_submit)
            for item in project_package.scene_images:
                item.start_frame_url = f"https://example.com/{Path(item.start_frame_path).name}"
                item.end_frame_url = f"https://example.com/{Path(item.end_frame_path).name}"
                item.status = "completed"
            for clip in project_package.seedance_manifest.clips:
                clip.start_frame_url = f"https://example.com/{Path(clip.start_frame_path).name}"
                clip.end_frame_url = f"https://example.com/{Path(clip.end_frame_path).name}"
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=3,
                failed_count=0,
                note="ok",
            )

        mock_generate_character_images.side_effect = fake_generate_character_images
        mock_generate_scene_images.side_effect = fake_generate_scene_images

        def fake_execute_manifest(manifest, force_submit=False):
            self.assertTrue(force_submit)
            for clip in manifest.clips:
                clip_path = Path(clip.output_path)
                clip_path.parent.mkdir(parents=True, exist_ok=True)
                clip_path.write_bytes(b"fake mp4 bytes")
                clip.downloaded_path = clip.output_path
                clip.submit_status = "completed"
                clip.remote_status = "succeeded"
            return SeedanceExecutionReport(
                submitted=True,
                manifest_title=manifest.title,
                completed_count=len(manifest.clips),
                failed_count=0,
                pending_count=0,
                note="ok",
            )

        mock_execute_manifest.side_effect = fake_execute_manifest

        expected_full_story_path = story_result.output_dir / "rendered" / "full_story.mp4"

        def fake_concat_manifest_clips(manifest, concat_list_path, output_path):
            self.assertTrue(concat_list_path.exists())
            self.assertEqual(output_path, expected_full_story_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"merged video bytes")
            return output_path

        mock_concat_manifest_clips.side_effect = fake_concat_manifest_clips

        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
        )

        self.assertEqual(video_result.full_story_path, expected_full_story_path)
        self.assertTrue(expected_full_story_path.exists())
        self.assertEqual(len(video_result.rendered_clip_paths), len(video_result.manifest.clips))
        mock_concat_manifest_clips.assert_called_once()

    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_character_images")
    def test_video_pipeline_skips_seedance_when_required_frames_fail(
        self,
        mock_generate_character_images,
        mock_generate_scene_images,
        mock_execute_manifest,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        mock_generate_character_images.return_value = SeedreamExecutionReport(
            submitted=True,
            generated_count=3,
            failed_count=0,
            note="ok",
        )
        mock_generate_scene_images.return_value = SeedreamExecutionReport(
            submitted=True,
            generated_count=0,
            failed_count=1,
            note="failed",
        )

        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
        )

        self.assertFalse(video_result.seedance_execution.submitted)
        self.assertIn("Seedream", video_result.seedance_execution.note)
        mock_execute_manifest.assert_not_called()

    def test_generic_character_aliases_are_normalized_to_real_names(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = CharacterVisualBibleSchema.model_validate(
            {
                "characters": [
                    {
                        "name": story_result.novel_package.outline.characters[0].name,
                        "role": story_result.novel_package.outline.characters[0].role,
                        "gender": story_result.novel_package.outline.characters[0].gender,
                        "appearance": "测试外观",
                        "outfit": "测试服装",
                        "color_palette": ["蓝色"],
                        "portrait_prompt": "测试 prompt",
                    }
                ]
            }
        )
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "seg-01",
                        "chapter_number": 1,
                        "title": "测试片段",
                        "summary": "主角进入车站。",
                        "involved_characters": ["主角"],
                        "narration": "主角看向远处。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["主角看向远处。"],
                        "sound_effects": ["风声"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": ["0-2秒：主角进入站台。"],
                        "scene_prompt": "主角站在雾中。",
                        "start_frame_prompt": "主角背影。",
                        "end_frame_prompt": "主角回头。",
                        "duration_seconds": 5,
                    }
                ]
            }
        )

        normalized = service._normalize_segment_characters(
            raw_plan,
            story_result.novel_package,
            visual_bible,
        )

        expected_name = story_result.novel_package.outline.characters[0].name
        segment = normalized.segments[0]
        self.assertEqual(segment.involved_characters, [expected_name])
        self.assertIn(expected_name, segment.scene_prompt)
        self.assertIn(expected_name, segment.start_frame_prompt)

    def test_legacy_voice_style_is_upgraded_to_structured_voice_profile(self) -> None:
        profile = CharacterProfile.from_dict(
            {
                "name": "林雪",
                "role": "信使",
                "desire": "送达密函",
                "conflict": "追兵逼近",
                "arc": "从逃避到承担",
                "visual_signature": ["深蓝", "风雪"],
                "voice_style": "冷静克制，低声短句推进信息",
                "image_prompt": "雪港信使设定图",
            }
        )

        self.assertEqual(profile.voice_style, "冷静克制，低声短句推进信息")
        self.assertEqual(profile.voice_profile.voice_style, "冷静克制，低声短句推进信息")
        self.assertTrue(profile.voice_profile.forbidden_voice_changes)

    def test_visual_bible_names_are_repaired_to_outline_characters(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        drifted_bible = CharacterVisualBibleSchema.model_validate(
            {
                "characters": [
                    {
                        "name": "林雨",
                        "role": story_result.novel_package.outline.characters[0].role,
                        "gender": story_result.novel_package.outline.characters[0].gender,
                        "appearance": "测试外观",
                        "outfit": "测试服装",
                        "color_palette": ["蓝色"],
                        "portrait_prompt": "林雨站在雾中",
                    }
                ]
            }
        )

        repaired = service._repair_character_visual_bible(
            drifted_bible,
            story_result.novel_package,
        )

        self.assertEqual(
            [item.name for item in repaired.characters],
            [item.name for item in story_result.novel_package.outline.characters],
        )

    def test_confession_segment_is_upgraded_to_two_involved_characters(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        first_character = story_result.novel_package.outline.characters[0]
        second_character = story_result.novel_package.outline.characters[1]
        story_result.novel_package.outline.chapters[0].featured_characters = [
            first_character.name,
            second_character.name,
        ]
        visual_bible = CharacterVisualBibleSchema.model_validate(
            {
                "characters": [
                    {
                        "name": first_character.name,
                        "role": first_character.role,
                        "gender": first_character.gender,
                        "appearance": "测试外观",
                        "outfit": "测试服装",
                        "color_palette": ["蓝色"],
                        "portrait_prompt": "测试 prompt",
                    },
                    {
                        "name": second_character.name,
                        "role": second_character.role,
                        "gender": second_character.gender,
                        "appearance": "测试外观",
                        "outfit": "测试服装",
                        "color_palette": ["红色"],
                        "portrait_prompt": "测试 prompt",
                    },
                ]
            }
        )
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "confession-01",
                        "chapter_number": 1,
                        "title": "雨棚下的告白",
                        "summary": "她终于在雨夜里向对方告白。",
                        "involved_characters": [first_character.name],
                        "narration": "雨棚下，她终于鼓起勇气把压在心里的话说出口。",
                        "dialogue_lines": [f"{first_character.name}：我喜欢你很久了。"],
                        "subtitle_lines": ["雨棚下，她终于鼓起勇气把压在心里的话说出口。"],
                        "sound_effects": ["雨声"],
                        "music_direction": "克制但上扬",
                        "timed_beats": ["0-5秒：她在雨声里告白。"],
                        "scene_prompt": "雨棚下的双人告白场景。",
                        "start_frame_prompt": "她看向对方，准备开口。",
                        "end_frame_prompt": "两人之间的气氛被告白打破。",
                        "duration_seconds": 5,
                    }
                ]
            }
        )

        normalized = service._normalize_segment_characters(
            raw_plan,
            story_result.novel_package,
            visual_bible,
        )

        segment = normalized.segments[0]
        self.assertEqual(segment.involved_characters[:2], [first_character.name, second_character.name])
        self.assertEqual(len(segment.involved_characters), 2)

    def test_romance_brief_repairs_primary_character_genders_to_male_female_pair(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一个男生终于在雨夜向喜欢的女生告白。",
            genre="校园恋爱",
            tone="青春、克制",
            chapter_count=1,
            total_word_target=1500,
        )
        architecture = StoryArchitectureSchema(
            title="雨夜告白",
            premise="雨夜里迟到的告白。",
            theme="勇气与回应",
            setting="高中校园",
            story_engine="双人关系推进",
            visual_motifs=["雨", "路灯"],
            tone_notes=["青春"],
        )
        cast_analysis = service._fallback_cast_analysis(brief, architecture)
        roster = service._fallback_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "characters": [
                    service._fallback_character_roster(
                        brief,
                        architecture,
                        cast_analysis=cast_analysis,
                    ).characters[0].model_copy(
                        update={"name": "程野", "gender": "男", "image_prompt": "程野，男，高中生。"}
                    ),
                    service._fallback_character_roster(
                        brief,
                        architecture,
                        cast_analysis=cast_analysis,
                    ).characters[1].model_copy(
                        update={"name": "周沉", "gender": "男", "image_prompt": "周沉，男，高中生。"}
                    ),
                ]
            }
        )

        repaired = service._repair_character_roster(
            roster,
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )

        self.assertEqual(repaired.characters[0].gender, "男")
        self.assertEqual(repaired.characters[1].gender, "女")
        self.assertIn("性别：女", repaired.characters[1].image_prompt)

    def test_dual_lead_prompt_forbids_single_character_roster(self) -> None:
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一个女生终于在雨夜向喜欢的男生告白。",
            genre="校园恋爱",
            tone="青春、克制",
            chapter_count=1,
            total_word_target=1500,
        )
        architecture = StoryArchitectureSchema(
            title="雨夜告白",
            premise="雨夜里迟到的告白。",
            theme="勇气与回应",
            setting="高中校园",
            story_engine="双人关系推进",
            visual_motifs=["雨", "路灯"],
            tone_notes=["青春"],
        )
        cast_analysis = NovelGeneratorService()._fallback_cast_analysis(
            brief,
            architecture,
        )

        prompt = build_character_user_prompt(
            brief,
            '{"title":"雨夜告白"}',
            cast_analysis=cast_analysis,
            story_draft_context="- 第 1 章《雨夜》 摘要：女生在雨夜向男生告白。",
        )

        self.assertIn("characters 数组前两位必须就是这段关系的双方", prompt)
        self.assertIn("不得只输出单主角", prompt)
        self.assertIn("cast_slot_id", prompt)
        self.assertIn("必须以上游 Cast Analysis 结果为准", prompt)
        self.assertIn("source_evidence", prompt)
        self.assertIn("已生成小说草稿", prompt)

    def test_dual_lead_repair_preserves_gender_order_from_brief(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一个女生终于在雨夜向喜欢的男生告白。",
            genre="校园恋爱",
            tone="青春、克制",
            chapter_count=1,
            total_word_target=1500,
        )
        architecture = StoryArchitectureSchema(
            title="雨夜告白",
            premise="雨夜里迟到的告白。",
            theme="勇气与回应",
            setting="高中校园",
            story_engine="双人关系推进",
            visual_motifs=["雨", "路灯"],
            tone_notes=["青春"],
        )
        cast_analysis = service._fallback_cast_analysis(brief, architecture)
        roster = service._fallback_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "characters": [
                    service._fallback_character_roster(
                        brief,
                        architecture,
                        cast_analysis=cast_analysis,
                    ).characters[0].model_copy(
                        update={"name": "程野", "gender": "男", "image_prompt": "程野，男，高中生。"}
                    )
                ]
            }
        )

        repaired = service._repair_character_roster(
            roster,
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )

        self.assertGreaterEqual(len(repaired.characters), 2)
        self.assertEqual(repaired.characters[0].gender, "女")
        self.assertEqual(repaired.characters[1].gender, "男")
        self.assertIn("关系定位", repaired.characters[0].image_prompt)
        self.assertIn("关系定位", repaired.characters[1].image_prompt)

    def test_dual_lead_chapter_prompt_requires_both_sides(self) -> None:
        brief = StoryBrief(
            title_hint="重逢站台",
            idea="她和多年未见的前任在站台重逢，并必须在列车离开前说清真相。",
            genre="都市情感",
            tone="克制、拉扯",
            chapter_count=2,
            total_word_target=3000,
        )
        architecture = StoryArchitectureSchema(
            title="重逢站台",
            premise="站台重逢。",
            theme="错过与坦白",
            setting="列车站台",
            story_engine="双人关系推进",
            visual_motifs=["站台", "列车"],
            tone_notes=["克制"],
        )
        cast_analysis = NovelGeneratorService()._fallback_cast_analysis(
            brief,
            architecture,
        )

        prompt = build_chapter_planner_user_prompt(
            brief=brief,
            architecture_summary='{"title":"重逢站台"}',
            character_summary='{"characters":[]}',
            cast_analysis=cast_analysis,
            story_draft_context="- 第 1 章《站台》 摘要：她与前任在站台重逢。",
        )

        self.assertIn("featured_characters 前两位必须优先放关系双方", prompt)
        self.assertIn("不能只写单人心理活动", prompt)
        self.assertIn("已生成小说草稿", prompt)
        self.assertIn("必须以上游 Cast Analysis 结果为准", prompt)

    def test_dual_lead_chapter_repair_adds_counterpart_from_brief(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一个女生终于在雨夜向喜欢的男生告白。",
            genre="校园恋爱",
            tone="青春、克制",
            chapter_count=1,
            total_word_target=1500,
        )
        architecture = StoryArchitectureSchema(
            title="雨夜告白",
            premise="雨夜里迟到的告白。",
            theme="勇气与回应",
            setting="高中校园",
            story_engine="双人关系推进",
            visual_motifs=["雨", "路灯"],
            tone_notes=["青春"],
        )
        cast_analysis = service._fallback_cast_analysis(brief, architecture)
        roster = service._fallback_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )
        chapter_plan_set = service._fallback_chapter_plan_set(
            brief,
            roster,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "chapters": [
                    service._fallback_chapter_plan_set(
                        brief,
                        roster,
                        cast_analysis=cast_analysis,
                    ).chapters[0].model_copy(
                        update={
                            "title": "雨棚下",
                            "summary": "她终于决定把心里的话说出口。",
                            "key_conflict": "她不确定自己是否会被拒绝。",
                            "beats": ["她在雨棚下反复练习开口。"],
                            "featured_characters": [roster.characters[0].name],
                        }
                    )
                ]
            }
        )

        repaired = service._repair_chapter_plan_set(
            chapter_plan_set,
            brief,
            roster,
            cast_analysis=cast_analysis,
        )

        self.assertEqual(
            repaired.chapters[0].featured_characters[:2],
            [roster.characters[0].name, roster.characters[1].name],
        )

    def test_cast_analysis_is_primary_cast_contract(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="边界之夜",
            idea="她终于决定越过那条谁都不敢点破的边界。",
            genre="情感短篇",
            tone="克制、暧昧",
            chapter_count=1,
            total_word_target=1500,
        )
        architecture = StoryArchitectureSchema(
            title="边界之夜",
            premise="边界被越过的夜晚。",
            theme="压抑与越界",
            setting="毕业夜晚",
            story_engine="关系推进",
            visual_motifs=["路灯", "夏夜"],
            tone_notes=["克制"],
        )
        cast_analysis = service._repair_cast_analysis(
            service._fallback_cast_analysis(brief, architecture).model_copy(
                update={
                    "story_shape": "dual_relationship_with_supporting_cast",
                    "requires_dual_leads": True,
                    "explicit_counterpart": True,
                    "recommended_core_cast_count": 2,
                }
            ),
            brief,
            architecture,
        )

        prompt = build_character_user_prompt(
            brief,
            architecture.model_dump_json(),
            cast_analysis=cast_analysis,
        )

        self.assertIn("必须以上游 Cast Analysis 结果为准", prompt)
        self.assertIn("不得只输出单主角", prompt)

    def test_cast_analysis_supports_multi_role_story_structure(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="旧城回响",
            idea="一名记者回到旧城调查父亲失踪真相，昔日恋人、线人和地方势力相继卷入。",
            genre="悬疑剧情",
            tone="克制、压迫",
            chapter_count=4,
            total_word_target=9000,
        )
        architecture = StoryArchitectureSchema(
            title="旧城回响",
            premise="记者回旧城追查失踪真相。",
            theme="真相、背叛与旧情",
            setting="旧工业城市",
            story_engine="调查推进不断卷出旧关系网络",
            visual_motifs=["旧厂房", "雨夜"],
            tone_notes=["压迫"],
        )

        cast_analysis = service._fallback_cast_analysis(brief, architecture)

        self.assertGreaterEqual(cast_analysis.recommended_core_cast_count, 4)
        self.assertGreaterEqual(len(cast_analysis.slots), 3)
        self.assertEqual(cast_analysis.slots[0].tier, "lead")

    def test_extract_role_labels_from_complex_brief(self) -> None:
        brief = StoryBrief(
            title_hint="旧城回响",
            idea="一名记者回到旧城调查父亲失踪真相，昔日恋人、地下线人、地方势力继承人和掌握档案的退休警察相继卷入。",
            genre="悬疑剧情",
            tone="克制、压迫",
            chapter_count=3,
            total_word_target=6000,
        )

        labels = extract_role_labels_from_brief(brief)

        self.assertIn("记者", labels)
        self.assertIn("昔日恋人", labels)
        self.assertIn("地下线人", labels)
        self.assertIn("地方势力继承人", labels)
        self.assertIn("掌握档案的退休警察", labels)

    def test_fallback_cast_analysis_uses_grounded_role_labels(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="旧城回响",
            idea="一名记者回到旧城调查父亲失踪真相，昔日恋人、地下线人、地方势力继承人和掌握档案的退休警察相继卷入。",
            genre="悬疑剧情",
            tone="克制、压迫",
            chapter_count=3,
            total_word_target=6000,
        )
        architecture = StoryArchitectureSchema(
            title="旧城回响",
            premise="记者回旧城追查失踪真相。",
            theme="真相、背叛与旧情",
            setting="旧工业城市",
            story_engine="调查推进不断卷出旧关系网络",
            visual_motifs=["旧厂房", "雨夜"],
            tone_notes=["压迫"],
        )

        cast_analysis = service._fallback_cast_analysis(brief, architecture)
        slot_labels = [item.brief_label for item in cast_analysis.slots[:4]]

        self.assertEqual(slot_labels[0], "记者")
        self.assertIn("昔日恋人", slot_labels)
        self.assertIn("地下线人", slot_labels)
        self.assertTrue(any(item.source_evidence for item in cast_analysis.slots[:3]))

    def test_dual_lead_alias_maps_counterpart_to_second_character(self) -> None:
        service = NovelGeneratorService()
        resolved = service._resolve_roster_name(
            raw_name="被告白的人",
            canonical_names=["林雾", "沈砚"],
            role_map={"林雾": "关系主动方 / 叙事发起者", "沈砚": "关系对位角色 / 关键回应方"},
        )

        self.assertEqual(resolved, "沈砚")

    def test_missing_chapters_are_repaired_back_into_segment_plan(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = service._fallback_character_visual_bible(story_result.novel_package)
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "only-ch01",
                        "chapter_number": 1,
                        "title": "只给第一章",
                        "summary": "主角进入车站。",
                        "involved_characters": [story_result.novel_package.outline.characters[0].name],
                        "narration": "主角看向远处。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["主角看向远处。"],
                        "sound_effects": ["风声"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": ["0-2秒：主角进入站台。"],
                        "scene_prompt": "主角站在雾中。",
                        "start_frame_prompt": "主角背影。",
                        "end_frame_prompt": "主角回头。",
                        "duration_seconds": 5,
                    }
                ]
            }
        )

        repaired = service._repair_segment_plan(
            raw_plan,
            story_result.novel_package,
            visual_bible,
        )

        self.assertEqual(
            {item.chapter_number for item in repaired.segments},
            {item.number for item in story_result.novel_package.outline.chapters},
        )

    def test_segment_planner_prompt_leaves_segments_per_chapter_to_llm(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        prompt = service._build_segment_planner_user_prompt(story_result.novel_package)

        self.assertIn("同一章节可以拆成 1 段、2 段、3 段或更多", prompt)
        self.assertIn("必须由你根据该章正文内容自行判断", prompt)
        self.assertNotIn("推荐最少片段数", prompt)

    def test_repair_segment_plan_preserves_all_llm_segments_within_same_chapter(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = service._fallback_character_visual_bible(story_result.novel_package)
        lead_name = story_result.novel_package.outline.characters[0].name
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "ch01-seg01",
                        "chapter_number": 1,
                        "title": "第一章片段一",
                        "summary": "第一章的开场。",
                        "involved_characters": [lead_name],
                        "narration": "第一章的开场。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["第一章的开场。"],
                        "sound_effects": ["风声"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": ["0-2秒：第一章的开场。"],
                        "scene_prompt": "第一章片段一。",
                        "start_frame_prompt": "第一章片段一起始。",
                        "end_frame_prompt": "第一章片段一结束。",
                        "duration_seconds": 5,
                    },
                    {
                        "segment_id": "ch01-seg02",
                        "chapter_number": 1,
                        "title": "第一章片段二",
                        "summary": "第一章的推进。",
                        "involved_characters": [lead_name],
                        "narration": "第一章的推进。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["第一章的推进。"],
                        "sound_effects": ["脚步声"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": ["0-2秒：第一章的推进。"],
                        "scene_prompt": "第一章片段二。",
                        "start_frame_prompt": "第一章片段二起始。",
                        "end_frame_prompt": "第一章片段二结束。",
                        "duration_seconds": 5,
                    },
                    {
                        "segment_id": "ch01-seg03",
                        "chapter_number": 1,
                        "title": "第一章片段三",
                        "summary": "第一章的收束。",
                        "involved_characters": [lead_name],
                        "narration": "第一章的收束。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["第一章的收束。"],
                        "sound_effects": ["低频嗡鸣"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": ["0-2秒：第一章的收束。"],
                        "scene_prompt": "第一章片段三。",
                        "start_frame_prompt": "第一章片段三起始。",
                        "end_frame_prompt": "第一章片段三结束。",
                        "duration_seconds": 5,
                    },
                ]
            }
        )

        repaired = service._repair_segment_plan(
            raw_plan,
            story_result.novel_package,
            visual_bible,
        )

        self.assertEqual(
            [item.segment_id for item in repaired.segments[:3]],
            ["ch01-seg01", "ch01-seg02", "ch01-seg03"],
        )
        self.assertGreaterEqual(
            len([item for item in repaired.segments if item.chapter_number == 1]),
            3,
        )

    def test_long_segments_are_split_to_seedance_safe_clips(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "snowport_01",
                        "chapter_number": 1,
                        "title": "雪港测试",
                        "summary": "信使在雪港中逃亡。",
                        "involved_characters": ["林雪"],
                        "narration": "暴风雪封港。信使在巷道中躲避追兵。她必须在天亮前送达密函。",
                        "dialogue_lines": [
                            "卫兵：站住！",
                            "信使：别过来！",
                            "卫兵：她跑不远！",
                        ],
                        "subtitle_lines": [
                            "暴风雪封港",
                            "信使在巷道中躲避追兵",
                            "她必须在天亮前送达密函",
                        ],
                        "sound_effects": ["风雪声", "脚步声", "追兵叫喊"],
                        "music_direction": "紧张弦乐",
                        "timed_beats": [
                            "0-5秒：雪港全景。",
                            "5-10秒：信使冲入巷道。",
                            "10-15秒：追兵逼近。",
                            "15-20秒：她翻越木箱。",
                            "20-25秒：短暂停下喘息。",
                            "25-30秒：继续向灯塔方向逃离。",
                        ],
                        "scene_prompt": "雪港巷道追逐，冷色调。",
                        "start_frame_prompt": "雪港远景。",
                        "end_frame_prompt": "信使回头望向追兵。",
                        "duration_seconds": 30,
                    }
                ]
            }
        )

        normalized = service._normalize_segments_for_seedance(raw_plan)

        self.assertEqual(len(normalized.segments), 3)
        self.assertTrue(all(2 <= item.duration_seconds <= 12 for item in normalized.segments))
        self.assertEqual(
            [item.duration_seconds for item in normalized.segments],
            [10, 10, 10],
        )
        self.assertEqual(
            [item.segment_id for item in normalized.segments],
            ["snowport_01_01", "snowport_01_02", "snowport_01_03"],
        )
        self.assertEqual(
            [item.source_segment_id for item in normalized.segments],
            ["snowport_01", "snowport_01", "snowport_01"],
        )
        self.assertEqual(
            [item.subsegment_index for item in normalized.segments],
            [1, 2, 3],
        )
        self.assertEqual(
            [item.subsegment_count for item in normalized.segments],
            [3, 3, 3],
        )
        self.assertEqual(
            [item.reuse_previous_end_frame for item in normalized.segments],
            [False, True, True],
        )
        self.assertTrue(all(item.timed_beats for item in normalized.segments))
        self.assertTrue(all(item.subtitle_lines for item in normalized.segments))
        self.assertTrue(all("当前子片段" in item.start_frame_prompt for item in normalized.segments))

        segments = [VideoSegment.from_dict(item.model_dump()) for item in normalized.segments]
        character_profiles = [
            CharacterVisualProfile(
                name="林雪",
                role="信使",
                gender="女",
                appearance="测试外观",
                outfit="测试服装",
                color_palette=["深蓝"],
                portrait_prompt="测试角色图",
            )
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}
        scene_tasks = service._build_scene_image_tasks(
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertFalse(scene_tasks[0].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[0].continuity_source_segment_id, "")
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "snowport_01_01")
        self.assertTrue(scene_tasks[2].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[2].continuity_source_segment_id, "snowport_01_02")

    def test_planned_segment_runtime_within_range_is_preserved(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=8,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "ch01-seg01",
                        "chapter_number": 1,
                        "title": "长时长测试",
                        "summary": "主角进入废弃戏院。",
                        "involved_characters": ["林默"],
                        "narration": "林默推门而入，雨声灌进长廊。",
                        "dialogue_lines": ["林默：这里还有电。"],
                        "subtitle_lines": ["林默推门而入", "雨声灌进长廊"],
                        "sound_effects": ["雨声", "脚步声"],
                        "music_direction": "悬疑氛围",
                        "timed_beats": [
                            "0-3秒：林默进入戏院大厅。",
                            "3-5秒：他沿着走廊继续前进。",
                            "5-8秒：他在舞台前停下。",
                        ],
                        "scene_prompt": "暴雨中的废弃戏院大厅。",
                        "start_frame_prompt": "林默推开戏院大门。",
                        "end_frame_prompt": "林默停在舞台前方。",
                        "duration_seconds": 8,
                    }
                ]
            }
        )

        normalized = service._normalize_segments_for_seedance(raw_plan)

        self.assertEqual(len(normalized.segments), 1)
        self.assertEqual(normalized.segments[0].segment_id, "ch01-seg01")
        self.assertEqual(normalized.segments[0].duration_seconds, 8)
        self.assertEqual(
            normalized.segments[0].timed_beats,
            [
                "0-3秒：林默进入戏院大厅。",
                "3-5秒：他沿着走廊继续前进。",
                "5-8秒：他在舞台前停下。",
            ],
        )

    def test_adjacent_segments_in_same_chapter_reuse_previous_end_frame_when_continuous(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        segments = [
            VideoSegment(
                segment_id="ch01-seg01",
                chapter_number=1,
                title="片段一",
                summary="林雪冲进雪港巷道。",
                involved_characters=["林雪"],
                narration="林雪在巷道里逃亡。",
                dialogue_lines=[],
                subtitle_lines=["林雪在巷道里逃亡。"],
                sound_effects=["脚步声"],
                music_direction="紧张",
                timed_beats=["0-5秒：林雪冲进巷道。"],
                scene_prompt="雪港巷道，冷色调。",
                start_frame_prompt="林雪进入巷道。",
                end_frame_prompt="林雪回头确认追兵位置。",
                duration_seconds=5,
                transition_hint="auto",
                source_segment_id="ch01-seg01",
            ),
            VideoSegment(
                segment_id="ch01-seg02",
                chapter_number=1,
                title="片段二",
                summary="林雪继续沿着同一条巷道前进。",
                involved_characters=["林雪"],
                narration="她没有停下，只能继续向前。",
                dialogue_lines=[],
                subtitle_lines=["她没有停下，只能继续向前。"],
                sound_effects=["急促呼吸"],
                music_direction="紧张",
                timed_beats=["0-5秒：林雪继续前冲。"],
                scene_prompt="同一条雪港巷道，镜头跟拍。",
                start_frame_prompt="延续上一镜头，林雪继续奔跑。",
                end_frame_prompt="林雪冲向巷口。",
                duration_seconds=5,
                transition_hint="auto",
                source_segment_id="ch01-seg02",
            ),
            VideoSegment(
                segment_id="ch01-seg03",
                chapter_number=1,
                title="片段三",
                summary="与此同时，另一边的哨塔响起警报。",
                involved_characters=["哨兵"],
                narration="转场到哨塔，警报声突然响起。",
                dialogue_lines=[],
                subtitle_lines=["转场到哨塔，警报声突然响起。"],
                sound_effects=["警报声"],
                music_direction="压迫",
                timed_beats=["0-5秒：哨塔警报。"],
                scene_prompt="另一边的哨塔，红灯闪烁。",
                start_frame_prompt="镜头切到哨塔内部。",
                end_frame_prompt="哨兵拉动警报杆。",
                duration_seconds=5,
                transition_hint="cut",
                source_segment_id="ch01-seg03",
            ),
        ]
        character_profiles = [
            CharacterVisualProfile(
                name="林雪",
                role="信使",
                gender="女",
                appearance="测试外观",
                outfit="测试服装",
                color_palette=["深蓝"],
                portrait_prompt="测试角色图",
            ),
            CharacterVisualProfile(
                name="哨兵",
                role="守卫",
                gender="男",
                appearance="测试外观",
                outfit="测试服装",
                color_palette=["灰黑"],
                portrait_prompt="测试角色图",
            ),
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}

        scene_tasks = service._build_scene_image_tasks(
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertEqual(scene_tasks[0].continuity_source_segment_id, "")
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "ch01-seg01")
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[2].continuity_source_segment_id, "")
        self.assertFalse(scene_tasks[2].reuse_previous_end_frame)


if __name__ == "__main__":
    unittest.main()
