from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storyforge.core.config import AppConfig  # noqa: E402
from storyforge.core.io import read_json  # noqa: E402
from storyforge.agents.base import PromptRequest  # noqa: E402
from storyforge.domains.novel.contracts import CharacterProfile, StoryBrief, StorySourcePackage  # noqa: E402
from storyforge.domains.novel.errors import (  # noqa: E402
    NovelStructuredGenerationError,
)
from storyforge.domains.novel.heuristics import extract_role_labels_from_brief  # noqa: E402
from storyforge.domains.novel.prompts import (  # noqa: E402
    build_character_user_prompt,
    build_chapter_planner_user_prompt,
)
from storyforge.domains.novel.schemas import (  # noqa: E402
    CastAnalysisSchema,
    CastRelationshipSchema,
    CastSlotSchema,
    ChapterDraftSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    StoryArchitectureSchema,
    StoryDraftSetSchema,
)
from storyforge.domains.novel.service import NovelGeneratorService  # noqa: E402
from storyforge.domains.video.contracts import CharacterVisualProfile, ContinuityLink, MotionPlan, SceneBible, SceneTransitionContract, ShotState, StoryMemoryPackage, VideoScene, VideoSegment  # noqa: E402
from storyforge.domains.video.errors import SegmentActionSplitRequiredError, VideoStructuredGenerationError  # noqa: E402
from storyforge.domains.video.schemas import (  # noqa: E402
    ChapterCoveragePlanSchema,
    ChapterCoverageEventSplitPlanSchema,
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    CharacterVisualBibleSchema,
    SegmentContinuityRepairSchema,
    SceneSegmentChunkSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentContractBatchSchema,
    VideoSegmentPlanSchema,
)  # noqa: E402
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from storyforge.integrations.seedance import SeedanceExecutionReport  # noqa: E402
from storyforge.integrations.seedream import SeedreamClient, SeedreamExecutionReport  # noqa: E402
from storyforge.pipelines.continuity import (  # noqa: E402
    ContinuitySoftIssueSchema,
    ContinuitySoftReviewSchema,
    write_continuity_report,
)
from storyforge.pipelines.story_pipeline import (  # noqa: E402
    run_story_generation_pipeline,
    run_story_scene_structure_pipeline,
    run_story_segment_contracts_pipeline,
)
from storyforge.pipelines.story_files import clear_story_derived_artifacts  # noqa: E402
from storyforge.pipelines.video_pipeline import (  # noqa: E402
    reset_scene_execution_contracts_for_repair,
    run_character_image_pipeline,
    run_scene_continuity_repair_pipeline,
    run_segment_continuity_repair_pipeline,
    run_scene_image_pipeline,
    run_video_merge_pipeline,
    run_video_render_pipeline,
)
from storyforge.pipelines.video_planning import (  # noqa: E402
    build_video_planning_artifacts,
    load_segment_contract_progress,
    load_video_planning_artifacts,
)
from storyforge.pipelines.video_support import should_skip_seedance_after_seedream  # noqa: E402
from _deterministic_backends import (  # noqa: E402
    DeterministicStoryBackend,
    DeterministicVideoBackend,
)
from _deterministic_novel_builders import DeterministicNovelBuilder  # noqa: E402
from _video_test_artifacts import (  # noqa: E402
    ensure_secondary_segment_execution_contract,
    mark_first_scene_and_video_failed,
    mark_rendered_manifest_clips,
    mark_runtime_character_images_completed,
    mark_runtime_manifest_clips_completed,
    mark_runtime_scene_images_completed,
    mark_runtime_scene_master_frames_completed,
    mark_scene_images_completed,
    mark_seedance_clips_completed,
)


def build_test_visual_bible(novel_package) -> CharacterVisualBibleSchema:
    return CharacterVisualBibleSchema.model_validate(
        {
            "characters": [
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                    "appearance": (
                        f"{item.gender}，具有明确轮廓、情绪感和电影感的角色外观，年龄段和体态稳定"
                    ),
                    "outfit": "带有故事气味的功能性服装，适合持续出镜",
                    "color_palette": item.visual_signature or novel_package.outline.visual_motifs[:2],
                    "portrait_prompt": item.image_prompt
                    or f"{item.name}，{item.role}，电影级肖像，{novel_package.brief.tone}",
                }
                for item in novel_package.outline.characters
            ]
        }
    )


@dataclass(slots=True)
class StoryStageBundle:
    output_dir: Path
    story_source_path: Path
    novel_package_path: Path
    novel_audit_path: Path
    story_memory_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    seedance_manifest_path: Path
    story_source: StorySourcePackage
    novel_package: object
    video_planning: object


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        class ContinuityBackend:
            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                return schema()

        self.story_backend = DeterministicStoryBackend()
        self.video_backend = DeterministicVideoBackend()
        self.novel_builder = DeterministicNovelBuilder()
        self._continuity_backend_patcher = patch(
            "storyforge.pipelines.continuity.build_agent_backend",
            return_value=ContinuityBackend(),
        )
        self._continuity_backend_patcher.start()
        self.addCleanup(self._continuity_backend_patcher.stop)
        self.temp_root = ROOT / "tests/.tmp"
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)
        self.temp_root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)

    def _run_story_pipeline(self, **kwargs):
        config = kwargs.pop("config")
        project_root = kwargs.pop("project_root", ROOT)
        output_root = kwargs.pop("output_root", self.temp_root)
        backend = kwargs.pop("backend", self.story_backend)
        video_backend = kwargs.pop("video_backend", self.video_backend)
        brief = kwargs.pop("brief")
        use_llm = kwargs.pop("use_llm", True)
        llm_provider = kwargs.pop("llm_provider", None)
        llm_model = kwargs.pop("llm_model", None)
        continuity_review_mode = kwargs.pop("continuity_review_mode", "auto")
        if kwargs:
            raise TypeError(f"Unsupported _run_story_pipeline kwargs: {sorted(kwargs.keys())}")

        generation = run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=project_root,
            output_root=output_root,
            backend=backend,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=project_root,
            output_root=generation.output_dir,
            backend=backend,
            video_backend=video_backend,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
        segment_contracts = run_story_segment_contracts_pipeline(
            novel_package=scene_structure.novel_package,
            config=config,
            project_root=project_root,
            output_root=scene_structure.output_dir,
            backend=video_backend,
            scene_structure_artifacts=scene_structure.scene_structure,
            use_llm=use_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            continuity_review_mode=continuity_review_mode,
        )
        return StoryStageBundle(
            output_dir=generation.output_dir,
            story_source_path=generation.story_source_path,
            novel_package_path=scene_structure.novel_package_path,
            novel_audit_path=scene_structure.novel_audit_path,
            story_memory_path=segment_contracts.story_memory_path,
            character_bible_path=segment_contracts.character_bible_path,
            character_images_path=segment_contracts.character_images_path,
            scene_plan_path=segment_contracts.scene_plan_path,
            segment_plan_path=segment_contracts.segment_plan_path,
            scene_images_path=segment_contracts.scene_images_path,
            seedance_manifest_path=segment_contracts.seedance_manifest_path,
            story_source=generation.story_source,
            novel_package=scene_structure.novel_package,
            video_planning=segment_contracts.video_planning,
        )

    def _run_story_generation_pipeline(self, **kwargs):
        return run_story_generation_pipeline(
            config=kwargs.pop("config"),
            project_root=kwargs.pop("project_root", ROOT),
            output_root=kwargs.pop("output_root", self.temp_root),
            backend=kwargs.pop("backend", self.story_backend),
            **kwargs,
        )

    def _build_video_planning_artifacts(self, **kwargs):
        return build_video_planning_artifacts(
            config=kwargs.pop("config"),
            project_root=kwargs.pop("project_root", ROOT),
            output_root=kwargs.pop("output_root", self.temp_root),
            backend=kwargs.pop("backend", self.video_backend),
            **kwargs,
        )

    def _ensure_two_outline_characters(self, story_result):
        characters = story_result.novel_package.outline.characters
        if len(characters) >= 2:
            return characters[0], characters[1]
        synthetic = CharacterProfile(
            cast_slot_id="lead_2",
            name="林晚",
            role="对手戏角色",
            gender="女",
            desire="回应当前主线关系",
            conflict="面对关系推进时保持克制",
            arc="从观望走向回应",
            visual_signature=["花园小径", "傍晚侧光"],
            voice_style="温柔克制",
            image_prompt="林晚，女，青年，校园感。",
        )
        story_result.novel_package.outline.characters.append(synthetic)
        return characters[0], characters[1]

    def test_live_structured_generation_retries_before_success(self) -> None:
        class RetryBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls < 3:
                    raise RuntimeError("structured_response missing")
                return StoryArchitectureSchema(
                    title="站台告白",
                    premise="列车离站前的告白。",
                    theme="告别与勇气",
                    setting="夜晚站台",
                    story_engine="离站倒计时逼迫关系表态。",
                    visual_motifs=["站台", "列车", "夜风"],
                    tone_notes=["克制", "电影感"],
                )

        service = NovelGeneratorService(backend=RetryBackend())
        result = service._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "story-architect"},
            ),
        )

        self.assertEqual(result.title, "站台告白")
        self.assertEqual(service.backend.calls, 3)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 3)
        self.assertIn("上一次输出未通过结构化校验", service.backend.requests[-1].user_prompt)

    def test_live_story_drafter_invalid_content_retries_without_runtime_fallback(self) -> None:
        class RetryBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "chapters": [
                            {
                                "number": 1,
                                "title": "花架下",
                                "summary": "他决定在这里开口。",
                                "markdown": "   ",
                                "visual_hooks": [],
                                "continuity_refs": [],
                            }
                        ]
                    }
                return {
                    "chapters": [
                        {
                            "number": 1,
                            "title": "花架下",
                            "summary": "他决定在这里开口。",
                            "markdown": "# 花架下\n\n他在紫藤花架下等待她赴约。",
                            "visual_hooks": ["紫藤花架"],
                            "continuity_refs": ["等待赴约"],
                        }
                    ]
                }

        service = NovelGeneratorService(backend=RetryBackend())
        brief = StoryBrief(
            title_hint="花架下",
            idea="一个男生准备在花架下告白。",
            genre="校园情感",
            tone="克制、青春",
            chapter_count=1,
            total_word_target=1000,
        )

        result = service._run_structured_agent(
            schema=StoryDraftSetSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "story-drafter"},
            ),
            validator=lambda value: service._validate_story_draft_set_output(
                value,
                brief=brief,
            ),
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertIn("story_drafter 第 1 章缺少必要字段", service.backend.requests[-1].user_prompt)
        self.assertEqual(result.chapters[0].title, "花架下")

    def test_novel_structured_agent_attaches_prompt_warning_metadata(self) -> None:
        class CaptureBackend:
            def __init__(self) -> None:
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.requests.append(request)
                return StoryArchitectureSchema(
                    title="长提示词测试",
                    premise="测试超长 prompt 预警。",
                    theme="提示词监控",
                    setting="测试环境",
                    story_engine="只验证 metadata 是否被正确写入。",
                    visual_motifs=["监控面板"],
                    tone_notes=["精简"],
                )

        backend = CaptureBackend()
        service = NovelGeneratorService(backend=backend)

        result = service._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="x" * (service.PROMPT_WARNING_THRESHOLD_CHARS + 64),
                metadata={"task": "story-architect"},
            ),
        )

        self.assertEqual(result.title, "长提示词测试")
        self.assertEqual(len(backend.requests), 1)
        request = backend.requests[0]
        self.assertEqual(
            request.metadata["prompt_soft_limit_chars"],
            service.PROMPT_WARNING_THRESHOLD_CHARS,
        )
        self.assertTrue(request.metadata["prompt_soft_limit_exceeded"])
        self.assertEqual(request.metadata["prompt_size_status"], "warn")
        self.assertIn("prompt length", request.metadata["prompt_warning"])
        self.assertGreater(
            request.metadata["total_prompt_chars"],
            service.PROMPT_WARNING_THRESHOLD_CHARS,
        )

    def test_video_structured_agent_live_success_does_not_resolve_fallback(self) -> None:
        class SuccessBackend:
            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                return {
                    "characters": [
                        {
                            "name": "林辰",
                            "role": "主角",
                            "gender": "男",
                            "appearance": "青年男性，体型稳定。",
                            "outfit": "白衬衫和牛仔裤。",
                            "color_palette": ["白色", "深蓝"],
                            "portrait_prompt": "林辰，男，青年，白衬衫，角色定妆。",
                        }
                    ]
                }

        service = NovelToVideoService(backend=SuccessBackend())
        result = service._run_structured_agent(
            schema=CharacterVisualBibleSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-character-bible"},
            ),
        )

        self.assertEqual(result.characters[0].name, "林辰")

    def test_video_planning_manifest_title_uses_story_title(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一场在末班列车前发生的告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        planning = self._build_video_planning_artifacts(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
        )

        self.assertEqual(planning.manifest.title, story_result.novel_package.outline.title)

    def test_video_strict_structured_repair_retries_before_success(self) -> None:
        class RetryBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    raise RuntimeError("segment repair schema invalid")
                return {
                    "characters": [
                        {
                            "name": "林辰",
                            "role": "主角",
                            "gender": "男",
                            "appearance": "青年男性，体型稳定。",
                            "outfit": "白衬衫和牛仔裤。",
                            "color_palette": ["白色", "深蓝"],
                            "portrait_prompt": "林辰，男，青年，白衬衫，角色定妆。",
                        }
                    ]
                }

        service = NovelToVideoService(backend=RetryBackend())
        result = service._run_strict_structured_agent(
            schema=CharacterVisualBibleSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "segment-continuity-repair"},
            ),
            validator=lambda value: value,
            attempts=2,
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual(result.characters[0].name, "林辰")
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 2)
        self.assertIn("上一次修复输出未通过结构化校验", service.backend.requests[-1].user_prompt)

    def test_story_pipeline_writes_continuity_report(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一场在末班列车前发生的告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        continuity_report_path = story_result.output_dir / "continuity_report.json"
        self.assertTrue(continuity_report_path.exists())
        continuity_report = read_json(continuity_report_path)
        self.assertEqual(continuity_report["report_version"], "v2")
        self.assertIn("summary", continuity_report)
        self.assertIn("scene_issues", continuity_report)
        self.assertIn("segment_issues", continuity_report)
        self.assertIn("v1_rules", continuity_report)
        self.assertIn("v2_llm_review", continuity_report)
        self.assertIn("review_mode_requested", continuity_report)

    def test_write_continuity_report_can_disable_v2_soft_review(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="短场景",
            idea="一个人安静地坐在窗边读信。",
            genre="情感",
            tone="克制、安静",
            chapter_count=1,
            total_word_target=800,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        _, report = write_continuity_report(
            story_result.output_dir,
            config=config,
            review_mode="off",
        )

        self.assertEqual(report.review_mode_requested, "off")
        self.assertEqual(report.review_mode_effective, "off")
        self.assertEqual(report.v2_llm_review.status, "disabled")

    def test_clear_story_derived_artifacts_removes_continuity_repair_reports(self) -> None:
        output_dir = self.temp_root / "cleanup-test"
        output_dir.mkdir(parents=True)
        repair_report_path = output_dir / "continuity_repair_ch1-sc1-seg1.json"
        repair_report_path.write_text("{}", encoding="utf-8")

        clear_story_derived_artifacts(output_dir)

        self.assertFalse(repair_report_path.exists())

    @patch(
        "storyforge.pipelines.video_pipeline.build_agent_backend",
        return_value=DeterministicVideoBackend(),
    )
    @patch("storyforge.pipelines.video_pipeline.NovelToVideoService.repair_segment_continuity")
    def test_run_segment_continuity_repair_pipeline_updates_target_segment_only(
        self,
        mock_repair_segment_continuity,
        mock_build_agent_backend,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="花园等待",
            idea="一个男生在花园等待喜欢的人赴约。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)

        segment_payload = read_json(story_result.segment_plan_path)
        self.assertGreaterEqual(len(segment_payload), 2)
        target_segment = dict(segment_payload[0])
        other_segment = dict(segment_payload[1])
        target_segment_id = str(target_segment["segment_id"])
        original_other_summary = str(other_segment["summary"])

        continuity_report_path = story_result.output_dir / "continuity_report.json"
        continuity_payload = read_json(continuity_report_path)
        continuity_payload["segment_issues"] = [
            {
                "scope": "segment",
                "severity": "high",
                "code": "action_bridge_weak",
                "message": "动作承接偏弱，需要重新规划该片段。",
                "scene_id": target_segment["scene_id"],
                "segment_id": target_segment_id,
                "recommended_action": "auto_repair_segment",
                "recommended_action_label": "智能修复该段",
                "details": {"field": "timed_beats"},
            }
        ]
        continuity_report_path.write_text(
            json.dumps(continuity_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        scene_images_path = story_result.output_dir / "scene_image_manifest.json"
        mark_scene_images_completed(story_result)

        manifest_path = story_result.output_dir / "seedance_manifest.json"
        mark_seedance_clips_completed(story_result)

        repaired_segment_payload = {
            **target_segment,
            "summary": "修复后的片段摘要",
            "timed_beats": ["0-3秒：补足承接动作", "3-8秒：完成核心对白"],
            "start_frame_prompt": "修复后的首帧提示词",
            "mid_frame_prompt": "修复后的中段提示词",
            "end_frame_prompt": "修复后的尾帧提示词",
        }
        mock_repair_segment_continuity.return_value = (
            VideoSegment.from_dict(repaired_segment_payload),
            {
                "segment_id": target_segment_id,
                "repair_summary": "已根据连续性问题重写该片段规划。",
                "changed_fields": ["summary", "timed_beats", "start_frame_prompt"],
            },
        )

        result = run_segment_continuity_repair_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            segment_id=target_segment_id,
            use_llm=True,
            continuity_review_mode="on",
        )

        self.assertEqual(result.segment_id, target_segment_id)
        self.assertTrue(result.repair_report_path.exists())
        self.assertTrue(mock_build_agent_backend.called)

        updated_segments = read_json(story_result.segment_plan_path)
        updated_target = next(
            item for item in updated_segments if item["segment_id"] == target_segment_id
        )
        updated_other = next(
            item for item in updated_segments if item["segment_id"] == other_segment["segment_id"]
        )
        self.assertEqual(updated_target["summary"], "修复后的片段摘要")
        self.assertEqual(updated_other["summary"], original_other_summary)

        updated_scene_images = read_json(scene_images_path)
        target_scene_task = next(
            item for item in updated_scene_images if item["segment_id"] == target_segment_id
        )
        other_scene_task = next(
            item for item in updated_scene_images if item["segment_id"] == other_segment["segment_id"]
        )
        self.assertEqual(target_scene_task["status"], "planned")
        self.assertEqual(target_scene_task["start_frame_url"], "")
        self.assertEqual(target_scene_task["end_frame_url"], "")
        self.assertEqual(other_scene_task["status"], "completed")
        self.assertNotEqual(other_scene_task["start_frame_url"], "")

        updated_manifest = read_json(manifest_path)
        target_clip = next(
            item for item in updated_manifest["clips"] if item["segment_id"] == target_segment_id
        )
        other_clip = next(
            item for item in updated_manifest["clips"] if item["segment_id"] == other_segment["segment_id"]
        )
        self.assertEqual(target_clip["submit_status"], "planned")
        self.assertEqual(target_clip["remote_status"], "planned")
        self.assertEqual(target_clip["video_url"], "")
        self.assertEqual(other_clip["submit_status"], "completed")
        self.assertNotEqual(other_clip["video_url"], "")

    @patch("storyforge.pipelines.video_pipeline.build_agent_backend")
    @patch("storyforge.pipelines.video_pipeline.NovelToVideoService.repair_scene_continuity")
    def test_run_scene_continuity_repair_pipeline_writes_scene_repair_report(
        self,
        mock_repair_scene_continuity,
        mock_build_agent_backend,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)

        scene_payload = read_json(story_result.scene_plan_path)
        target_scene_id = str(scene_payload["scenes"][0]["scene_id"])
        scene_segment_ids = [
            item["segment_id"]
            for item in scene_payload["scenes"][0]["segments"]
        ]
        localized_segment_id = str(scene_segment_ids[0])
        continuity_report_path = story_result.output_dir / "continuity_report.json"
        continuity_payload = read_json(continuity_report_path)
        continuity_payload["scene_issues"] = [
            {
                "scope": "scene",
                "severity": "medium",
                "code": "scene_master_frame_status_mismatch",
                "message": "只有一个片段的场景母图状态和 scene 主记录不一致。",
                "scene_id": target_scene_id,
                "segment_id": localized_segment_id,
                "recommended_action": "regenerate_scene_master_frame",
                "recommended_action_label": "重生成场景母图",
                "details": {},
            }
        ]
        continuity_payload["segment_issues"] = [
            {
                "scope": "segment",
                "severity": "high",
                "code": "video_generation_failed",
                "message": "片段视频生成失败，需要重新生成视频。",
                "scene_id": target_scene_id,
                "segment_id": localized_segment_id,
                "recommended_action": "regenerate_video",
                "recommended_action_label": "重生成片段视频",
                "details": {"error": "demo"},
            }
        ]
        continuity_report_path.write_text(
            json.dumps(continuity_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        scene_payload = read_json(story_result.scene_plan_path)
        target_scene = dict(scene_payload["scenes"][0])
        repaired_scene_payload = {
            **target_scene,
            "scene_anchor": "修复后的入口到内部步道场景锚点",
            "scene_bible": {
                **target_scene["scene_bible"],
                "location": "玫瑰园入口连接内部花径",
                "background_anchors": ["拱门", "花墙", "向内延伸的石板路"],
                "fixed_props": ["路灯", "长椅"],
                "spatial_layout": "镜头沿步道向园内推进，保持入口到内部的纵深关系",
                "continuity_notes": "同一场景保持从入口到内部花径的连续空间，不回退成单一入口特写",
            },
            "scene_master_frame_prompt": "修复后的场景母图 prompt",
            "scene_master_frame_status": "planned",
            "scene_master_frame_url": "",
            "scene_master_frame_error": "",
        }
        mock_repair_scene_continuity.return_value = (
            VideoScene.from_dict(repaired_scene_payload),
            {
                "scene_id": target_scene_id,
                "repair_summary": "已更新 scene 基线，等待人工决定是否重跑场景母图和媒体阶段。",
                "changed_fields": ["scene_anchor", "scene_bible", "scene_master_frame_prompt"],
            },
        )

        result = run_scene_continuity_repair_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            scene_id=target_scene_id,
            use_llm=True,
            continuity_review_mode="on",
        )

        self.assertEqual(result.scene_id, target_scene_id)
        self.assertEqual(result.segment_id, "")
        self.assertTrue(result.repair_report_path.exists())
        self.assertTrue(mock_build_agent_backend.called)
        repair_payload = read_json(result.repair_report_path)
        self.assertEqual(repair_payload["scope"], "scene")
        self.assertEqual(repair_payload["scene_id"], target_scene_id)
        self.assertEqual(repair_payload["repair_action"], "regenerate_scene_master_frame")
        self.assertEqual(repair_payload["selection_mode"], "localized_segments")
        self.assertEqual(repair_payload["affected_segment_ids"], [localized_segment_id])
        self.assertEqual(len(repair_payload["continuity_issues"]), 1)
        self.assertEqual(len(repair_payload["related_segment_issues"]), 1)
        self.assertEqual(result.affected_segment_ids, (localized_segment_id,))

        updated_scene_plan = read_json(story_result.scene_plan_path)
        updated_scene = next(item for item in updated_scene_plan["scenes"] if item["scene_id"] == target_scene_id)
        self.assertEqual(updated_scene["scene_anchor"], "修复后的入口到内部步道场景锚点")
        self.assertEqual(updated_scene["scene_bible"]["location"], "玫瑰园入口连接内部花径")
        self.assertEqual(updated_scene["scene_master_frame_status"], "planned")

        updated_segments = read_json(story_result.segment_plan_path)
        repaired_segment = next(item for item in updated_segments if item["segment_id"] == localized_segment_id)
        self.assertEqual(repaired_segment["scene_bible"]["location"], "玫瑰园入口连接内部花径")

        updated_scene_images = read_json(story_result.output_dir / "scene_image_manifest.json")
        repaired_scene_task = next(item for item in updated_scene_images if item["segment_id"] == localized_segment_id)
        self.assertEqual(repaired_scene_task["status"], "planned")

    @patch("storyforge.pipelines.video_pipeline.build_agent_backend")
    @patch("storyforge.pipelines.video_pipeline.NovelToVideoService.repair_scene_continuity")
    def test_run_scene_continuity_repair_pipeline_keeps_full_scene_for_global_issue(
        self,
        mock_repair_scene_continuity,
        mock_build_agent_backend,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)

        scene_payload = read_json(story_result.scene_plan_path)
        target_scene_id = str(scene_payload["scenes"][0]["scene_id"])
        scene_segment_ids = [
            item["segment_id"]
            for item in scene_payload["scenes"][0]["segments"]
        ]
        continuity_report_path = story_result.output_dir / "continuity_report.json"
        continuity_payload = read_json(continuity_report_path)
        continuity_payload["scene_issues"] = [
            {
                "scope": "scene",
                "severity": "high",
                "code": "scene_master_frame_missing_output",
                "message": "场景母图缺失，需要重生成。",
                "scene_id": target_scene_id,
                "segment_id": "",
                "recommended_action": "regenerate_scene_master_frame",
                "recommended_action_label": "重生成场景母图",
                "details": {"scene_master_frame_path": "missing.png"},
            }
        ]
        continuity_payload["segment_issues"] = [
            {
                "scope": "segment",
                "severity": "high",
                "code": "video_generation_failed",
                "message": "其中一个片段视频失败。",
                "scene_id": target_scene_id,
                "segment_id": str(scene_segment_ids[0]),
                "recommended_action": "regenerate_video",
                "recommended_action_label": "重生成片段视频",
                "details": {},
            }
        ]
        continuity_report_path.write_text(
            json.dumps(continuity_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        scene_payload = read_json(story_result.scene_plan_path)
        target_scene = dict(scene_payload["scenes"][0])
        repaired_scene_payload = {
            **target_scene,
            "scene_anchor": "全场景修复后的锚点",
            "scene_bible": {
                **target_scene["scene_bible"],
                "location": "全新的场景连续空间",
                "background_anchors": ["主入口", "中央花坛", "内部步道"],
                "fixed_props": ["路灯", "长椅"],
                "spatial_layout": "镜头在整 scene 内沿同一空间轴线推进",
                "continuity_notes": "整 scene 保持统一空间与光线基线",
            },
            "scene_master_frame_prompt": "全场景修复后的母图 prompt",
            "scene_master_frame_status": "planned",
            "scene_master_frame_url": "",
            "scene_master_frame_error": "",
        }
        mock_repair_scene_continuity.return_value = (
            VideoScene.from_dict(repaired_scene_payload),
            {
                "scene_id": target_scene_id,
                "repair_summary": "已更新全 scene 基线。",
                "changed_fields": ["scene_bible"],
            },
        )

        result = run_scene_continuity_repair_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            scene_id=target_scene_id,
            use_llm=True,
            continuity_review_mode="on",
        )

        self.assertTrue(mock_build_agent_backend.called)
        repair_payload = read_json(result.repair_report_path)
        self.assertEqual(repair_payload["selection_mode"], "full_scene_global_issue")
        self.assertEqual(repair_payload["affected_segment_ids"], scene_segment_ids)
        self.assertEqual(result.affected_segment_ids, tuple(scene_segment_ids))

    @patch("storyforge.pipelines.continuity.build_agent_backend")
    def test_write_continuity_report_can_force_v2_soft_review(self, mock_build_backend) -> None:
        class InitialBackend:
            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                return ContinuitySoftReviewSchema()

        mock_build_backend.return_value = InitialBackend()
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="花园等待",
            idea="一个男生在花园等待喜欢的人赴约。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        segment_payload = read_json(story_result.segment_plan_path)
        first_segment_id = segment_payload[0]["segment_id"]
        first_scene_id = segment_payload[0]["scene_id"]

        class ReviewBackend:
            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                return ContinuitySoftReviewSchema(
                    summary="发现一处动作承接偏弱。",
                    segment_issues=[
                        ContinuitySoftIssueSchema(
                            scope="segment",
                            severity="medium",
                            issue_type="action_bridge_weak",
                            scene_id=first_scene_id,
                            segment_id=first_segment_id,
                            message="当前段从等待直接跳到转身，动作桥接偏弱，观感上像少了一拍。",
                            recommended_action="regenerate_scene_images",
                            evidence="start_frame_prompt 与 end_frame_prompt 动作跨度较大，timed_beats 没有补中间动作。",
                        )
                    ],
                )

        mock_build_backend.return_value = ReviewBackend()

        _, report = write_continuity_report(
            story_result.output_dir,
            config=config,
            review_mode="on",
            llm_provider="deepseek",
            llm_model="deepseek-chat",
        )

        self.assertEqual(report.review_mode_requested, "on")
        self.assertEqual(report.review_mode_effective, "on")
        self.assertEqual(report.v2_llm_review.status, "completed")
        self.assertTrue(
            any(issue.code == "llm_action_bridge_weak" for issue in report.segment_issues)
        )

    def test_load_video_planning_artifacts_restores_story_title_from_novel_package(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一场在末班列车前发生的告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        planning = self._build_video_planning_artifacts(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
        )
        manifest_payload = read_json(planning.manifest_path)
        manifest_payload["title"] = "segment_video_manifest"
        planning.manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        loaded = load_video_planning_artifacts(story_result.output_dir)

        self.assertEqual(loaded.project_package.title, story_result.novel_package.outline.title)
        self.assertEqual(loaded.manifest.title, "segment_video_manifest")

    def test_live_structured_generation_raises_after_retry_limit(self) -> None:
        class AlwaysFailBackend:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                raise RuntimeError("structured_response missing")

        service = NovelGeneratorService(backend=AlwaysFailBackend())
        with self.assertRaises(NovelStructuredGenerationError) as ctx:
            service._run_structured_agent(
                schema=StoryArchitectureSchema,
                request=PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "story-architect"},
                ),
            )

        self.assertEqual(service.backend.calls, 3)
        self.assertIn("task=story-architect", str(ctx.exception))

    def test_live_structured_generation_none_response_raises_clear_error(self) -> None:
        class EmptyStructuredBackend:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                return None

        service = NovelGeneratorService(backend=EmptyStructuredBackend())
        with self.assertRaises(NovelStructuredGenerationError) as ctx:
            service._run_structured_agent(
                schema=StoryArchitectureSchema,
                request=PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "story-architect"},
                ),
            )

        self.assertEqual(service.backend.calls, 3)
        self.assertIn("模型没有返回 StoryArchitectureSchema 结构化对象", str(ctx.exception))
        self.assertNotIn("input_value=None", str(ctx.exception))

    def test_character_roster_duplicate_names_trigger_structured_retry(self) -> None:
        class DuplicateNameBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "characters": [
                            {
                                "cast_slot_id": "lead_1",
                                "name": "程野",
                                "role": "主角",
                                "gender": "男",
                                "desire": "推进故事",
                                "conflict": "面对阻力",
                                "arc": "学会回应",
                                "visual_signature": ["站台"],
                                "voice_style": "克制",
                                "voice_profile": {
                                    "voice_style": "克制",
                                    "timbre": "清亮",
                                    "speaking_rate": "中速",
                                    "emotional_baseline": "紧张",
                                    "accent_or_texture": "",
                                    "dialogue_delivery": "",
                                    "forbidden_voice_changes": ["不要突然变老"],
                                },
                                "image_prompt": "程野，男，站台上的人。",
                            },
                            {
                                "cast_slot_id": "lead_2",
                                "name": "程野",
                                "role": "对位角色",
                                "gender": "女",
                                "desire": "作出回应",
                                "conflict": "不敢坦白",
                                "arc": "学会表达",
                                "visual_signature": ["列车"],
                                "voice_style": "克制",
                                "voice_profile": {
                                    "voice_style": "克制",
                                    "timbre": "柔和",
                                    "speaking_rate": "中速",
                                    "emotional_baseline": "克制",
                                    "accent_or_texture": "",
                                    "dialogue_delivery": "",
                                    "forbidden_voice_changes": ["不要突然变老"],
                                },
                                "image_prompt": "程野，女，列车旁的人。",
                            },
                        ]
                    }
                return {
                    "characters": [
                        {
                            "cast_slot_id": "lead_1",
                            "name": "程野",
                            "role": "主角",
                            "gender": "男",
                            "desire": "推进故事",
                            "conflict": "面对阻力",
                            "arc": "学会回应",
                            "visual_signature": ["站台"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "清亮",
                                "speaking_rate": "中速",
                                "emotional_baseline": "紧张",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "程野，男，站台上的人。",
                        },
                        {
                            "cast_slot_id": "lead_2",
                            "name": "苏晚",
                            "role": "对位角色",
                            "gender": "女",
                            "desire": "作出回应",
                            "conflict": "不敢坦白",
                            "arc": "学会表达",
                            "visual_signature": ["列车"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "柔和",
                                "speaking_rate": "中速",
                                "emotional_baseline": "克制",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "苏晚，女，列车旁的人。",
                        },
                    ]
                }

        service = NovelGeneratorService(backend=DuplicateNameBackend())

        result = service._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "character-designer"},
            ),
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual([item.name for item in result.characters], ["程野", "苏晚"])
        self.assertIn("重名角色", service.backend.requests[-1].user_prompt)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 2)

    def test_character_roster_duplicate_slot_ids_trigger_structured_retry(self) -> None:
        class DuplicateSlotBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "characters": [
                            {
                                "cast_slot_id": "lead_1",
                                "name": "程野",
                                "role": "主角",
                                "gender": "男",
                                "desire": "推进故事",
                                "conflict": "面对阻力",
                                "arc": "学会回应",
                                "visual_signature": ["站台"],
                                "voice_style": "克制",
                                "voice_profile": {
                                    "voice_style": "克制",
                                    "timbre": "清亮",
                                    "speaking_rate": "中速",
                                    "emotional_baseline": "紧张",
                                    "accent_or_texture": "",
                                    "dialogue_delivery": "",
                                    "forbidden_voice_changes": ["不要突然变老"],
                                },
                                "image_prompt": "程野，男，站台上的人。",
                            },
                            {
                                "cast_slot_id": "lead_1",
                                "name": "苏晚",
                                "role": "对位角色",
                                "gender": "女",
                                "desire": "作出回应",
                                "conflict": "不敢坦白",
                                "arc": "学会表达",
                                "visual_signature": ["列车"],
                                "voice_style": "克制",
                                "voice_profile": {
                                    "voice_style": "克制",
                                    "timbre": "柔和",
                                    "speaking_rate": "中速",
                                    "emotional_baseline": "克制",
                                    "accent_or_texture": "",
                                    "dialogue_delivery": "",
                                    "forbidden_voice_changes": ["不要突然变老"],
                                },
                                "image_prompt": "苏晚，女，列车旁的人。",
                            },
                        ]
                    }
                return {
                    "characters": [
                        {
                            "cast_slot_id": "lead_1",
                            "name": "程野",
                            "role": "主角",
                            "gender": "男",
                            "desire": "推进故事",
                            "conflict": "面对阻力",
                            "arc": "学会回应",
                            "visual_signature": ["站台"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "清亮",
                                "speaking_rate": "中速",
                                "emotional_baseline": "紧张",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "程野，男，站台上的人。",
                        },
                        {
                            "cast_slot_id": "lead_2",
                            "name": "苏晚",
                            "role": "对位角色",
                            "gender": "女",
                            "desire": "作出回应",
                            "conflict": "不敢坦白",
                            "arc": "学会表达",
                            "visual_signature": ["列车"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "柔和",
                                "speaking_rate": "中速",
                                "emotional_baseline": "克制",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "苏晚，女，列车旁的人。",
                        },
                    ]
                }

        service = NovelGeneratorService(backend=DuplicateSlotBackend())

        result = service._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "character-designer"},
            ),
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual([item.cast_slot_id for item in result.characters], ["lead_1", "lead_2"])
        self.assertIn("重复槽位", service.backend.requests[-1].user_prompt)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 2)

    def test_video_structured_retry_adds_length_compression_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-segment-planner"},
            ),
            schema=VideoSegmentPlanSchema,
            attempt=2,
            last_error=RuntimeError(
                "LangChain structured output was empty; finish_reason='length'"
            ),
        )

        self.assertEqual(retry_request.metadata["structured_retry_attempt"], 2)
        self.assertIn("输出过长被截断", retry_request.user_prompt)
        self.assertIn("不要重复父级 scene", retry_request.user_prompt)

    def test_video_structured_retry_adds_timed_beats_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=RuntimeError("segment ch01-sc01-seg01 缺少 timed_beats。"),
        )

        self.assertEqual(retry_request.metadata["structured_retry_attempt"], 2)
        self.assertIn("漏掉了必填的 timed_beats", retry_request.user_prompt)
        self.assertIn("0-2秒：发生了什么", retry_request.user_prompt)

    def test_video_structured_retry_adds_action_budget_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=SegmentActionSplitRequiredError(
                segment_id="ch01-sc01-seg01",
                action_node_count=4,
                current_duration_seconds=6,
                max_action_nodes=2,
                required_segment_count=2,
            ),
        )

        self.assertEqual(retry_request.metadata["structured_retry_attempt"], 2)
        self.assertIn("动作容量约有 4 个推进点", retry_request.user_prompt)
        self.assertIn("至少拆成 2 个 segment", retry_request.user_prompt)
        self.assertIn("等待 -> 会面 -> 开口", retry_request.user_prompt)

    def test_video_structured_retry_adds_chapter_event_split_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-chapter-event-planner"},
            ),
            schema=ChapterCoveragePlanSchema,
            attempt=2,
            last_error=ValueError(
                "关键事件 ch01-ev02 过于粗：当前至少包含 3 个推进点。"
                "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
            ),
        )

        self.assertEqual(retry_request.metadata["structured_retry_attempt"], 2)
        self.assertIn("把多个推进阶段合并成了同一个关键事件", retry_request.user_prompt)
        self.assertIn("拆成更细的相邻 event", retry_request.user_prompt)
        self.assertIn("等待 -> 会面 -> 开口", retry_request.user_prompt)
        self.assertIn("如果当前章节已经拆成多个 event，章节首尾 event 最多允许 3 个", retry_request.user_prompt)
        self.assertIn("回忆补叙", retry_request.user_prompt)
        self.assertIn("中间 event 尤其不能把一轮问句、一次回答和一个动作结果同时塞进去", retry_request.user_prompt)
        self.assertIn("source_evidence", retry_request.user_prompt)

    def test_video_chapter_event_repair_retry_focuses_current_offending_event(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_repair_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="repair-user",
                metadata={
                    "task": "video-chapter-event-repair",
                    "chapter_number": 1,
                    "offending_event_id": "ch01-ev02",
                },
            ),
            schema=ChapterCoveragePlanSchema,
            attempt=2,
            last_error=ValueError(
                "关键事件 ch01-ev03 过于粗：当前至少包含 3 个推进点。"
                "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
            ),
        )

        self.assertEqual(retry_request.metadata["offending_event_id"], "ch01-ev03")
        self.assertIn("本次只优先修 `ch01-ev03` 及其后续编号", retry_request.user_prompt)
        self.assertIn("如果当前失败项不是章节首尾 event，就必须压到 1-2 个推进点", retry_request.user_prompt)
        self.assertIn("中间 event 不要再把问句、回答、动作结果三连塞在一起", retry_request.user_prompt)

    def test_video_chapter_event_split_repair_retry_forbids_merging_back_into_one_event(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_repair_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="split-user",
                metadata={
                    "task": "video-chapter-event-split-repair",
                    "chapter_number": 1,
                    "offending_event_id": "ch01-ev05",
                },
            ),
            schema=ChapterCoverageEventSplitPlanSchema,
            attempt=2,
            last_error=ValueError(
                "关键事件 ch01-ev05 过于粗：当前至少包含 4 个推进点。"
                "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
            ),
        )

        self.assertEqual(retry_request.metadata["offending_event_id"], "ch01-ev05")
        self.assertIn("replacement events 至少输出 2 条", retry_request.user_prompt)
        self.assertIn("不要输出 event_id", retry_request.user_prompt)
        self.assertIn("不要改写相邻 event", retry_request.user_prompt)

    def test_video_scene_chunk_repair_retry_focuses_current_offending_chunk(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_repair_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="repair-user",
                metadata={
                    "task": "video-scene-chunk-repair",
                    "chapter_number": 1,
                    "scene_id": "ch01-sc01",
                    "offending_chunk_id": "ch01-sc01-ch01",
                    "required_segment_count": 2,
                },
            ),
            schema=SceneSegmentChunkPlanSchema,
            attempt=2,
            last_error=ValueError(
                "scene ch01-sc01 的 chunk ch01-sc01-ch02 动作容量过载："
                "当前 must_cover / transition_goal 至少包含 4 个推进点，"
                "expected_segment_count 至少应为 2，或拆成更多 chunk。"
            ),
        )

        self.assertEqual(retry_request.metadata["offending_chunk_id"], "ch01-sc01-ch02")
        self.assertEqual(retry_request.metadata["required_segment_count"], 2)
        self.assertIn("本次只优先修 `ch01-sc01-ch02`", retry_request.user_prompt)
        self.assertIn("`expected_segment_count` 至少要改成 2", retry_request.user_prompt)
        self.assertIn("必须把当前 chunk 拆成两个连续 chunk", retry_request.user_prompt)

    def test_video_structured_retry_adds_frame_and_opening_match_notes(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=RuntimeError(
                "segment ch01-sc01-seg01 的 mid_frame_characters 不能为空，且只能使用 involved_characters 内角色。"
                " segment ch01-sc01-seg01 的 continuity_link.opening_match 过于空泛，必须写出可拍到的开场状态。"
            ),
        )

        self.assertIn("中段出镜角色写错了", retry_request.user_prompt)
        self.assertIn("不要直接照搬整个 scene cast", retry_request.user_prompt)
        self.assertIn("opening_match 不合格", retry_request.user_prompt)
        self.assertIn("不要留空，也不要写", retry_request.user_prompt)

    def test_video_structured_retry_adds_cross_chunk_opening_match_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=RuntimeError(
                "scene ch01-sc07 的 chunk ch01-sc07-c03 首段 opening_match 没有明确承接上一 chunk 尾部状态。"
            ),
        )

        self.assertIn("跨 chunk 首段没有把上一 chunk 的尾部状态真正复现", retry_request.user_prompt)
        self.assertIn("visible_tail_state", retry_request.user_prompt)
        self.assertIn("opening_match_seed", retry_request.user_prompt)
        self.assertIn("承接上一 chunk 尾部", retry_request.user_prompt)

    def test_video_structured_retry_adds_mid_frame_anchor_group_note(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=RuntimeError(
                "segment ch01-sc01-seg01 的 mid_frame_characters 不能只保留首尾同组角色的一部分。"
                "首尾帧固定角色组为 苏雨、林晨，但中段写成了 苏雨。"
            ),
        )

        self.assertIn("中段锚点把同一组多人角色写丢了", retry_request.user_prompt)
        self.assertIn("mid_frame_mode", retry_request.user_prompt)
        self.assertIn("insert_cut", retry_request.user_prompt)
        self.assertIn("把 `mid_frame_characters` 改回 `苏雨、林晨`", retry_request.user_prompt)
        self.assertIn("先 苏雨、林晨 同框 -> 再切 苏雨 单人 -> 最后回到 苏雨、林晨 同框", retry_request.user_prompt)

    def test_frame_character_rule_block_includes_mid_frame_two_branch_examples(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)

        rule_block = service._frame_character_rule_block()

        self.assertIn("二选一", rule_block)
        self.assertIn(
            "`mid_frame_mode=continuous`",
            rule_block,
        )
        self.assertIn(
            "`start=[苏雨,林晨] / mid=[苏雨] / end=[苏雨,林晨] / mid_frame_mode=continuous`",
            rule_block,
        )
        self.assertIn(
            "主镜头 -> 插入镜头 -> 主镜头",
            rule_block,
        )
        self.assertIn(
            "先检查 `start_frame_characters / mid_frame_characters / end_frame_characters`",
            rule_block,
        )
        self.assertIn(
            "`shot_state.camera_motion=推向林晨侧脸特写`",
            rule_block,
        )
        self.assertIn(
            "保持苏雨、林晨同框",
            rule_block,
        )

    def test_video_structured_retry_adds_multi_character_focus_example(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-scene-segment-planner"},
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=RuntimeError(
                "segment ch01-sc04-seg01 的 shot_state.camera_motion 在 start_frame (苏晴、林远) 多人同帧时仍要求单人特写，这会导致同一角色在单帧里重复出现。"
            ),
        )

        self.assertIn("如果 start_frame 是 `苏晴、林远`", retry_request.user_prompt)
        self.assertIn("保持两人同框并捕捉苏晴表情变化", retry_request.user_prompt)
        self.assertIn("当前报错的是 `shot_state.camera_motion` 在 `start_frame`", retry_request.user_prompt)
        self.assertIn("该帧角色是 `苏晴、林远`", retry_request.user_prompt)
        self.assertIn("不要再写“推向 苏晴 侧脸特写”", retry_request.user_prompt)

    def test_action_repair_focus_conflict_error_is_routed_to_focus_repair(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)

        self.assertTrue(
            service._should_repair_scene_chunk_contract_batch_after_focus_conflict_failure(
                ValueError(
                    "segment ch01-sc01-seg04b 的 shot_state.camera_motion 在 start_frame "
                    "(林屿、苏晚) 多人同帧时仍要求单人特写，这会导致同一角色在单帧里重复出现。"
                )
            )
        )

    def test_video_scene_segment_focus_repair_retry_keeps_shared_lens_language(self) -> None:
        service = NovelToVideoService(backend=self.video_backend)
        retry_request = service._build_repair_retry_request(
            request=PromptRequest(
                system_prompt="system",
                user_prompt="focus-user",
                metadata={
                    "task": "video-scene-segment-focus-repair",
                    "chapter_number": 1,
                    "scene_id": "ch01-sc01",
                    "chunk_id": "ch01-sc01-ch03",
                    "offending_segment_id": "ch01-sc01-seg05",
                    "field_name": "shot_state.framing",
                    "frame_label": "start_frame",
                },
            ),
            schema=SceneSegmentContractBatchSchema,
            attempt=2,
            last_error=ValueError(
                "segment ch01-sc01-seg05 的 shot_state.framing 在 start_frame "
                "(林屿、苏晚) 多人同帧时仍要求单人特写，这会导致同一角色在单帧里重复出现。"
            ),
        )

        self.assertEqual(retry_request.metadata["offending_segment_id"], "ch01-sc01-seg05")
        self.assertEqual(retry_request.metadata["field_name"], "shot_state.framing")
        self.assertEqual(retry_request.metadata["frame_label"], "start_frame")
        self.assertIn("只优先修 `ch01-sc01-seg05`", retry_request.user_prompt)
        self.assertIn("角色组是 `林屿、苏晚`", retry_request.user_prompt)
        self.assertIn("把 `shot_state.framing` 和 `shot_state.camera_motion` 一起改成共享镜头语言", retry_request.user_prompt)
        self.assertIn("不要把 `start_frame` 主锚点偷偷改成单人特写", retry_request.user_prompt)

    def test_scene_segment_contract_schema_requires_timed_beats(self) -> None:
        with self.assertRaises(ValidationError):
            SceneSegmentContractBatchSchema.model_validate(
                {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg01",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "等待",
                            "summary": "主角在湖边等待。",
                            "involved_characters": ["陈默"],
                            "start_frame_characters": ["陈默"],
                            "end_frame_characters": ["陈默"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "duration_seconds": 5,
                            "requires_mid_frame": False,
                            "transition_hint": "start",
                            "shot_state": {},
                            "continuity_link": {},
                        }
                    ],
                }
            )

    def test_character_roster_count_mismatch_triggers_missing_slot_backfill(self) -> None:
        class CountMismatchBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "characters": [
                            {
                                "cast_slot_id": "lead_1",
                                "name": "程野",
                                "role": "主角",
                                "gender": "男",
                                "desire": "推进故事",
                                "conflict": "面对阻力",
                                "arc": "学会回应",
                                "visual_signature": ["站台"],
                                "voice_style": "克制",
                                "voice_profile": {
                                    "voice_style": "克制",
                                    "timbre": "清亮",
                                    "speaking_rate": "中速",
                                    "emotional_baseline": "紧张",
                                    "accent_or_texture": "",
                                    "dialogue_delivery": "",
                                    "forbidden_voice_changes": ["不要突然变老"],
                                },
                                "image_prompt": "程野，男，站台上的人。",
                            }
                        ]
                    }
                return {
                    "characters": [
                        {
                            "cast_slot_id": "lead_1",
                            "name": "程野",
                            "role": "主角",
                            "gender": "男",
                            "desire": "推进故事",
                            "conflict": "面对阻力",
                            "arc": "学会回应",
                            "visual_signature": ["站台"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "清亮",
                                "speaking_rate": "中速",
                                "emotional_baseline": "紧张",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "程野，男，站台上的人。",
                        },
                        {
                            "cast_slot_id": "lead_2",
                            "name": "苏晚",
                            "role": "对位角色",
                            "gender": "女",
                            "desire": "作出回应",
                            "conflict": "不敢坦白",
                            "arc": "学会表达",
                            "visual_signature": ["列车"],
                            "voice_style": "克制",
                            "voice_profile": {
                                "voice_style": "克制",
                                "timbre": "柔和",
                                "speaking_rate": "中速",
                                "emotional_baseline": "克制",
                                "accent_or_texture": "",
                                "dialogue_delivery": "",
                                "forbidden_voice_changes": ["不要突然变老"],
                            },
                            "image_prompt": "苏晚，女，列车旁的人。",
                        },
                    ]
                }

        service = NovelGeneratorService(backend=CountMismatchBackend())
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
        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
        expected_slots = cast_analysis.primary_slots(
            max(1, cast_analysis.recommended_core_cast_count)
        )
        result = service._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={
                    "task": "character-designer",
                    "expected_character_count": len(expected_slots),
                    "expected_cast_slot_ids": [item.slot_id for item in expected_slots],
                    "character_slot_contract": "\n".join(
                        [
                            f"- characters[{index}].cast_slot_id 必须是 \"{item.slot_id}\""
                            for index, item in enumerate(expected_slots)
                        ]
                    ),
                },
            ),
            validator=lambda value: service._validate_character_roster_output(
                value,
                cast_analysis=cast_analysis,
            ),
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual([item.cast_slot_id for item in result.characters], ["lead_1", "lead_2"])
        self.assertEqual(service.backend.requests[-1].metadata["task"], "character-designer-backfill")
        self.assertIn("现在只补全缺失角色", service.backend.requests[-1].user_prompt)
        self.assertIn("缺失 slots：lead_2", service.backend.requests[-1].user_prompt)
        self.assertIn("characters[1].cast_slot_id 必须是 \"lead_2\"", service.backend.requests[-1].user_prompt)

    def test_video_segment_planner_live_failure_raises_clear_error(self) -> None:
        class AlwaysFailBackend:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                raise RuntimeError("structured_response missing")

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="花园等待",
            idea="一个男生在花园等待喜欢的人赴约。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(backend=AlwaysFailBackend())

        with self.assertRaises(VideoStructuredGenerationError) as ctx:
            service._run_structured_agent(
                schema=VideoSegmentPlanSchema,
                request=PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "video-segment-planner"},
                ),
                validator=lambda value: service._validate_segment_plan_output(
                    value,
                    novel_package=story_result.novel_package,
                ),
            )

        self.assertEqual(service.backend.calls, 3)
        self.assertIn("task=video-segment-planner", str(ctx.exception))

    def test_video_segment_plan_meta_template_phrases_trigger_retry(self) -> None:
        class MetaTemplateBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "scenes": [
                            {
                                "scene_id": "ch01-sc01",
                                "chapter_number": 1,
                                "title": "场景 1",
                                "summary": "等待",
                                "scene_anchor": "花园傍晚",
                                "scene_bible": {},
                                "involved_characters": ["林辰", "苏雨"],
                                "segments": [
                                    {
                                        "segment_id": "ch01-sc01-seg01",
                                        "chapter_number": 1,
                                        "scene_id": "ch01-sc01",
                                        "scene_title": "场景 1",
                                        "scene_summary": "等待",
                                        "scene_anchor": "花园傍晚",
                                        "scene_bible": {},
                                        "shot_state": {},
                                        "continuity_link": {},
                                        "title": "片段 1",
                                        "summary": "当前片段聚焦：林辰等待苏雨",
                                        "involved_characters": ["林辰"],
                                        "start_frame_characters": ["林辰"],
                                        "mid_frame_characters": [],
                                        "end_frame_characters": ["林辰"],
                                        "narration": "结尾要保留初吻的余波。",
                                        "dialogue_lines": [],
                                        "subtitle_lines": [],
                                        "sound_effects": ["晚风"],
                                        "music_direction": "温柔",
                                        "timed_beats": ["0-6秒：林辰等待苏雨"],
                                        "start_frame_prompt": "林辰站在花架下",
                                        "mid_frame_prompt": "",
                                        "end_frame_prompt": "林辰望向路口",
                                        "duration_seconds": 6,
                                        "requires_mid_frame": False,
                                        "transition_hint": "auto",
                                    }
                                ],
                            }
                        ]
                    }
                return {
                    "scenes": [
                        {
                            "scene_id": "ch01-sc01",
                            "chapter_number": 1,
                            "title": "场景 1",
                            "summary": "林辰在花园等待苏雨赴约",
                            "scene_anchor": "紫藤花架与图书馆灯光",
                            "scene_bible": {},
                            "involved_characters": ["林辰", "苏雨"],
                            "segments": [
                                {
                                    "segment_id": "ch01-sc01-seg01",
                                    "chapter_number": 1,
                                    "scene_id": "ch01-sc01",
                                    "scene_title": "场景 1",
                                    "scene_summary": "林辰在花园等待苏雨赴约",
                                    "scene_anchor": "紫藤花架与图书馆灯光",
                                    "scene_bible": {},
                                    "shot_state": {},
                                    "continuity_link": {},
                                    "title": "片段 1",
                                    "summary": "林辰独自在紫藤花架下等待苏雨",
                                        "involved_characters": ["林辰"],
                                        "start_frame_characters": ["林辰"],
                                        "mid_frame_characters": [],
                                        "end_frame_characters": ["林辰"],
                                    "narration": "林辰提前来到花园，在紫藤花下反复整理衣角。",
                                    "dialogue_lines": [],
                                    "subtitle_lines": ["林辰提前来到花园，在紫藤花下反复整理衣角。"],
                                    "sound_effects": ["晚风", "树叶轻响"],
                                    "music_direction": "克制温柔",
                                    "timed_beats": ["0-6秒：林辰独自在花架下等待，视线不断望向路口"],
                                    "start_frame_prompt": "林辰站在紫藤花架下望向路口",
                                    "mid_frame_prompt": "",
                                    "end_frame_prompt": "林辰低头整理衣角后再次抬头",
                                    "duration_seconds": 6,
                                    "requires_mid_frame": False,
                                    "transition_hint": "auto",
                                }
                            ],
                        }
                    ]
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="花园等待",
            idea="一个男生在花园等待喜欢的人赴约。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService(backend=MetaTemplateBackend())

        result = service._run_structured_agent(
            schema=VideoSegmentPlanSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "video-segment-planner"},
            ),
            validator=lambda value: service._validate_segment_plan_output(
                value,
                novel_package=story_result.novel_package,
            ),
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual(result.segments[0].summary, "林辰独自在紫藤花架下等待苏雨")
        self.assertIn("未通过结构化校验", service.backend.requests[-1].user_prompt)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 2)

    def test_story_pipeline_and_explicit_video_stages(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        self.assertTrue(story_result.story_source_path.exists())
        self.assertTrue(story_result.novel_package_path.exists())
        self.assertTrue(story_result.novel_audit_path.exists())
        self.assertTrue(story_result.story_memory_path.exists())
        self.assertTrue(story_result.character_bible_path.exists())
        self.assertTrue(story_result.character_images_path.exists())
        self.assertTrue(story_result.scene_plan_path.exists())
        self.assertTrue(story_result.segment_plan_path.exists())
        self.assertTrue(story_result.scene_images_path.exists())
        self.assertTrue(story_result.seedance_manifest_path.exists())
        self.assertFalse((story_result.output_dir / "story.md").exists())
        self.assertFalse((story_result.output_dir / "outline.json").exists())
        self.assertFalse((story_result.output_dir / "workflow_trace.json").exists())
        self.assertIsNotNone(story_result.novel_package.review)
        self.assertIn("story_architect", story_result.novel_package.workflow_trace)
        self.assertIn("story_drafter", story_result.novel_package.workflow_trace)
        self.assertIn("cast_analyzer", story_result.novel_package.workflow_trace)
        persisted_novel_package = read_json(story_result.novel_package_path)
        persisted_novel_audit = read_json(story_result.novel_audit_path)
        persisted_story_memory = read_json(story_result.story_memory_path)
        self.assertNotIn("review", persisted_novel_package)
        self.assertNotIn("workflow_trace", persisted_novel_package)
        self.assertNotIn("premise", persisted_novel_package["outline"])
        self.assertNotIn("theme", persisted_novel_package["outline"])
        self.assertNotIn("agent_notes", persisted_novel_package["outline"])
        self.assertNotIn("visual_hooks", persisted_novel_package["chapters"][0])
        self.assertNotIn("continuity_refs", persisted_novel_package["chapters"][0])
        self.assertIn("review", persisted_novel_audit)
        self.assertIn("workflow_trace", persisted_novel_audit)
        self.assertIn("outline_context", persisted_novel_audit)
        self.assertIn("chapter_context", persisted_novel_audit)
        self.assertEqual(
            persisted_story_memory["story_identity"]["story_title"],
            story_result.novel_package.outline.title,
        )
        self.assertEqual(
            persisted_story_memory["planning_index"]["chapter_count"],
            len(story_result.novel_package.outline.chapters),
        )
        self.assertEqual(
            persisted_story_memory["generation_notes"]["last_successful_stage"],
            "video-segment-plan-merged",
        )
        self.assertTrue(
            all(item.voice_profile.voice_style for item in story_result.novel_package.outline.characters)
        )
        self.assertTrue(
            all(item.voice_profile.timbre for item in story_result.novel_package.outline.characters)
        )
        self.assertTrue(
            all(item.voice_profile.forbidden_voice_changes for item in story_result.novel_package.outline.characters)
        )
        character_result = run_character_image_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_characters=False,
        )
        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=character_result.output_dir,
            submit_scenes=False,
        )
        render_result = run_video_render_pipeline(
            config=config,
            project_root=ROOT,
            output_root=scene_result.output_dir,
            submit_seedance=False,
        )
        self.assertTrue(character_result.character_bible_path.exists())
        self.assertTrue(scene_result.scene_plan_path.exists())
        self.assertTrue(scene_result.segment_plan_path.exists())
        self.assertTrue(render_result.manifest_path.exists())
        self.assertTrue(scene_result.seedream_execution_path.exists())
        self.assertTrue(render_result.seedance_execution_path.exists())
        self.assertIsNone(render_result.full_story_path)
        self.assertGreater(len(scene_result.project_package.scenes), 0)
        self.assertGreater(len(scene_result.project_package.segments), 0)
        self.assertGreater(len(scene_result.project_package.seedance_manifest.clips), 0)
        self.assertTrue(
            all(item.scene_bible.location for item in scene_result.project_package.scenes)
        )
        self.assertTrue(
            all(item.scene_bible.continuity_notes for item in scene_result.project_package.scenes)
        )
        self.assertTrue(
            all(item.scene_master_frame_prompt for item in scene_result.project_package.scenes)
        )
        self.assertTrue(
            all(item.scene_master_frame_path.endswith("_master.png") for item in scene_result.project_package.scenes)
        )
        self.assertTrue(
            all(item.scene_bible.location for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.scene_bible.continuity_notes for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.shot_state.framing for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.shot_state.action_progression for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.continuity_link.transition_mode for item in scene_result.project_package.segments)
        )
        self.assertEqual(
            {item.chapter_number for item in scene_result.project_package.segments},
            {item.number for item in story_result.novel_package.outline.chapters},
        )
        self.assertTrue(
            all(
                (item.narration and item.narration.strip()) or item.dialogue_lines
                for item in scene_result.project_package.segments
            )
        )
        self.assertTrue(
            all(item.subtitle_lines for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.sound_effects for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.music_direction for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(item.timed_beats for item in scene_result.project_package.segments)
        )
        self.assertTrue(
            all(
                ("对白：" in item.prompt)
                or ("旁白：" in item.prompt)
                or ("本段无对白、无旁白、无字幕" in item.prompt)
                for item in scene_result.project_package.seedance_manifest.clips
            )
        )
        self.assertTrue(
            all(
                ("角色音色：" in item.prompt and "禁止变化：" in item.prompt)
                or ("本段无对白、无旁白、无字幕" in item.prompt)
                for item in scene_result.project_package.seedance_manifest.clips
            )
        )
        self.assertTrue(
            all(
                ("硬字幕样式：" in item.prompt and "硬字幕文案：" in item.prompt)
                or ("字幕约束：本段没有可烧录字幕" in item.prompt)
                for item in scene_result.project_package.seedance_manifest.clips
            )
        )
        self.assertTrue(
            all("时间节拍：" in item.prompt for item in scene_result.project_package.seedance_manifest.clips)
        )
        self.assertTrue(
            all(item.image_kind == "turnaround_sheet" for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("统一三视图模板 SF-TURN-01" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("横版 16:9" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("纯白色" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("左栏正面，中栏左侧面，右栏背面" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("画面顶部只允许出现角色中文姓名" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("画面唯一可见文字：" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all(
                "不得写性别、身份、职业、角色定位" in item.prompt
                for item in scene_result.project_package.character_images
            )
        )
        self.assertTrue(
            all("同一种美术风格" in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("主配色" not in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all("2x2 信息格" not in item.prompt for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.use_as_reference for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.output_path.endswith("_sheet.png") for item in scene_result.project_package.character_images)
        )
        self.assertTrue(
            all(item.reference_images for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all(item.scene_master_frame_prompt for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all(item.scene_master_frame_path.endswith("_master.png") for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all("图片1是场景参考" in item.start_frame_prompt for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all(
                (
                    "只画当前帧真正出镜的角色" in item.start_frame_prompt
                    or "不要出现人物" in item.start_frame_prompt
                )
                for item in scene_result.project_package.scene_images
            )
        )
        self.assertTrue(
            all("保持图片1里的" in item.start_frame_prompt for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all("纯画面，不要文字、字幕、水印或 Logo。" in item.start_frame_prompt for item in scene_result.project_package.scene_images)
        )
        self.assertTrue(
            all("纯画面，不要文字、字幕、水印或 Logo。" in item.end_frame_prompt for item in scene_result.project_package.scene_images)
        )
        persisted_scene_plan = read_json(scene_result.scene_plan_path)
        self.assertTrue(
            all(item.get("scene_bible") for item in persisted_scene_plan["scenes"])
        )
        self.assertTrue(
            all(item.get("scene_master_frame_prompt") for item in persisted_scene_plan["scenes"])
        )
        self.assertTrue(
            all(str(item.get("scene_master_frame_path", "")).endswith("_master.png") for item in persisted_scene_plan["scenes"])
        )
        persisted_segment_plan = read_json(scene_result.segment_plan_path)
        self.assertTrue(
            all(item.get("scene_bible") for item in persisted_segment_plan)
        )
        self.assertTrue(
            all(item.get("shot_state") for item in persisted_segment_plan)
        )
        self.assertTrue(
            all(item.get("continuity_link") for item in persisted_segment_plan)
        )
        self.assertFalse(scene_result.seedream_execution.submitted)
        self.assertFalse(render_result.seedance_execution.submitted)

    def test_story_scene_structure_and_segment_contract_pipelines(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=self.video_backend,
        )
        self.assertTrue(scene_structure.novel_package_path.exists())
        self.assertTrue(scene_structure.novel_audit_path.exists())
        self.assertTrue(scene_structure.story_memory_path.exists())
        self.assertTrue(scene_structure.character_bible_path.exists())
        self.assertTrue(scene_structure.scene_plan_path.exists())
        self.assertFalse((generation.output_dir / "segment_plan.json").exists())
        stage_one_memory = read_json(scene_structure.story_memory_path)
        self.assertEqual(
            stage_one_memory["generation_notes"]["last_successful_stage"],
            "video-scene-structure",
        )
        stage_one_scene_plan = read_json(scene_structure.scene_plan_path)
        self.assertTrue(stage_one_scene_plan["scenes"])
        self.assertTrue(all(not item.get("segments") for item in stage_one_scene_plan["scenes"]))
        self.assertTrue(all(item.get("covered_event_ids") for item in stage_one_scene_plan["scenes"]))
        self.assertTrue(all(item.get("covered_event_summaries") for item in stage_one_scene_plan["scenes"]))

        segment_contracts = run_story_segment_contracts_pipeline(
            novel_package=scene_structure.novel_package,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.video_backend,
        )
        self.assertTrue(segment_contracts.story_memory_path.exists())
        self.assertTrue(segment_contracts.character_images_path.exists())
        self.assertTrue(segment_contracts.scene_plan_path.exists())
        self.assertTrue(segment_contracts.segment_plan_path.exists())
        self.assertTrue(segment_contracts.scene_images_path.exists())
        self.assertTrue(segment_contracts.seedance_manifest_path.exists())
        stage_two_memory = read_json(segment_contracts.story_memory_path)
        self.assertEqual(
            stage_two_memory["generation_notes"]["last_successful_stage"],
            "video-segment-plan-merged",
        )
        self.assertTrue(
            all(item.get("carry_over_summary", "") for item in stage_two_memory["chapter_states"])
        )
        self.assertTrue(
            all(isinstance(item.get("carry_over_visuals", []), list) for item in stage_two_memory["chapter_states"])
        )
        self.assertTrue(
            all(isinstance(item.get("carry_over_props", []), list) for item in stage_two_memory["chapter_states"])
        )
        self.assertTrue(
            all(isinstance(item.get("relationship_state", []), list) for item in stage_two_memory["chapter_states"])
        )

    def test_scene_structure_retries_when_scene_planner_omits_tail_events(self) -> None:
        class SceneCoverageRetryBackend(DeterministicVideoBackend):
            def __init__(self) -> None:
                super().__init__()
                self.event_calls = 0
                self.scene_calls = 0

            def generate_structured(self, request: PromptRequest, schema):
                task = str(request.metadata.get("task", "")).strip()
                if task == "video-chapter-event-planner":
                    self.event_calls += 1
                    return ChapterCoveragePlanSchema.model_validate(
                        {
                            "chapter_number": 1,
                            "events": [
                                {
                                    "event_id": "ch01-ev01",
                                    "summary": "林栀主动找到周骁。",
                                    "source_evidence": ["主动找到"],
                                    "involved_characters": ["林栀", "周骁"],
                                },
                                {
                                    "event_id": "ch01-ev02",
                                    "summary": "林栀终于说出口。",
                                    "source_evidence": ["说出口"],
                                    "involved_characters": ["林栀", "周骁"],
                                },
                                {
                                    "event_id": "ch01-ev03",
                                    "summary": "周骁给出关键回应。",
                                    "source_evidence": ["关键回应"],
                                    "involved_characters": ["林栀", "周骁"],
                                },
                                {
                                    "event_id": "ch01-ev04",
                                    "summary": "两人的情绪和关系发生明确变化。",
                                    "source_evidence": ["明确变化"],
                                    "involved_characters": ["林栀", "周骁"],
                                },
                            ],
                        }
                    )
                if task == "video-chapter-scene-planner":
                    self.scene_calls += 1
                    if self.scene_calls == 1:
                        return ChapterSceneStructureSchema.model_validate(
                            {
                                "scenes": [
                                    {
                                        "scene_id": "ch01-sc01",
                                        "chapter_number": 1,
                                        "title": "相遇与表白",
                                        "summary": "林栀找到周骁并说出口，周骁给出回应。",
                                        "scene_anchor": "统一测试场景",
                                        "involved_characters": ["林栀", "周骁"],
                                        "covered_event_ids": [
                                            "ch01-ev01",
                                            "ch01-ev02",
                                            "ch01-ev03",
                                        ],
                                        "scene_bible": {
                                            "location": "统一测试场景",
                                            "time_window": "傍晚",
                                            "weather": "微风",
                                            "lighting": "柔和侧光",
                                            "dominant_palette": ["米白", "灰蓝"],
                                            "background_anchors": ["固定背景锚点"],
                                            "fixed_props": ["关键道具"],
                                            "spatial_layout": "两人位于画面中部",
                                            "character_blocking": "两人面对面",
                                            "continuity_notes": "保持空间连续",
                                        },
                                    }
                                ]
                            }
                        )
                    return ChapterSceneStructureSchema.model_validate(
                        {
                            "scenes": [
                                {
                                    "scene_id": "ch01-sc01",
                                    "chapter_number": 1,
                                    "title": "找到并说出口",
                                    "summary": "林栀主动找到周骁，终于把话说出口。",
                                    "scene_anchor": "统一测试场景前半段",
                                    "involved_characters": ["林栀", "周骁"],
                                    "covered_event_ids": ["ch01-ev01", "ch01-ev02"],
                                    "scene_bible": {
                                        "location": "统一测试场景",
                                        "time_window": "傍晚",
                                        "weather": "微风",
                                        "lighting": "柔和侧光",
                                        "dominant_palette": ["米白", "灰蓝"],
                                        "background_anchors": ["固定背景锚点"],
                                        "fixed_props": ["关键道具"],
                                        "spatial_layout": "两人位于画面中部",
                                        "character_blocking": "林栀主动靠近周骁",
                                        "continuity_notes": "保持空间连续",
                                    },
                                },
                                {
                                    "scene_id": "ch01-sc02",
                                    "chapter_number": 1,
                                    "title": "回应与关系变化",
                                    "summary": "周骁回应后，两人的情绪和关系发生明确变化。",
                                    "scene_anchor": "统一测试场景后半段",
                                    "involved_characters": ["林栀", "周骁"],
                                    "covered_event_ids": ["ch01-ev03", "ch01-ev04"],
                                    "scene_transition_contract": {
                                        "previous_scene_id": "ch01-sc01",
                                        "transition_mode": "direct_continue",
                                        "previous_scene_exit_state": "林栀刚把话说出口，两人仍停在原地等待回应。",
                                        "next_scene_entry_match": "当前场开头先承接两人停在统一测试场景后半段等待回应的状态，再带出周骁准备回应、两人距离即将收紧的开场。",
                                        "bridge_action": "先停在说出口后的沉默里，再让周骁接住这次告白。",
                                        "carry_over_elements": ["两人站位", "统一测试场景", "说出口后的停顿"],
                                        "screen_direction_policy": "保持面对面站位，不要突然反轴。",
                                        "visual_bridge": "先看统一测试场景后半段里两人停住的姿态，再转到周骁开始回应、两人距离收紧。",
                                        "audio_bridge": "ambient_bridge",
                                        "transition_focus_seconds": 1,
                                    },
                                    "scene_bible": {
                                        "location": "统一测试场景",
                                        "time_window": "傍晚",
                                        "weather": "微风",
                                        "lighting": "柔和侧光",
                                        "dominant_palette": ["米白", "灰蓝"],
                                        "background_anchors": ["固定背景锚点"],
                                        "fixed_props": ["关键道具"],
                                        "spatial_layout": "两人仍停留在同一空间",
                                        "character_blocking": "周骁回应后，两人距离收紧",
                                        "continuity_notes": "保持关系推进连续",
                                    },
                                },
                            ]
                        }
                    )
                if task == "video-scene-chunk-planner":
                    scene_id = str(request.metadata.get("scene_id", "")).strip()
                    if scene_id == "ch01-sc01":
                        return SceneSegmentChunkPlanSchema.model_validate(
                            {
                                "scene_id": scene_id,
                                "chapter_number": 1,
                                "chunks": [
                                    {
                                        "chunk_id": "ch01-sc01-chunk01",
                                        "order_index": 1,
                                        "title": "找到并说出口",
                                        "summary": "林栀主动找到周骁，终于把话说出口。",
                                        "must_cover": ["林栀主动找到周骁", "林栀终于说出口"],
                                        "transition_goal": "林栀已经说出口，停在原地等待下一场推进",
                                        "expected_segment_count": 1,
                                    }
                                ],
                            }
                        )
                    if scene_id == "ch01-sc02":
                        return SceneSegmentChunkPlanSchema.model_validate(
                            {
                                "scene_id": scene_id,
                                "chapter_number": 1,
                                "chunks": [
                                    {
                                        "chunk_id": "ch01-sc02-chunk01",
                                        "order_index": 1,
                                        "title": "承接停顿，给出回应",
                                        "summary": "先承接林栀说出口后的停顿，再由周骁给出回应，关系随之变化。",
                                        "must_cover": ["承接说出口后的沉默", "周骁给出回应", "两人关系发生明确变化"],
                                        "transition_goal": "回应落地后，两人的关系状态已经改变",
                                        "expected_segment_count": 2,
                                    }
                                ],
                            }
                        )
                if task == "video-scene-segment-planner":
                    scene_id = str(request.metadata.get("scene_id", "")).strip()
                    if scene_id == "ch01-sc02":
                        return SceneSegmentContractBatchSchema.model_validate(
                            {
                                "scene_id": scene_id,
                                "chapter_number": 1,
                                "segments": [
                                    {
                                        "segment_id": "ch01-sc02-seg01",
                                        "chapter_number": 1,
                                        "scene_id": scene_id,
                                        "title": "停顿后的回应",
                                        "summary": "周骁承接林栀说出口后的停顿，给出回应，两人的关系随之变化。",
                                        "involved_characters": ["林栀", "周骁"],
                                        "start_frame_characters": ["林栀", "周骁"],
                                        "end_frame_characters": ["林栀", "周骁"],
                                        "timed_beats": [
                                            "0-3秒：承接林栀说出口后的沉默停顿，周骁抬眼接住这次告白",
                                            "3-6秒：周骁给出回应，两人的距离和情绪关系随之变化",
                                        ],
                                        "duration_seconds": 6,
                                        "requires_mid_frame": False,
                                        "transition_hint": "auto",
                                        "shot_state": {
                                            "framing": "双人中景",
                                            "camera_motion": "先稳住停顿，再轻微前推到回应落地",
                                            "blocking": "两人面对面停住，周骁先接住沉默再回应",
                                            "action_progression": "承接停顿 -> 周骁回应 -> 关系变化",
                                            "emotion_progression": "从屏息等待到回应落地后的明显松动",
                                            "screen_direction": "保持面对面轴线",
                                            "end_state_lock": "周骁回应完成后，两人的关系状态已经改变",
                                        },
                                        "continuity_link": {
                                            "previous_segment_id": "",
                                            "transition_mode": "start",
                                            "opening_match": "林栀刚把话说出口，两人仍停在原地等待回应，周骁开始抬眼接住这次告白。",
                                            "carry_over_elements": [],
                                            "allowed_changes": "在停顿中承接开场，再推进到周骁回应和关系变化",
                                            "transition_reason": "作为当前 scene 首段，先消费跨场承接再进入本 scene 新推进",
                                        },
                                    }
                                ],
                            }
                        )
                return super().generate_structured(request, schema)

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="镜湖告白",
            idea="大学校园里的双人告白故事",
            genre="校园告白",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "scene-coverage-source",
        )
        backend = SceneCoverageRetryBackend()
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=backend,
        )

        self.assertEqual(backend.event_calls, 1)
        self.assertEqual(backend.scene_calls, 2)
        persisted_scene_plan = read_json(scene_structure.scene_plan_path)
        self.assertEqual(len(persisted_scene_plan["scenes"]), 2)
        covered_event_ids = [
            event_id
            for scene in persisted_scene_plan["scenes"]
            for event_id in scene["covered_event_ids"]
        ]
        self.assertEqual(
            covered_event_ids,
            ["ch01-ev01", "ch01-ev02", "ch01-ev03", "ch01-ev04"],
        )
        segment_contracts = run_story_segment_contracts_pipeline(
            novel_package=scene_structure.novel_package,
            config=config,
            project_root=ROOT,
            output_root=scene_structure.output_dir,
            backend=backend,
            scene_structure_artifacts=scene_structure.scene_structure,
        )
        persisted_scene_plan = read_json(segment_contracts.scene_plan_path)
        self.assertTrue(
            all(item.get("scene_bible") for item in persisted_scene_plan["scenes"])
        )
        self.assertTrue(
            all(item.get("covered_event_summaries") for item in persisted_scene_plan["scenes"])
        )
        self.assertTrue(
            all(item.get("scene_master_frame_prompt") for item in persisted_scene_plan["scenes"])
        )
        self.assertTrue(
            all(str(item.get("scene_master_frame_path", "")).endswith("_master.png") for item in persisted_scene_plan["scenes"])
        )
        self.assertEqual(
            [
                event_id
                for scene in persisted_scene_plan["scenes"]
                for event_id in scene["covered_event_ids"]
            ],
            ["ch01-ev01", "ch01-ev02", "ch01-ev03", "ch01-ev04"],
        )
        self.assertEqual(
            persisted_scene_plan["scenes"][1]["scene_transition_contract"]["previous_scene_id"],
            "ch01-sc01",
        )
        persisted_segment_plan = read_json(segment_contracts.segment_plan_path)
        self.assertTrue(
            all(item.get("scene_bible") for item in persisted_segment_plan)
        )
        self.assertTrue(
            all(item.get("shot_state") for item in persisted_segment_plan)
        )
        self.assertTrue(
            all(item.get("continuity_link") for item in persisted_segment_plan)
        )

    def test_story_pipeline_matches_split_structuring_outputs(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="全链路结构化一致性测试",
            idea="毕业前夕，两个人在校园里逐步靠近彼此。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=2,
            total_word_target=1800,
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "compat-source",
        )

        split_scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "compat-split",
            backend=self.story_backend,
            video_backend=self.video_backend,
        )
        split_segment_contracts = run_story_segment_contracts_pipeline(
            novel_package=split_scene_structure.novel_package,
            config=config,
            project_root=ROOT,
            output_root=split_scene_structure.output_dir,
            backend=self.video_backend,
            scene_structure_artifacts=split_scene_structure.scene_structure,
        )
        full_pipeline = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "full-pipeline",
        )

        split_scene_plan = read_json(split_segment_contracts.scene_plan_path)
        full_scene_plan = read_json(full_pipeline.scene_plan_path)
        self.assertEqual(
            [item["scene_id"] for item in split_scene_plan["scenes"]],
            [item["scene_id"] for item in full_scene_plan["scenes"]],
        )
        self.assertEqual(
            [item["title"] for item in split_scene_plan["scenes"]],
            [item["title"] for item in full_scene_plan["scenes"]],
        )
        self.assertEqual(
            [
                [segment["segment_id"] for segment in item.get("segments", [])]
                for item in split_scene_plan["scenes"]
            ],
            [
                [segment["segment_id"] for segment in item.get("segments", [])]
                for item in full_scene_plan["scenes"]
            ],
        )

        split_segment_plan = read_json(split_segment_contracts.segment_plan_path)
        full_segment_plan = read_json(full_pipeline.segment_plan_path)
        self.assertEqual(
            [item["segment_id"] for item in split_segment_plan],
            [item["segment_id"] for item in full_segment_plan],
        )
        self.assertEqual(
            [item["scene_id"] for item in split_segment_plan],
            [item["scene_id"] for item in full_segment_plan],
        )

        split_story_memory = read_json(split_segment_contracts.story_memory_path)
        full_story_memory = read_json(full_pipeline.story_memory_path)
        self.assertEqual(
            split_story_memory["planning_index"],
            full_story_memory["planning_index"],
        )
        self.assertEqual(
            [
                {
                    "chapter_number": item["chapter_number"],
                    "generated_scene_ids": item.get("generated_scene_ids", []),
                    "generated_segment_ids": item.get("generated_segment_ids", []),
                    "carry_over_summary": item.get("carry_over_summary", ""),
                }
                for item in split_story_memory["chapter_states"]
            ],
            [
                {
                    "chapter_number": item["chapter_number"],
                    "generated_scene_ids": item.get("generated_scene_ids", []),
                    "generated_segment_ids": item.get("generated_segment_ids", []),
                    "carry_over_summary": item.get("carry_over_summary", ""),
                }
                for item in full_story_memory["chapter_states"]
            ],
        )

    def test_segment_contracts_checkpoint_and_resume_skips_completed_scenes_in_failed_chapter(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="断点续跑测试",
            idea="三章连续推进的校园情感短篇。",
            genre="青春",
            tone="克制电影感",
            target_audience="大众读者",
            chapter_count=3,
            total_word_target=1800,
            must_include=["三章顺序推进"],
            style_keywords=["连贯", "清晰"],
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=self.video_backend,
        )
        injected_scene_payloads: list[dict[str, object]] = []
        scene_two_injected = False
        for scene in scene_structure.scene_structure.scene_plan.scenes:
            injected_scene_payloads.append(scene.model_dump())
            if scene.chapter_number == 2 and not scene_two_injected:
                duplicate_scene = scene.model_dump()
                duplicate_scene["scene_id"] = "ch02-sc02"
                duplicate_scene["title"] = f"{scene.title} / 后续"
                duplicate_scene["summary"] = f"{scene.summary} 后续推进。"
                duplicate_scene["segments"] = []
                injected_scene_payloads.append(duplicate_scene)
                scene_two_injected = True
        self.assertTrue(scene_two_injected)
        scene_structure.scene_structure.scene_plan = VideoSegmentPlanSchema.model_validate(
            {"scenes": injected_scene_payloads}
        )

        chapter_scene_ids: dict[int, list[str]] = {}
        for scene in scene_structure.scene_structure.scene_plan.scenes:
            chapter_scene_ids.setdefault(scene.chapter_number, []).append(scene.scene_id)
        self.assertGreaterEqual(len(chapter_scene_ids.get(2, [])), 2)

        original_chunk_builder = NovelToVideoService._build_scene_chunk_contract_batch
        attempted_scenes: list[str] = []
        failed_scene_id = chapter_scene_ids[2][1]
        completed_before_failure = chapter_scene_ids[1] + [chapter_scene_ids[2][0]]
        failed_chunk_id = f"{failed_scene_id}-chunk01"

        def fail_on_second_scene_of_second_chapter(
            service,
            *,
            novel_package,
            story_memory,
            chapter_number,
            scene,
            chunk,
            previous_chunk_exit_state,
            previous_tail_segment,
        ):
            attempted_scenes.append(scene.scene_id)
            if chapter_number == 2 and scene.scene_id == failed_scene_id:
                raise VideoStructuredGenerationError(
                    task="video-scene-segment-planner",
                    schema_name="SceneSegmentContractBatchSchema",
                    attempts=3,
                    cause=RuntimeError("scene failed"),
                    metadata={
                        "chapter_number": 2,
                        "scene_id": failed_scene_id,
                        "chunk_id": failed_chunk_id,
                    },
                )
            return original_chunk_builder(
                service,
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter_number,
                scene=scene,
                chunk=chunk,
                previous_chunk_exit_state=previous_chunk_exit_state,
                previous_tail_segment=previous_tail_segment,
            )

        with patch.object(
            NovelToVideoService,
            "_build_scene_chunk_contract_batch",
            autospec=True,
            side_effect=fail_on_second_scene_of_second_chapter,
        ):
            with self.assertRaises(VideoStructuredGenerationError):
                run_story_segment_contracts_pipeline(
                    novel_package=scene_structure.novel_package,
                    config=config,
                    project_root=ROOT,
                    output_root=generation.output_dir,
                    backend=self.video_backend,
                    scene_structure_artifacts=scene_structure.scene_structure,
                )

        self.assertEqual(
            attempted_scenes,
            chapter_scene_ids[1] + chapter_scene_ids[2][:2],
        )
        progress = load_segment_contract_progress(generation.output_dir)
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(progress.status, "failed")
        self.assertEqual(progress.completed_chapters, 1)
        self.assertEqual(progress.failed_chapter_number, 2)
        self.assertEqual(progress.failed_scene_id, failed_scene_id)
        self.assertEqual(progress.failed_chunk_id, failed_chunk_id)
        self.assertEqual(
            progress.completed_scene_count,
            len(completed_before_failure),
        )
        self.assertTrue(progress.resume_ready)
        partial_plan = load_video_planning_artifacts(generation.output_dir)
        self.assertEqual(
            [scene.scene_id for scene in partial_plan.project_package.scenes],
            completed_before_failure,
        )

        resumed_scenes: list[str] = []

        def record_resumed_scenes(
            service,
            *,
            novel_package,
            story_memory,
            chapter_number,
            scene,
            chunk,
            previous_chunk_exit_state,
            previous_tail_segment,
        ):
            resumed_scenes.append(scene.scene_id)
            return original_chunk_builder(
                service,
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter_number,
                scene=scene,
                chunk=chunk,
                previous_chunk_exit_state=previous_chunk_exit_state,
                previous_tail_segment=previous_tail_segment,
            )

        with patch.object(
            NovelToVideoService,
            "_build_scene_chunk_contract_batch",
            autospec=True,
            side_effect=record_resumed_scenes,
        ):
            resumed = run_story_segment_contracts_pipeline(
                novel_package=scene_structure.novel_package,
                config=config,
                project_root=ROOT,
                output_root=generation.output_dir,
                backend=self.video_backend,
                scene_structure_artifacts=scene_structure.scene_structure,
                resume_from_progress=True,
            )

        self.assertFalse(set(completed_before_failure).intersection(resumed_scenes))
        self.assertEqual(
            resumed_scenes,
            chapter_scene_ids[2][1:] + chapter_scene_ids[3],
        )
        self.assertTrue(resumed.segment_contract_progress_path.exists())
        resumed_progress = load_segment_contract_progress(generation.output_dir)
        self.assertIsNotNone(resumed_progress)
        assert resumed_progress is not None
        self.assertEqual(resumed_progress.status, "completed")
        self.assertEqual(resumed_progress.completed_chapters, 3)
        self.assertEqual(resumed_progress.total_chapters, 3)
        self.assertEqual(
            resumed_progress.completed_scene_count,
            sum(len(scene_ids) for scene_ids in chapter_scene_ids.values()),
        )
        self.assertFalse(resumed_progress.resume_ready)
        resumed_plan = load_video_planning_artifacts(generation.output_dir)
        self.assertEqual(
            [scene.scene_id for scene in resumed_plan.project_package.scenes],
            chapter_scene_ids[1] + chapter_scene_ids[2] + chapter_scene_ids[3],
        )

    def test_segment_contracts_checkpoint_and_resume_within_scene_chunk(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="scene 内 chunk 续跑测试",
            idea="一个男生在湖边等待，随后与喜欢的人正式碰面。",
            genre="校园情感",
            tone="克制电影感",
            target_audience="大众读者",
            chapter_count=1,
            total_word_target=1200,
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-resume",
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=self.video_backend,
        )
        scene_id = scene_structure.scene_structure.scene_plan.scenes[0].scene_id
        chapter_number = scene_structure.scene_structure.scene_plan.scenes[0].chapter_number
        character_names = [item.name for item in scene_structure.novel_package.outline.characters[:2]]
        if not character_names:
            character_names = ["主角"]
        first_character = character_names[0]
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "chunks": [
                    {
                        "chunk_id": "wait",
                        "order_index": 1,
                        "title": "等待",
                        "summary": "主角在湖边等待，对方尚未入镜。",
                        "must_cover": ["单人等待", "听见脚步声"],
                        "transition_goal": "停在回头前的一刻。",
                        "expected_segment_count": 1,
                    },
                    {
                        "chunk_id": "meet",
                        "order_index": 2,
                        "title": "会面",
                        "summary": "对方走近，两人正式开始交谈。",
                        "must_cover": ["对方入镜", "正式开口"],
                        "transition_goal": "从等待推进到面对面交流。",
                        "expected_segment_count": 1,
                    },
                ],
            }
        )
        first_batch = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "segments": [
                    {
                        "segment_id": f"{scene_id}-seg01",
                        "chapter_number": chapter_number,
                        "scene_id": scene_id,
                        "title": "等待",
                        "summary": "主角在湖边等待，对方尚未入镜。",
                        "involved_characters": [first_character],
                        "start_frame_characters": [first_character],
                        "mid_frame_characters": [],
                        "end_frame_characters": [first_character],
                        "narration": "他在湖边等待，听见脚步声后微微回头。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["他在湖边等待，听见脚步声后微微回头。"],
                        "timed_beats": ["0-6秒：他在湖边等待，听见脚步声后微微回头。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "中景",
                            "camera_motion": "缓慢推进",
                            "blocking": "单人站在湖边步道侧前方",
                            "action_progression": "等待并在尾部听见脚步声",
                            "emotion_progression": "紧张逐步累积",
                            "prop_continuity": "书包停在肩侧",
                            "screen_direction": "保持向右前方等待",
                            "end_state_lock": "他回头一半，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "主角已站在湖边步道，面向湖面等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立单人等待的开场基线。",
                            "transition_reason": "当前 scene 的起始段。",
                        },
                    }
                ],
            }
        )
        second_batch = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "segments": [
                    {
                        "segment_id": f"{scene_id}-seg01",
                        "chapter_number": chapter_number,
                        "scene_id": scene_id,
                        "title": "会面",
                        "summary": "对方走近后，两人正式开始交谈。",
                        "involved_characters": character_names,
                        "start_frame_characters": [first_character],
                        "mid_frame_characters": character_names,
                        "end_frame_characters": character_names or [first_character],
                        "narration": "脚步声靠近，他转身迎上对方，终于开口。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["脚步声靠近，他转身迎上对方，终于开口。"],
                        "timed_beats": ["0-6秒：脚步声靠近，他转身迎上对方，终于开口。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "continue",
                        "shot_state": {
                            "framing": "中景转双人中近景",
                            "camera_motion": "轻微前推",
                            "blocking": "另一人从右侧入镜并停在主角面前",
                            "action_progression": "从回头承接到面对面开口",
                            "emotion_progression": "紧张转为对视交流",
                            "prop_continuity": "书包仍在肩侧",
                            "screen_direction": "延续上一段的右向视线",
                            "end_state_lock": "两人停在面对面对话姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": f"{scene_id}-seg01",
                            "transition_mode": "continue",
                            "opening_match": "承接上一段尾部，他仍停在湖边并回头迎向来人。",
                            "carry_over_elements": ["湖边站位", "书包", "右向视线"],
                            "allowed_changes": "对方入镜，两人从等待推进到正式会面。",
                            "transition_reason": "同一 scene 内继续推进到会面动作。",
                        },
                    }
                ],
            }
        )

        attempted_chunks: list[str] = []

        def fail_on_second_chunk(
            service,
            *,
            novel_package,
            story_memory,
            chapter_number,
            scene,
            chunk,
            previous_chunk_exit_state,
            previous_tail_segment,
        ):
            attempted_chunks.append(chunk.chunk_id)
            if chunk.chunk_id == "meet":
                raise VideoStructuredGenerationError(
                    task="video-scene-segment-planner",
                    schema_name="SceneSegmentContractBatchSchema",
                    attempts=3,
                    cause=RuntimeError("chunk failed"),
                    metadata={
                        "chapter_number": chapter_number,
                        "scene_id": scene.scene_id,
                        "chunk_id": chunk.chunk_id,
                        "chunk_order_index": chunk.order_index,
                    },
                )
            return first_batch

        with patch.object(
            NovelToVideoService,
            "_plan_scene_chunk_outline",
            autospec=True,
            return_value=chunk_plan,
        ) as chunk_plan_mock:
            with patch.object(
                NovelToVideoService,
                "_build_scene_chunk_contract_batch",
                autospec=True,
                side_effect=fail_on_second_chunk,
            ):
                with self.assertRaises(VideoStructuredGenerationError):
                    run_story_segment_contracts_pipeline(
                        novel_package=scene_structure.novel_package,
                        config=config,
                        project_root=ROOT,
                        output_root=generation.output_dir,
                        backend=self.video_backend,
                        scene_structure_artifacts=scene_structure.scene_structure,
                    )

        self.assertEqual(chunk_plan_mock.call_count, 1)
        self.assertEqual(attempted_chunks, ["wait", "meet"])
        progress = load_segment_contract_progress(generation.output_dir)
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(progress.status, "failed")
        self.assertEqual(progress.completed_chunk_count, 1)
        self.assertEqual(progress.failed_chunk_id, "meet")
        self.assertEqual(progress.failed_scene_id, scene_id)
        self.assertTrue(progress.resume_ready)
        scene_progress = progress.chapters[0].scenes[0]
        self.assertEqual(scene_progress.chunk_count, 2)
        self.assertEqual(scene_progress.completed_chunk_count, 1)
        self.assertEqual(scene_progress.failed_chunk_id, "meet")
        self.assertEqual(
            [item.status for item in scene_progress.chunks],
            ["completed", "failed"],
        )

        partial_plan = load_video_planning_artifacts(generation.output_dir)
        self.assertEqual(
            [item.segment_id for item in partial_plan.project_package.segments],
            [f"{scene_id}-seg01"],
        )

        resumed_chunks: list[str] = []

        def build_remaining_chunk(
            service,
            *,
            novel_package,
            story_memory,
            chapter_number,
            scene,
            chunk,
            previous_chunk_exit_state,
            previous_tail_segment,
        ):
            resumed_chunks.append(chunk.chunk_id)
            self.assertEqual(chunk.chunk_id, "meet")
            self.assertIsNotNone(previous_tail_segment)
            self.assertEqual(previous_tail_segment.segment_id, f"{scene_id}-seg01")
            return second_batch

        with patch.object(
            NovelToVideoService,
            "_plan_scene_chunk_outline",
            autospec=True,
            side_effect=AssertionError("resume should reuse stored chunk plan"),
        ):
            with patch.object(
                NovelToVideoService,
                "_build_scene_chunk_contract_batch",
                autospec=True,
                side_effect=build_remaining_chunk,
            ):
                resumed = run_story_segment_contracts_pipeline(
                    novel_package=scene_structure.novel_package,
                    config=config,
                    project_root=ROOT,
                    output_root=generation.output_dir,
                    backend=self.video_backend,
                    scene_structure_artifacts=scene_structure.scene_structure,
                    resume_from_progress=True,
                )

        self.assertTrue(resumed.segment_contract_progress_path.exists())
        self.assertEqual(resumed_chunks, ["meet"])
        resumed_progress = load_segment_contract_progress(generation.output_dir)
        self.assertIsNotNone(resumed_progress)
        assert resumed_progress is not None
        self.assertEqual(resumed_progress.status, "completed")
        self.assertEqual(resumed_progress.total_chunks, 2)
        self.assertEqual(resumed_progress.completed_chunk_count, 2)
        self.assertFalse(resumed_progress.resume_ready)
        resumed_scene_progress = resumed_progress.chapters[0].scenes[0]
        self.assertEqual(resumed_scene_progress.status, "completed")
        self.assertEqual(resumed_scene_progress.completed_chunk_count, 2)
        self.assertEqual(
            [item.status for item in resumed_scene_progress.chunks],
            ["completed", "completed"],
        )
        resumed_plan = load_video_planning_artifacts(generation.output_dir)
        self.assertEqual(
            [item.segment_id for item in resumed_plan.project_package.segments],
            [f"{scene_id}-seg01", f"{scene_id}-seg02"],
        )

    def test_cast_analysis_source_evidence_must_exist_in_story_draft(self) -> None:
        service = NovelGeneratorService()
        story_draft_set = StoryDraftSetSchema(
            chapters=[
                ChapterDraftSchema(
                    number=1,
                    title="雨夜",
                    summary="林深在废弃站台调查异常广播。",
                    markdown="林深站在暴雨里的旧站台，反复核对广播记录。",
                    visual_hooks=["暴雨", "站台"],
                    continuity_refs=["异常广播"],
                )
            ]
        )
        analysis = CastAnalysisSchema(
            story_shape="single_lead_with_supporting_cast",
            recommended_core_cast_count=2,
            requires_dual_leads=False,
            explicit_counterpart=False,
            prefers_male_female_pair=False,
            cast_strategy="先稳定主角，再补配角。",
            chapter_participation_rule="主角贯穿始终。",
            ordering_rule="按优先级排序。",
            slots=[
                CastSlotSchema(
                    slot_id="lead_1",
                    tier="lead",
                    story_function="protagonist",
                    brief_label="调查员",
                    source_evidence=["林深"],
                    gender_hint="男",
                    objective="查清真相",
                    must_appear_in=["opening", "climax"],
                    order_priority=1,
                    notes="主角",
                ),
                CastSlotSchema(
                    slot_id="core_support_1",
                    tier="core_support",
                    story_function="ally",
                    brief_label="外部阻力",
                    source_evidence=["沈砚"],
                    gender_hint="男",
                    objective="制造压力",
                    must_appear_in=["midpoint"],
                    order_priority=2,
                    notes="不存在于正文",
                ),
            ],
            relationships=[
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="core_support_1",
                    relationship_type="pressure",
                    priority=1,
                    summary="制造阻力。",
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "source_evidence"):
            service._validate_cast_analysis_output(
                analysis,
                story_draft_set=story_draft_set,
            )

    def test_cast_analysis_source_evidence_accepts_name_inside_decorated_phrase(self) -> None:
        service = NovelGeneratorService()
        story_draft_set = StoryDraftSetSchema(
            chapters=[
                ChapterDraftSchema(
                    number=1,
                    title="考场外",
                    summary="林栀与监考老师周骁在考试结束后短暂对话。",
                    markdown=(
                        "林栀抱着试卷走出教学楼，周骁站在走廊尽头等她。"
                        "这位监考老师没有多说，只提醒她别把准考证落下。"
                    ),
                    visual_hooks=["教学楼", "走廊"],
                    continuity_refs=["考试结束"],
                )
            ]
        )
        analysis = CastAnalysisSchema(
            story_shape="dual_relationship_with_supporting_cast",
            recommended_core_cast_count=2,
            requires_dual_leads=True,
            explicit_counterpart=True,
            prefers_male_female_pair=True,
            cast_strategy="稳定关系双方。",
            chapter_participation_rule="双方必须共同参与关键节点。",
            ordering_rule="按 lead_1, lead_2 输出。",
            slots=[
                CastSlotSchema(
                    slot_id="lead_1",
                    tier="lead",
                    story_function="protagonist",
                    brief_label="女学生林栀",
                    source_evidence=["女学生林栀"],
                    gender_hint="女",
                    objective="确认对方是否记得自己的约定。",
                    must_appear_in=["opening", "climax"],
                    order_priority=1,
                    notes="主动方",
                ),
                CastSlotSchema(
                    slot_id="lead_2",
                    tier="lead",
                    story_function="love_interest",
                    brief_label="年轻监考老师周骁",
                    source_evidence=["年轻监考老师周骁"],
                    gender_hint="男",
                    objective="给出回应。",
                    must_appear_in=["opening", "climax"],
                    order_priority=2,
                    notes="回应方",
                ),
            ],
            relationships=[
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="lead_2",
                    relationship_type="core_relationship",
                    priority=1,
                    summary="毕业前夜的关键关系。",
                )
            ],
        )

        validated = service._validate_cast_analysis_output(
            analysis,
            story_draft_set=story_draft_set,
        )

        self.assertEqual(len(validated.slots), 2)

    def test_deterministic_character_roster_only_covers_requested_slots(self) -> None:
        brief = StoryBrief(
            title_hint="站台告白",
            idea="一个女生在列车离站前向喜欢多年的男生告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )
        architecture = StoryArchitectureSchema(
            title="站台告白",
            premise="列车离站前的告白。",
            theme="告别与勇气",
            setting="夜晚站台",
            story_engine="离站倒计时逼迫关系表态。",
            visual_motifs=["站台", "列车", "夜风"],
            tone_notes=["克制", "电影感"],
        )
        cast_analysis = CastAnalysisSchema(
            story_shape="dual_relationship_with_supporting_cast",
            recommended_core_cast_count=2,
            requires_dual_leads=True,
            explicit_counterpart=True,
            prefers_male_female_pair=True,
            cast_strategy="只稳定关系双方。",
            chapter_participation_rule="双方必须共同参与。",
            ordering_rule="lead_1, lead_2。",
            slots=[
                CastSlotSchema(
                    slot_id="lead_1",
                    tier="lead",
                    story_function="protagonist",
                    brief_label="女生",
                    source_evidence=["女生"],
                    gender_hint="女",
                    objective="告白",
                    must_appear_in=["opening", "climax"],
                    order_priority=1,
                    notes="主动方",
                ),
                CastSlotSchema(
                    slot_id="lead_2",
                    tier="lead",
                    story_function="love_interest",
                    brief_label="男生",
                    source_evidence=["男生"],
                    gender_hint="男",
                    objective="回应",
                    must_appear_in=["opening", "climax"],
                    order_priority=2,
                    notes="回应方",
                ),
                CastSlotSchema(
                    slot_id="core_support_1",
                    tier="core_support",
                    story_function="ally",
                    brief_label="朋友",
                    source_evidence=["朋友"],
                    gender_hint="女",
                    objective="助推关系",
                    must_appear_in=["midpoint"],
                    order_priority=3,
                    notes="不应进入本次角色卡",
                ),
            ],
            relationships=[
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="lead_2",
                    relationship_type="core_relationship",
                    priority=1,
                    summary="核心关系。",
                )
            ],
        )

        roster = self.novel_builder.build_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )

        self.assertEqual([item.cast_slot_id for item in roster.characters], ["lead_1", "lead_2"])

    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_character_images")
    def test_video_pipeline_does_not_auto_concat_full_story_after_successful_seedance(
        self,
        mock_generate_character_images,
        mock_generate_scene_images,
        mock_execute_manifest,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        def fake_generate_character_images(project_package, force_submit=False):
            self.assertTrue(force_submit)
            mark_runtime_character_images_completed(project_package)
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=3,
                failed_count=0,
                note="ok",
            )

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertIsNone(segment_ids)
            mark_runtime_scene_images_completed(project_package)
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=3,
                failed_count=0,
                note="ok",
            )

        mock_generate_character_images.side_effect = fake_generate_character_images
        mock_generate_scene_images.side_effect = fake_generate_scene_images

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertIsNone(segment_ids)
            mark_runtime_manifest_clips_completed(manifest)
            return SeedanceExecutionReport(
                submitted=True,
                manifest_title=manifest.title,
                completed_count=len(manifest.clips),
                failed_count=0,
                pending_count=0,
                note="ok",
            )

        mock_execute_manifest.side_effect = fake_execute_manifest

        character_result = run_character_image_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_characters=True,
        )
        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=character_result.output_dir,
            submit_scenes=True,
        )
        render_result = run_video_render_pipeline(
            config=config,
            project_root=ROOT,
            output_root=scene_result.output_dir,
            submit_seedance=True,
        )

        self.assertIsNone(render_result.full_story_path)
        self.assertEqual(len(render_result.rendered_clip_paths), len(render_result.manifest.clips))

    @patch("storyforge.pipelines.video_pipeline.concat_manifest_clips")
    def test_run_video_merge_pipeline_concats_rendered_clips_on_demand(
        self,
        mock_concat_manifest_clips,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        rendered_dir = story_result.output_dir / "rendered"
        mark_rendered_manifest_clips(
            story_result,
            clip_count=2,
            remote_status="succeeded",
            rendered_dir=rendered_dir,
        )

        expected_full_story_path = story_result.output_dir / "rendered" / "full_story.mp4"

        def fake_concat_manifest_clips(manifest, output_path):
            self.assertEqual(len(manifest.clips), 2)
            self.assertEqual(output_path, expected_full_story_path)
            output_path.write_bytes(b"merged")
            return output_path

        mock_concat_manifest_clips.side_effect = fake_concat_manifest_clips

        merge_result = run_video_merge_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
        )

        self.assertEqual(merge_result.full_story_path, expected_full_story_path)
        self.assertEqual(merge_result.merged_clip_count, 2)
        self.assertTrue(expected_full_story_path.exists())
        mock_concat_manifest_clips.assert_called_once()

    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_character_images")
    def test_seedance_skip_guard_returns_true_when_seedream_frames_fail(
        self,
        mock_generate_character_images,
        mock_generate_scene_images,
        mock_execute_manifest,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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

        character_result = run_character_image_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_characters=True,
        )
        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=character_result.output_dir,
            submit_scenes=True,
        )

        self.assertTrue(
            should_skip_seedance_after_seedream(True, scene_result.seedream_execution)
        )
        mock_execute_manifest.assert_not_called()

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    def test_run_scene_image_pipeline_only_updates_selected_segment(
        self,
        mock_generate_scene_images,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        selected_segment_id = read_json(story_result.segment_plan_path)[0]["segment_id"]

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})
            mark_runtime_scene_images_completed(
                project_package,
                segment_ids={selected_segment_id},
            )
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=2,
                failed_count=0,
                note="ok",
            )

        mock_generate_scene_images.side_effect = fake_generate_scene_images

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_scenes=True,
            segment_id=selected_segment_id,
        )

        scene_manifest = read_json(scene_result.scene_images_path)
        selected_task = next(item for item in scene_manifest if item["segment_id"] == selected_segment_id)
        untouched_tasks = [item for item in scene_manifest if item["segment_id"] != selected_segment_id]
        self.assertTrue(selected_task["start_frame_url"])
        self.assertTrue(selected_task["end_frame_url"])
        self.assertTrue(all(not item.get("start_frame_url") for item in untouched_tasks))

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    def test_run_scene_image_pipeline_preserves_newer_disk_state_for_other_segments(
        self,
        mock_generate_scene_images,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)
        segment_payload = read_json(story_result.segment_plan_path)
        selected_segment_id = str(segment_payload[0]["segment_id"])
        preserved_segment_id = str(segment_payload[1]["segment_id"])

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})

            scene_manifest_payload = read_json(story_result.scene_images_path)
            for item in scene_manifest_payload:
                if item["segment_id"] != preserved_segment_id:
                    continue
                item["status"] = "completed"
                item["start_frame_url"] = "https://disk.example/preserved_start.png"
                item["end_frame_url"] = "https://disk.example/preserved_end.png"
                break
            story_result.scene_images_path.write_text(
                json.dumps(scene_manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            manifest_payload = read_json(story_result.seedance_manifest_path)
            for clip in manifest_payload["clips"]:
                if clip["segment_id"] != preserved_segment_id:
                    continue
                clip["start_frame_url"] = "https://disk.example/preserved_start.png"
                clip["end_frame_url"] = "https://disk.example/preserved_end.png"
                break
            story_result.seedance_manifest_path.write_text(
                json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            mark_runtime_scene_images_completed(
                project_package,
                segment_ids={selected_segment_id},
                base_url="https://runtime.example",
            )
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=2,
                failed_count=0,
                note="ok",
            )

        mock_generate_scene_images.side_effect = fake_generate_scene_images

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_scenes=True,
            segment_id=selected_segment_id,
        )

        persisted_scene_manifest = read_json(scene_result.scene_images_path)
        preserved_task = next(
            item for item in persisted_scene_manifest if item["segment_id"] == preserved_segment_id
        )
        self.assertEqual(preserved_task["status"], "completed")
        self.assertEqual(
            preserved_task["start_frame_url"],
            "https://disk.example/preserved_start.png",
        )
        self.assertEqual(
            preserved_task["end_frame_url"],
            "https://disk.example/preserved_end.png",
        )

        persisted_seedance_manifest = read_json(scene_result.manifest_path)
        preserved_clip = next(
            item for item in persisted_seedance_manifest["clips"] if item["segment_id"] == preserved_segment_id
        )
        self.assertEqual(
            preserved_clip["start_frame_url"],
            "https://disk.example/preserved_start.png",
        )
        self.assertEqual(
            preserved_clip["end_frame_url"],
            "https://disk.example/preserved_end.png",
        )

    def test_write_continuity_report_flags_failed_scene_and_video_tasks(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        first_scene_id, first_segment_id = mark_first_scene_and_video_failed(story_result)

        report_path, report = write_continuity_report(story_result.output_dir)

        self.assertEqual(report_path.name, "continuity_report.json")
        self.assertEqual(report.status, "critical")
        scene_codes = {item.code for item in report.scene_issues if item.scene_id == first_scene_id}
        segment_codes = {
            item.code
            for item in report.segment_issues
            if item.segment_id == first_segment_id
        }
        self.assertIn("scene_master_frame_failed", scene_codes)
        self.assertIn("scene_generation_failed", segment_codes)
        self.assertIn("video_generation_failed", segment_codes)
        self.assertTrue(
            any(item.action == "regenerate_scene_master_frame" for item in report.recommended_actions)
        )
        self.assertTrue(
            any(item.action == "regenerate_video" for item in report.recommended_actions)
        )

    def test_write_continuity_report_flags_weak_scene_baseline(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        scene_plan_payload = read_json(story_result.scene_plan_path)
        target_scene = scene_plan_payload["scenes"][0]
        target_scene["scene_bible"]["background_anchors"] = ["站台"]
        target_scene["scene_bible"]["fixed_props"] = []
        target_scene["scene_bible"]["dominant_palette"] = []
        target_scene["scene_master_frame_prompt"] = "站台傍晚"
        story_result.scene_plan_path.write_text(
            json.dumps(scene_plan_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _, report = write_continuity_report(story_result.output_dir)

        scene_codes = {item.code for item in report.scene_issues if item.scene_id == target_scene["scene_id"]}
        self.assertIn("scene_baseline_weak", scene_codes)
        weak_issue = next(
            item
            for item in report.scene_issues
            if item.scene_id == target_scene["scene_id"] and item.code == "scene_baseline_weak"
        )
        self.assertEqual(weak_issue.recommended_action, "regenerate_scene_master_frame")
        self.assertIn("背景锚点不足", weak_issue.message)

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_master_frames")
    def test_run_scene_image_pipeline_only_updates_selected_scene_master_frame(
        self,
        mock_generate_scene_master_frames,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        scene_plan = read_json(story_result.scene_plan_path)
        selected_scene_id = scene_plan["scenes"][0]["scene_id"]

        def fake_generate_scene_master_frames(
            project_package,
            force_submit=False,
            scene_ids=None,
            force_regenerate=False,
        ):
            self.assertTrue(force_submit)
            self.assertEqual(scene_ids, {selected_scene_id})
            self.assertTrue(force_regenerate)
            mark_runtime_scene_master_frames_completed(
                project_package,
                scene_ids={selected_scene_id},
            )
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=1,
                failed_count=0,
                note="ok",
            )

        mock_generate_scene_master_frames.side_effect = fake_generate_scene_master_frames

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_scenes=True,
            scene_id=selected_scene_id,
            master_only=True,
        )

        persisted_scene_plan = read_json(scene_result.scene_plan_path)
        selected_scene = next(
            item for item in persisted_scene_plan["scenes"] if item["scene_id"] == selected_scene_id
        )
        self.assertTrue(selected_scene["scene_master_frame_url"])
        self.assertEqual(selected_scene["scene_master_frame_status"], "completed")

        persisted_scene_manifest = read_json(scene_result.scene_images_path)
        selected_scene_tasks = [
            item for item in persisted_scene_manifest if item["scene_id"] == selected_scene_id
        ]
        self.assertTrue(selected_scene_tasks)
        self.assertTrue(all(item["scene_master_frame_url"] for item in selected_scene_tasks))

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    def test_run_scene_image_pipeline_only_updates_selected_scene_segments(
        self,
        mock_generate_scene_images,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        scene_plan = read_json(story_result.scene_plan_path)
        selected_scene_id = scene_plan["scenes"][0]["scene_id"]
        selected_segment_ids = {
            item["segment_id"]
            for item in scene_plan["scenes"][0]["segments"]
        }

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, selected_segment_ids)
            mark_runtime_scene_images_completed(
                project_package,
                segment_ids=selected_segment_ids,
            )
            return SeedreamExecutionReport(
                submitted=True,
                generated_count=2,
                failed_count=0,
                note="ok",
            )

        mock_generate_scene_images.side_effect = fake_generate_scene_images

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_scenes=True,
            scene_id=selected_scene_id,
        )

        scene_manifest = read_json(scene_result.scene_images_path)
        selected_tasks = [
            item for item in scene_manifest if item["scene_id"] == selected_scene_id
        ]
        untouched_tasks = [
            item for item in scene_manifest if item["scene_id"] != selected_scene_id
        ]
        self.assertTrue(selected_tasks)
        self.assertTrue(all(item["start_frame_url"] for item in selected_tasks))
        self.assertTrue(all(not item.get("start_frame_url") for item in untouched_tasks))

    def test_reset_scene_execution_contracts_for_repair_resets_only_selected_scene_segments(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)
        scene_plan = read_json(story_result.scene_plan_path)
        selected_scene_id = scene_plan["scenes"][0]["scene_id"]
        selected_scene_segment_ids = [
            item["segment_id"]
            for item in scene_plan["scenes"][0]["segments"]
        ]
        selected_segment_id = str(selected_scene_segment_ids[0])

        mark_scene_images_completed(story_result)
        mark_seedance_clips_completed(story_result)

        selected_segment_ids = reset_scene_execution_contracts_for_repair(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            scene_id=selected_scene_id,
            segment_ids={selected_segment_id},
        )

        scene_manifest = read_json(story_result.scene_images_path)
        selected_tasks = [
            item for item in scene_manifest if item["segment_id"] in selected_segment_ids
        ]
        untouched_tasks = [
            item for item in scene_manifest if item["segment_id"] not in selected_segment_ids
        ]
        self.assertTrue(selected_tasks)
        self.assertTrue(all(item["status"] == "planned" for item in selected_tasks))
        self.assertTrue(all(not item["start_frame_url"] for item in selected_tasks))
        self.assertTrue(
            all(item["scene_id"] == selected_scene_id for item in selected_tasks)
        )
        self.assertTrue(all(item["status"] == "completed" for item in untouched_tasks))
        self.assertTrue(all(item["start_frame_url"] for item in untouched_tasks))

        manifest_payload = read_json(story_result.seedance_manifest_path)
        selected_clips = [
            item for item in manifest_payload["clips"] if item["segment_id"] in selected_segment_ids
        ]
        untouched_clips = [
            item for item in manifest_payload["clips"] if item["segment_id"] not in selected_segment_ids
        ]
        self.assertTrue(selected_clips)
        self.assertTrue(all(item["submit_status"] == "planned" for item in selected_clips))
        self.assertTrue(all(not item["downloaded_path"] for item in selected_clips))
        self.assertTrue(all(item["submit_status"] == "completed" for item in untouched_clips))
        self.assertTrue(all(item["downloaded_path"] for item in untouched_clips))

    @patch("storyforge.pipelines.video_pipeline.concat_manifest_clips")
    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    def test_run_video_render_pipeline_only_selected_segment_skips_full_concat(
        self,
        mock_execute_manifest,
        mock_concat_manifest_clips,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        manifest_payload = read_json(story_result.seedance_manifest_path)
        selected_segment_id = manifest_payload["clips"][0]["segment_id"]
        selected_output_path = Path(manifest_payload["clips"][0]["output_path"])
        manifest_payload["clips"][0]["start_frame_url"] = "https://example.com/start.png"
        manifest_payload["clips"][0]["end_frame_url"] = "https://example.com/end.png"
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})
            mark_runtime_manifest_clips_completed(
                manifest,
                segment_ids={selected_segment_id},
                remote_status="succeeded",
                write_bytes=b"selected clip",
            )
            return SeedanceExecutionReport(
                submitted=True,
                manifest_title=manifest.title,
                completed_count=1,
                failed_count=0,
                pending_count=0,
                note="ok",
            )

        mock_execute_manifest.side_effect = fake_execute_manifest

        video_result = run_video_render_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
            segment_id=selected_segment_id,
        )

        self.assertEqual(video_result.rendered_clip_paths, [selected_output_path])
        self.assertIsNone(video_result.full_story_path)
        mock_concat_manifest_clips.assert_not_called()

    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    def test_run_video_render_pipeline_only_selected_scene_segments(self, mock_execute_manifest) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        scene_plan = read_json(story_result.scene_plan_path)
        selected_scene_id = scene_plan["scenes"][0]["scene_id"]
        selected_segment_ids = {
            item["segment_id"]
            for item in scene_plan["scenes"][0]["segments"]
        }
        manifest_payload = read_json(story_result.seedance_manifest_path)
        selected_output_paths = {
            str(item["segment_id"]): Path(item["output_path"])
            for item in manifest_payload["clips"]
            if item["segment_id"] in selected_segment_ids
        }
        for clip in manifest_payload["clips"]:
            if clip["segment_id"] not in selected_segment_ids:
                continue
            clip["start_frame_url"] = f"https://example.com/{clip['segment_id']}_start.png"
            clip["end_frame_url"] = f"https://example.com/{clip['segment_id']}_end.png"
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, selected_segment_ids)
            mark_runtime_manifest_clips_completed(
                manifest,
                segment_ids=selected_segment_ids,
                remote_status="succeeded",
                write_bytes=b"scene clip",
            )
            return SeedanceExecutionReport(
                submitted=True,
                manifest_title=manifest.title,
                completed_count=len(selected_segment_ids),
                failed_count=0,
                pending_count=0,
                note="ok",
            )

        mock_execute_manifest.side_effect = fake_execute_manifest

        video_result = run_video_render_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
            scene_id=selected_scene_id,
        )

        self.assertEqual(
            {str(path) for path in video_result.rendered_clip_paths},
            {str(path) for path in selected_output_paths.values()},
        )

    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    def test_run_video_render_pipeline_preserves_newer_disk_frame_urls_for_other_segments(
        self,
        mock_execute_manifest,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        ensure_secondary_segment_execution_contract(story_result)
        manifest_payload = read_json(story_result.seedance_manifest_path)
        selected_segment_id = str(manifest_payload["clips"][0]["segment_id"])
        preserved_segment_id = str(manifest_payload["clips"][1]["segment_id"])

        for clip in manifest_payload["clips"]:
            if clip["segment_id"] != selected_segment_id:
                continue
            clip["start_frame_url"] = "https://runtime.example/selected_start.png"
            clip["end_frame_url"] = "https://runtime.example/selected_end.png"
            break
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})

            latest_manifest_payload = read_json(story_result.seedance_manifest_path)
            for clip in latest_manifest_payload["clips"]:
                if clip["segment_id"] != preserved_segment_id:
                    continue
                clip["start_frame_url"] = "https://disk.example/preserved_start.png"
                clip["end_frame_url"] = "https://disk.example/preserved_end.png"
                break
            story_result.seedance_manifest_path.write_text(
                json.dumps(latest_manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            mark_runtime_manifest_clips_completed(
                manifest,
                segment_ids={selected_segment_id},
                remote_status="succeeded",
                write_bytes=b"selected clip",
            )
            return SeedanceExecutionReport(
                submitted=True,
                manifest_title=manifest.title,
                completed_count=1,
                failed_count=0,
                pending_count=0,
                note="ok",
            )

        mock_execute_manifest.side_effect = fake_execute_manifest

        video_result = run_video_render_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
            segment_id=selected_segment_id,
        )

        persisted_manifest = read_json(video_result.manifest_path)
        selected_clip = next(
            item for item in persisted_manifest["clips"] if item["segment_id"] == selected_segment_id
        )
        preserved_clip = next(
            item for item in persisted_manifest["clips"] if item["segment_id"] == preserved_segment_id
        )
        self.assertEqual(selected_clip["submit_status"], "completed")
        self.assertEqual(selected_clip["remote_status"], "succeeded")
        self.assertTrue(selected_clip["downloaded_path"])
        self.assertEqual(
            preserved_clip["start_frame_url"],
            "https://disk.example/preserved_start.png",
        )
        self.assertEqual(
            preserved_clip["end_frame_url"],
            "https://disk.example/preserved_end.png",
        )

    def test_generic_character_aliases_are_normalized_to_real_names(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        self.assertIn(expected_name, segment.start_frame_prompt)

    def test_character_profile_requires_structured_voice_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "voice_profile"):
            CharacterProfile.from_dict(
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

    def test_resume_from_progress_rejects_legacy_checkpoint_without_chunks(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="旧进度拒绝恢复",
            idea="毕业前夕，两个人在校园里逐步靠近彼此。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "legacy-progress-source",
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=self.video_backend,
        )

        progress_payload = {
            "schema_version": 2,
            "status": "failed",
            "story_title": scene_structure.novel_package.outline.title,
            "story_source_revision": scene_structure.scene_structure.story_memory.story_identity.story_source_revision,
            "total_chapters": 1,
            "total_scenes": len(scene_structure.scene_structure.scene_plan.scenes),
            "total_chunks": 0,
            "completed_chapters": 0,
            "completed_scene_count": 0,
            "completed_chunk_count": 0,
            "completed_segment_count": 0,
            "failed_chapter_number": 1,
            "failed_scene_id": scene_structure.scene_structure.scene_plan.scenes[0].scene_id,
            "failed_chunk_id": "",
            "resume_ready": True,
            "chapters": [
                {
                    "chapter_number": 1,
                    "chapter_title": scene_structure.novel_package.outline.chapters[0].title,
                    "status": "failed",
                    "scene_count": len(scene_structure.scene_structure.scene_plan.scenes),
                    "completed_scene_count": 0,
                    "segment_count": 0,
                    "failed_scene_id": scene_structure.scene_structure.scene_plan.scenes[0].scene_id,
                    "error": "legacy checkpoint",
                    "scenes": [
                        {
                            "scene_id": scene.scene_id,
                            "scene_title": scene.title,
                            "chapter_number": scene.chapter_number,
                            "status": "failed" if index == 0 else "pending",
                            "chunk_count": 0,
                            "completed_chunk_count": 0,
                            "segment_count": 0,
                            "failed_chunk_id": "",
                            "error": "legacy checkpoint" if index == 0 else "",
                            "chunks": [],
                        }
                        for index, scene in enumerate(scene_structure.scene_structure.scene_plan.scenes)
                    ],
                }
            ],
        }
        progress_path = generation.output_dir / "segment_contract_progress.json"
        progress_path.write_text(
            json.dumps(progress_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "无法继续恢复"):
            run_story_segment_contracts_pipeline(
                novel_package=scene_structure.novel_package,
                config=config,
                project_root=ROOT,
                output_root=generation.output_dir,
                backend=self.video_backend,
                scene_structure_artifacts=scene_structure.scene_structure,
                resume_from_progress=True,
            )

    def test_visual_bible_names_are_repaired_to_outline_characters(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        story_result = self._run_story_pipeline(
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
        first_character, second_character = self._ensure_two_outline_characters(story_result)
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

    def test_frame_character_lists_are_inferred_and_preserved_separately(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        first_character, second_character = self._ensure_two_outline_characters(story_result)
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
                        "segment_id": "confession-02",
                        "chapter_number": 1,
                        "title": "紫藤花廊的等待",
                        "summary": "陈默独自等待，林晚稍后才出现。",
                        "involved_characters": [first_character.name, second_character.name],
                        "narration": "他站在花廊里等她，直到她终于走近。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["他站在花廊里等她，直到她终于走近。"],
                        "sound_effects": ["风声"],
                        "music_direction": "青春克制",
                        "timed_beats": ["0-3秒：陈默独自等待。", "3-5秒：林晚走近。"],
                        "start_frame_prompt": f"{first_character.name}独自站在花廊入口处等待。",
                        "mid_frame_prompt": f"{first_character.name}看见{second_character.name}从花园小径走来。",
                        "end_frame_prompt": f"{first_character.name}仍独自望向小径方向。",
                        "duration_seconds": 5,
                        "requires_mid_frame": True,
                        "start_frame_characters": [first_character.name],
                        "mid_frame_characters": [first_character.name, second_character.name],
                        "end_frame_characters": [first_character.name],
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
        self.assertEqual(segment.start_frame_characters, [first_character.name])
        self.assertEqual(
            segment.mid_frame_characters,
            [first_character.name, second_character.name],
        )
        self.assertEqual(segment.end_frame_characters, [first_character.name])

    def test_mid_frame_characters_follow_mid_timed_beat_not_full_segment_cast(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        first_character, second_character = self._ensure_two_outline_characters(story_result)
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
                        "segment_id": "confession-waiting",
                        "chapter_number": 1,
                        "title": "花廊等待",
                        "summary": f"{first_character.name}在花廊等待{second_character.name}。",
                        "involved_characters": [first_character.name, second_character.name],
                        "narration": "他站在花廊下等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["他站在花廊下等待。"],
                        "sound_effects": ["风声"],
                        "music_direction": "青春克制",
                        "timed_beats": [
                            "0-4秒：镜头从紫藤花架全景缓缓推进，旁白开始",
                            f"4-9秒：镜头聚焦{first_character.name}背影，他站在花架下等待",
                        ],
                        "start_frame_prompt": f"{first_character.name}独自站在紫藤花架下等待。",
                        "mid_frame_prompt": (
                            f"中段锚点帧，角色：{first_character.name}、{second_character.name}，"
                            f"镜头推进到片段中段，重点呈现 {first_character.name}等待{second_character.name}。"
                        ),
                        "end_frame_prompt": f"{first_character.name}听到声音后转身。",
                        "duration_seconds": 9,
                        "start_frame_characters": [first_character.name],
                        "mid_frame_characters": [first_character.name, second_character.name],
                        "end_frame_characters": [first_character.name],
                        "requires_mid_frame": True,
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
        self.assertEqual(segment.mid_frame_characters, [first_character.name])

    def test_default_mid_frame_prompt_does_not_reinject_full_segment_context(self) -> None:
        service = NovelToVideoService()
        segment = VideoSegment.from_dict(
            {
                "segment_id": "confession-mid",
                "chapter_number": 1,
                "scene_id": "ch01-sc01",
                "scene_title": "紫藤花架",
                "scene_summary": "等待与转身",
                "scene_anchor": "紫藤花架 / 傍晚",
                "title": "等待",
                "summary": "陈默在花架下等待。",
                "involved_characters": ["陈默", "林晓"],
                "narration": "陈默站在原地。",
                "dialogue_lines": [],
                "subtitle_lines": [],
                "sound_effects": [],
                "music_direction": "",
                "timed_beats": ["0-4秒：陈默独自等待。", "4-8秒：他听见脚步声后抬头。"],
                "start_frame_prompt": "陈默独自等待。",
                "mid_frame_prompt": "",
                "end_frame_prompt": "陈默抬头。",
                "duration_seconds": 8,
                "start_frame_characters": ["陈默"],
                "mid_frame_characters": ["陈默"],
                "end_frame_characters": ["陈默"],
                "requires_mid_frame": True,
            }
        )

        prompt = service._build_default_mid_frame_prompt(segment)

        self.assertIn("中段锚点帧", prompt)
        self.assertIn("陈默", prompt)
        self.assertNotIn("场景主提示", prompt)
        self.assertNotIn("浅蓝连衣裙", prompt)
        self.assertNotIn("林晓", prompt)

    def test_default_mid_frame_prompt_prefers_middle_beat_over_future_segment_summary(self) -> None:
        service = NovelToVideoService()
        segment = VideoSegment.from_dict(
            {
                "segment_id": "confession-mid-beat",
                "chapter_number": 1,
                "scene_id": "ch01-sc01",
                "scene_title": "镜湖长椅",
                "scene_summary": "等待、停顿与靠近。",
                "scene_anchor": "镜湖边长椅 / 傍晚 / 微风",
                "title": "停顿时刻",
                "summary": "陈默等到林晓后终于靠近并亲吻。",
                "involved_characters": ["陈默", "林晓"],
                "narration": "",
                "dialogue_lines": [],
                "subtitle_lines": [],
                "sound_effects": [],
                "music_direction": "",
                "timed_beats": [
                    "0-4秒：陈默独自站在长椅旁等待。",
                    "4-8秒：林晓停在长椅另一侧，抬眼看向陈默。",
                    "8-12秒：两人靠近后拥抱。",
                ],
                "start_frame_prompt": "陈默独自站在长椅旁等待。",
                "mid_frame_prompt": "",
                "end_frame_prompt": "两人靠近后拥抱。",
                "duration_seconds": 12,
                "start_frame_characters": ["陈默"],
                "mid_frame_characters": ["陈默", "林晓"],
                "end_frame_characters": ["陈默", "林晓"],
                "requires_mid_frame": True,
            }
        )

        prompt = service._build_default_mid_frame_prompt(segment)

        self.assertIn("林晓停在长椅另一侧", prompt)
        self.assertNotIn("终于靠近并亲吻", prompt)
        self.assertNotIn("拥抱", prompt)

    def test_chapter_scene_structure_output_rejects_missing_tail_event_coverage(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="镜湖告白",
            idea="大学校园里的双人告白故事",
            genre="校园告白",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        generation = self._run_story_generation_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "scene-coverage-validation",
        )
        scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=generation.output_dir,
            backend=self.story_backend,
            video_backend=self.video_backend,
        )
        service = NovelToVideoService()
        chapter_event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": "林栀主动找到周骁。",
                        "source_evidence": ["主动找到"],
                        "involved_characters": ["林栀", "周骁"],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": "林栀终于说出口。",
                        "source_evidence": ["说出口"],
                        "involved_characters": ["林栀", "周骁"],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": "周骁给出关键回应。",
                        "source_evidence": ["关键回应"],
                        "involved_characters": ["林栀", "周骁"],
                    },
                    {
                        "event_id": "ch01-ev04",
                        "summary": "两人的情绪和关系发生明确变化。",
                        "source_evidence": ["明确变化"],
                        "involved_characters": ["林栀", "周骁"],
                    },
                ],
            }
        )
        structure = ChapterSceneStructureSchema.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "title": "相遇与表白",
                        "summary": "林栀找到周骁后把话说出口，周骁给出回应。",
                        "scene_anchor": "统一测试场景",
                        "involved_characters": ["林栀", "周骁"],
                        "covered_event_ids": ["ch01-ev01", "ch01-ev02", "ch01-ev03"],
                        "scene_bible": {
                            "location": "统一测试场景",
                            "time_window": "傍晚",
                            "weather": "微风",
                            "lighting": "柔和侧光",
                            "background_anchors": ["固定背景锚点"],
                            "spatial_layout": "两人面对面站定",
                        },
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "关键事件覆盖不完整"):
            service._validate_chapter_scene_structure_output(
                structure,
                novel_package=scene_structure.novel_package,
                chapter_number=1,
                chapter_event_plan=chapter_event_plan,
            )

    def test_scene_segment_contract_output_requires_explicit_frame_characters(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖边等待",
                "summary": "主角在镜湖边等待。",
                "scene_anchor": "镜湖边长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖",
                    "character_blocking": "单人等待",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": [],
                        "mid_frame_characters": [],
                        "end_frame_characters": [],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "start_frame_characters 不能为空"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_chapter_scene_structure_output_requires_transition_contract_for_nonfirst_scene(self) -> None:
        service = NovelToVideoService()
        chapter_event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": "陈默在花廊下等到林晚。",
                        "source_evidence": ["花廊", "等到"],
                        "involved_characters": ["陈默", "林晚"],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": "两人离开花廊走向镜湖。",
                        "source_evidence": ["离开花廊", "镜湖"],
                        "involved_characters": ["陈默", "林晚"],
                    },
                ],
            }
        )
        structure = ChapterSceneStructureSchema.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "title": "花廊相遇",
                        "summary": "陈默终于在花廊下等到林晚。",
                        "scene_anchor": "花廊 / 傍晚 / 微风",
                        "involved_characters": ["陈默", "林晚"],
                        "covered_event_ids": ["ch01-ev01"],
                        "scene_bible": {
                            "location": "校园花廊",
                            "time_window": "傍晚",
                            "weather": "微风",
                            "lighting": "暖色侧光",
                            "background_anchors": ["花廊"],
                            "fixed_props": ["长椅"],
                            "spatial_layout": "花廊通向湖边步道",
                            "character_blocking": "两人在花廊入口会面",
                            "continuity_notes": "保持花廊与湖边方向关系稳定",
                        },
                    },
                    {
                        "scene_id": "ch01-sc02",
                        "chapter_number": 1,
                        "title": "走向镜湖",
                        "summary": "两人离开花廊后继续走向镜湖步道。",
                        "scene_anchor": "镜湖步道 / 傍晚 / 微风",
                        "involved_characters": ["陈默", "林晚"],
                        "covered_event_ids": ["ch01-ev02"],
                        "scene_bible": {
                            "location": "镜湖步道",
                            "time_window": "傍晚",
                            "weather": "微风",
                            "lighting": "湖边暖色侧光",
                            "background_anchors": ["镜湖", "步道"],
                            "fixed_props": ["栏杆"],
                            "spatial_layout": "步道沿湖延伸",
                            "character_blocking": "两人沿步道继续前行",
                            "continuity_notes": "保持花廊出口到镜湖步道的方向一致",
                        },
                    },
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "scene_transition_contract"):
            service._validate_chapter_scene_structure_output(
                structure,
                novel_package=None,
                chapter_number=1,
                chapter_event_plan=chapter_event_plan,
            )

    def test_chapter_scene_transition_entry_is_backfilled_to_current_scene_opening(self) -> None:
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "镜湖步道",
                "summary": "两人从花廊出口走入镜湖步道。",
                "scene_anchor": "镜湖步道 / 傍晚 / 微风",
                "involved_characters": ["陈默", "林晚"],
                "covered_event_ids": ["ch01-ev02"],
                "scene_transition_contract": {
                    "previous_scene_id": "ch01-sc01",
                    "transition_mode": "adjacent_move",
                    "previous_scene_exit_state": "两人刚从花廊下并肩迈步离开。",
                    "next_scene_entry_match": "承接上一场的沉默。",
                    "bridge_action": "沿花廊出口继续前行，顺势 reveal 镜湖步道。",
                    "carry_over_elements": ["并肩关系", "向右前方行进"],
                    "screen_direction_policy": "保持向右前方行进。",
                    "visual_bridge": "先跟脚步，再露出镜湖步道与栏杆。",
                    "transition_focus_seconds": 2,
                },
                "scene_bible": {
                    "location": "镜湖步道",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "湖边暖色侧光",
                    "background_anchors": ["镜湖", "步道"],
                    "fixed_props": ["栏杆"],
                    "spatial_layout": "步道沿湖延伸",
                    "character_blocking": "两人并肩进入镜湖步道",
                    "continuity_notes": "先承接花廊离场，再稳定到镜湖空间",
                },
            }
        )

        entry_match = scene.scene_transition_contract.next_scene_entry_match

        self.assertIn("镜湖步道", entry_match)
        self.assertIn("两人并肩进入镜湖步道", entry_match)
        self.assertIn("承接上一场的沉默", entry_match)

    def test_chapter_scene_structure_accepts_filmable_transition_entry_with_current_anchor(self) -> None:
        service = NovelToVideoService()
        chapter_event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": "陈默在花廊下等到林晚。",
                        "source_evidence": ["花廊", "等到"],
                        "involved_characters": ["陈默", "林晚"],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": "两人离开花廊走向镜湖。",
                        "source_evidence": ["离开花廊", "镜湖"],
                        "involved_characters": ["陈默", "林晚"],
                    },
                ],
            }
        )
        structure = ChapterSceneStructureSchema.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "title": "花廊相遇",
                        "summary": "陈默终于在花廊下等到林晚。",
                        "scene_anchor": "花廊 / 傍晚 / 微风",
                        "involved_characters": ["陈默", "林晚"],
                        "covered_event_ids": ["ch01-ev01"],
                        "scene_bible": {
                            "location": "校园花廊",
                            "background_anchors": ["花廊"],
                            "spatial_layout": "花廊通向湖边步道",
                            "character_blocking": "两人在花廊入口会面",
                        },
                    },
                    {
                        "scene_id": "ch01-sc02",
                        "chapter_number": 1,
                        "title": "走向镜湖",
                        "summary": "两人离开花廊后继续走向镜湖步道。",
                        "scene_anchor": "镜湖步道 / 傍晚 / 微风",
                        "involved_characters": ["陈默", "林晚"],
                        "covered_event_ids": ["ch01-ev02"],
                        "scene_transition_contract": {
                            "previous_scene_id": "ch01-sc01",
                            "transition_mode": "adjacent_move",
                            "previous_scene_exit_state": "两人在花廊入口并肩迈步离开。",
                            "next_scene_entry_match": "当前场开头先看到镜湖步道，陈默和林晚并肩从画面左侧进入，栏杆和湖面在右侧出现。",
                            "bridge_action": "两人沿花廊出口继续前行，顺势进入镜湖步道。",
                            "carry_over_elements": ["并肩关系", "向右前方行进"],
                            "screen_direction_policy": "保持向右前方行进。",
                            "visual_bridge": "先跟脚步，再露出镜湖步道与栏杆。",
                            "transition_focus_seconds": 2,
                        },
                        "scene_bible": {
                            "location": "镜湖步道",
                            "background_anchors": ["镜湖", "步道", "栏杆"],
                            "spatial_layout": "步道沿湖延伸",
                            "character_blocking": "两人并肩进入镜湖步道",
                        },
                    },
                ]
            }
        )

        validated = service._validate_chapter_scene_structure_output(
            structure,
            novel_package=None,
            chapter_number=1,
            chapter_event_plan=chapter_event_plan,
        )

        self.assertEqual(len(validated.scenes), 2)

    def test_scene_chunk_output_requires_consuming_scene_transition_contract(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "镜湖步道",
                "summary": "两人从花廊出口走入镜湖步道。",
                "scene_anchor": "镜湖步道 / 傍晚 / 微风",
                "involved_characters": ["陈默", "林晚"],
                "scene_transition_contract": {
                    "previous_scene_id": "ch01-sc01",
                    "transition_mode": "adjacent_move",
                    "previous_scene_exit_state": "两人刚从花廊下并肩迈步离开。",
                    "next_scene_entry_match": "开头先承接两人并肩前行，再带出镜湖步道。",
                    "bridge_action": "沿花廊出口继续前行，顺势 reveal 镜湖步道。",
                    "carry_over_elements": ["并肩关系", "向右前方行进"],
                    "screen_direction_policy": "保持向右前方行进。",
                    "visual_bridge": "先跟脚步，再露出镜湖步道与栏杆。",
                    "transition_focus_seconds": 2,
                },
                "scene_bible": {
                    "location": "镜湖步道",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "background_anchors": ["镜湖", "步道"],
                    "fixed_props": ["栏杆"],
                    "spatial_layout": "步道沿湖延伸",
                    "character_blocking": "两人并肩进入镜湖步道",
                    "continuity_notes": "先承接花廊离场，再稳定到镜湖空间",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-01",
                        "order_index": 1,
                        "title": "直接告白",
                        "summary": "陈默在镜湖边直接说出喜欢，不再承接走路状态。",
                        "must_cover": ["陈默直接告白"],
                        "transition_goal": "林晚准备回应。",
                        "expected_segment_count": 1,
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "首个 chunk 没有消费 scene_transition_contract"):
            service._validate_scene_segment_chunk_output(chunk_plan, scene=scene)

    def test_scene_chunk_output_rejects_future_event_progress_outside_bound_events(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "递出纸条前",
                "summary": "林屿走向长椅，把纸条递到苏晚面前。",
                "scene_anchor": "樱花公园长椅区 / 午后",
                "involved_characters": ["林屿", "苏晚"],
                "covered_event_ids": ["ch01-ev01", "ch01-ev02"],
                "covered_event_summaries": [
                    "林屿从樱花树下起步走向长椅。",
                    "林屿把皱纸条递到苏晚面前，等待她接过。",
                ],
                "scene_bible": {
                    "location": "樱花公园长椅区",
                    "time_window": "午后",
                    "weather": "微风",
                    "lighting": "暖色斜射光",
                    "background_anchors": ["长椅", "樱花树"],
                    "fixed_props": ["纸条"],
                    "spatial_layout": "步道通向长椅",
                    "character_blocking": "林屿走近后停在长椅旁",
                    "continuity_notes": "当前 scene 只到递纸条，不进入回应结果",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-01",
                        "order_index": 1,
                        "title": "读完后亲吻",
                        "summary": "苏晚看完纸条后踮脚亲吻林屿，关系立即落定。",
                        "must_cover": ["苏晚读完纸条", "苏晚踮脚亲吻林屿"],
                        "transition_goal": "两人通过亲吻完成回应",
                        "expected_segment_count": 1,
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "提前引入了未绑定事件推进"):
            service._validate_scene_segment_chunk_output(chunk_plan, scene=scene)

    def test_scene_chunk_output_allows_first_chunk_to_reference_previous_scene_event_via_transition_contract(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc05",
                "chapter_number": 1,
                "title": "回应与亲吻",
                "summary": "苏晚回应说等这句话等了快一年；林屿问可不可以亲她，苏晚主动踮脚吻上林屿。",
                "scene_anchor": "樱花树王下，回应与亲吻",
                "involved_characters": ["林屿", "苏晚"],
                "covered_event_ids": ["ch01-ev09", "ch01-ev10"],
                "covered_event_summaries": [
                    "苏晚回应说等这句话等了快一年，暗示她也一直喜欢林屿。",
                    "林屿问可不可以亲苏晚，苏晚主动踮脚亲吻林屿。",
                ],
                "scene_transition_contract": {
                    "previous_scene_id": "ch01-sc04",
                    "transition_mode": "direct_continue",
                    "previous_scene_exit_state": "林屿说完告白，世界安静，风停花落。",
                    "next_scene_entry_match": "苏晚低下头，耳根红了。",
                    "bridge_action": "林屿告白后的沉默中，苏晚低头回应。",
                    "carry_over_elements": ["林屿", "苏晚", "樱花树王", "夕阳光线"],
                    "screen_direction_policy": "两人从面对面逐渐靠近。",
                    "visual_bridge": "苏晚低头又抬头的表情变化，然后往前走一步。",
                    "audio_bridge": "none",
                    "transition_focus_seconds": 1,
                },
                "scene_bible": {
                    "location": "樱花公园樱花树王下",
                    "time_window": "四月初傍晚，告白后",
                    "weather": "风停了，花瓣慢落",
                    "lighting": "夕阳逆光，光线温暖",
                    "background_anchors": ["樱花树王", "石板路"],
                    "fixed_props": ["草地"],
                    "spatial_layout": "两人面对面站立，距离逐渐缩短至零",
                    "character_blocking": "苏晚低头耳根红，然后抬头；林屿问可不可以亲；苏晚往前走一步踮脚吻上林屿",
                    "continuity_notes": "当前 scene 承接上一场告白后的静默。",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "chunks": [
                    {
                        "chunk_id": "ch01-sc05-chunk01",
                        "order_index": 1,
                        "title": "听完告白后的回应",
                        "summary": "苏晚在听完告白后的沉默里低头红了耳根，然后抬头回应。",
                        "must_cover": ["听完告白后的沉默", "苏晚低头红了耳根", "苏晚抬头回应"],
                        "transition_goal": "苏晚的回应完整说出口。",
                        "expected_segment_count": 2,
                    },
                    {
                        "chunk_id": "ch01-sc05-chunk02",
                        "order_index": 2,
                        "title": "询问与亲吻",
                        "summary": "林屿问可不可以亲她，苏晚主动往前一步吻上去。",
                        "must_cover": ["林屿轻声询问", "苏晚主动踮脚亲吻"],
                        "transition_goal": "亲吻落地后，当前 scene 收束。",
                        "expected_segment_count": 2,
                    }
                ]
            }
        )

        validated = service._validate_scene_segment_chunk_output(chunk_plan, scene=scene)

        self.assertEqual(validated.chunks[0].chunk_id, "ch01-sc05-chunk01")
        self.assertEqual(validated.chunks[1].chunk_id, "ch01-sc05-chunk02")

    def test_scene_chunk_output_allows_non_relational_response_inside_bound_chat_scene(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "湖边闲聊",
                "summary": "林序和苏晚并肩坐下，闲聊期中考试和食堂窗口。",
                "scene_anchor": "湖边长椅 / 傍晚 / 微风",
                "involved_characters": ["林序", "苏晚"],
                "covered_event_ids": ["ch01-ev03"],
                "covered_event_summaries": [
                    "苏晚在林序身边坐下，两人闲聊期中考试和食堂。"
                ],
                "scene_bible": {
                    "location": "湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "background_anchors": ["湖面", "长椅"],
                    "fixed_props": ["栏杆"],
                    "spatial_layout": "长椅朝向湖面，石板路从侧后方延伸",
                    "character_blocking": "两人并肩坐下，边看湖面边聊天",
                    "continuity_notes": "当前 scene 只覆盖轻松闲聊，不进入关系推进。",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "chunks": [
                    {
                        "chunk_id": "ch01-sc02-chunk01",
                        "order_index": 1,
                        "title": "坐下接上闲聊",
                        "summary": "苏晚在林序身边坐下，回应他刚才聊到的期中考试和食堂话题。",
                        "must_cover": [
                            "苏晚在林序身边坐下",
                            "苏晚回应林序刚才聊到的期中考试和食堂话题",
                        ],
                        "transition_goal": "两人的闲聊自然接上并稳定下来。",
                        "expected_segment_count": 1,
                    }
                ]
            }
        )

        validated = service._validate_scene_segment_chunk_output(chunk_plan, scene=scene)

        self.assertEqual(validated.chunks[0].chunk_id, "ch01-sc02-chunk01")

    def test_scene_chunk_contract_output_requires_scene_transition_entry(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "镜湖步道",
                "summary": "两人从花廊出口走入镜湖步道。",
                "scene_anchor": "镜湖步道 / 傍晚 / 微风",
                "involved_characters": ["陈默", "林晚"],
                "scene_transition_contract": {
                    "previous_scene_id": "ch01-sc01",
                    "transition_mode": "adjacent_move",
                    "previous_scene_exit_state": "两人刚从花廊下并肩迈步离开。",
                    "next_scene_entry_match": "开头先承接两人并肩前行，再带出镜湖步道。",
                    "bridge_action": "沿花廊出口继续前行，顺势 reveal 镜湖步道。",
                    "carry_over_elements": ["并肩关系", "向右前方行进"],
                    "screen_direction_policy": "保持向右前方行进。",
                    "visual_bridge": "先跟脚步，再露出镜湖步道与栏杆。",
                    "transition_focus_seconds": 2,
                },
                "scene_bible": {
                    "location": "镜湖步道",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "background_anchors": ["镜湖", "步道"],
                    "fixed_props": ["栏杆"],
                    "spatial_layout": "步道沿湖延伸",
                    "character_blocking": "两人并肩进入镜湖步道",
                    "continuity_notes": "先承接花廊离场，再稳定到镜湖空间",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "chunk-01",
                "order_index": 1,
                "title": "走入镜湖步道",
                "summary": "两人从花廊出口走入镜湖步道。",
                "must_cover": ["承接并肩前行", "带出镜湖步道"],
                "transition_goal": "两人在镜湖边慢下来。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "tmp-seg-01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc02",
                        "title": "镜湖边停下",
                        "summary": "两人已经站在镜湖边，准备开始说话。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "timed_beats": ["0-6秒：两人已经站在镜湖边停住，彼此对视。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定双人镜头",
                            "blocking": "两人在镜湖边面对面停住",
                            "action_progression": "从站定推进到准备开口",
                            "emotion_progression": "紧张停顿",
                            "screen_direction": "两人围绕当前对视轴线站定",
                            "end_state_lock": "两人仍站在镜湖边对视",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "开场就是两人已经站在镜湖边，面对面停住。",
                            "carry_over_elements": ["镜湖步道"],
                            "allowed_changes": "从停住推进到准备开口。",
                            "transition_reason": "新 scene 开场。",
                        },
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "首段 opening_match 没有承接 scene_transition_contract"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
                previous_tail_segment=None,
            )

    def test_scene_segment_contract_output_rejects_generic_opening_match(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖边等待",
                "summary": "主角在镜湖边等待。",
                "scene_anchor": "镜湖边长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖",
                    "character_blocking": "单人等待",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并保持站姿",
                            "end_state_lock": "陈默仍站在长椅旁等待",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "场景开始",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待状态。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "opening_match 过于空泛"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_scene_segment_contract_output_collects_warning_for_generic_opening_match_when_creative_strict_disabled(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖边等待",
                "summary": "主角在镜湖边等待。",
                "scene_anchor": "镜湖边长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖",
                    "character_blocking": "单人等待",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并保持站姿",
                            "end_state_lock": "陈默仍站在长椅旁等待",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "场景开始",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待状态。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )
        warnings: list[str] = []

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
            creative_strict=False,
            warning_sink=warnings,
        )

        self.assertEqual(validated.segments[0].segment_id, "ch01-sc01-seg01")
        self.assertTrue(any("opening_match 过于空泛" in item for item in warnings))

    def test_scene_chunk_contract_output_requires_last_segment_to_land_on_transition_goal(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园入口",
                "summary": "林辰在花园入口说出口，等待苏雨回应。",
                "scene_anchor": "花园入口 / 黄昏 / 微风",
                "involved_characters": ["林辰", "苏雨"],
                "covered_event_ids": ["ch01-ev01", "ch01-ev02"],
                "covered_event_summaries": [
                    "林辰把心意说出口。",
                    "苏雨回应后，两人进入正式对话。",
                ],
                "scene_bible": {
                    "location": "花园入口",
                    "time_window": "黄昏",
                    "weather": "微风",
                    "lighting": "暖色斜射光",
                    "background_anchors": ["入口拱门", "石板路"],
                    "fixed_props": ["花坛"],
                    "spatial_layout": "入口面对石板路，花坛在左侧",
                    "character_blocking": "林辰先说出口，苏雨站在对面听完",
                    "continuity_notes": "当前 scene 要真正落到苏雨回应。",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "chunk-01",
                "order_index": 1,
                "title": "说出口后停住",
                "summary": "林辰说出口后，气氛停在等待苏雨回应前。",
                "must_cover": ["林辰说出心意", "苏雨回应"],
                "transition_goal": "苏雨回应后，两人进入正式对话。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "tmp-seg-01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "说出口后停住",
                        "summary": "林辰说完后停住，苏雨还未回应。",
                        "involved_characters": ["林辰", "苏雨"],
                        "start_frame_characters": ["林辰", "苏雨"],
                        "end_frame_characters": ["林辰", "苏雨"],
                        "timed_beats": [
                            "0-3秒：林辰看着苏雨，把心意说出口。",
                            "3-6秒：苏雨沉默看着他，气氛停在她准备回应前的一刻。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定双人镜头，停在两人之间",
                            "blocking": "林辰说完后站定，苏雨站在对面沉默看着他",
                            "action_progression": "从说出口推进到等待回应前的停顿",
                            "emotion_progression": "紧张悬置",
                            "screen_direction": "两人围绕同一对视轴线站定",
                            "end_state_lock": "林辰停住呼吸，苏雨准备回应但还未开口",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "开场时林辰和苏雨已经面对面站在花园入口，林辰正看着她。",
                            "carry_over_elements": ["花园入口", "面对面站位"],
                            "allowed_changes": "从说出口推进到等待回应前的停顿。",
                            "transition_reason": "当前 chunk 起始。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "最后一个 segment 仍停在 transition_goal 发生前"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
                previous_tail_segment=None,
            )

    def test_scene_chunk_contract_output_collects_warning_for_unlanded_transition_goal_when_creative_strict_disabled(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园入口",
                "summary": "林辰在花园入口说出口，等待苏雨回应。",
                "scene_anchor": "花园入口 / 黄昏 / 微风",
                "involved_characters": ["林辰", "苏雨"],
                "covered_event_ids": ["ch01-ev01", "ch01-ev02"],
                "covered_event_summaries": [
                    "林辰把心意说出口。",
                    "苏雨回应后，两人进入正式对话。",
                ],
                "scene_bible": {
                    "location": "花园入口",
                    "time_window": "黄昏",
                    "weather": "微风",
                    "lighting": "暖色斜射光",
                    "background_anchors": ["入口拱门", "石板路"],
                    "fixed_props": ["花坛"],
                    "spatial_layout": "入口面对石板路，花坛在左侧",
                    "character_blocking": "林辰先说出口，苏雨站在对面听完",
                    "continuity_notes": "当前 scene 要真正落到苏雨回应。",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "chunk-01",
                "order_index": 1,
                "title": "说出口后停住",
                "summary": "林辰说出口后，气氛停在等待苏雨回应前。",
                "must_cover": ["林辰说出心意", "苏雨回应"],
                "transition_goal": "苏雨回应后，两人进入正式对话。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "tmp-seg-01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "说出口后停住",
                        "summary": "林辰说完后停住，苏雨还未回应。",
                        "involved_characters": ["林辰", "苏雨"],
                        "start_frame_characters": ["林辰", "苏雨"],
                        "end_frame_characters": ["林辰", "苏雨"],
                        "timed_beats": [
                            "0-3秒：林辰看着苏雨，把心意说出口。",
                            "3-6秒：苏雨沉默看着他，气氛停在她准备回应前的一刻。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定双人镜头，停在两人之间",
                            "blocking": "林辰说完后站定，苏雨站在对面沉默看着他",
                            "action_progression": "从说出口推进到等待回应前的停顿",
                            "emotion_progression": "紧张悬置",
                            "screen_direction": "两人围绕同一对视轴线站定",
                            "end_state_lock": "林辰停住呼吸，苏雨准备回应但还未开口",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "开场时林辰和苏雨已经面对面站在花园入口，林辰正看着她。",
                            "carry_over_elements": ["花园入口", "面对面站位"],
                            "allowed_changes": "从说出口推进到等待回应前的停顿。",
                            "transition_reason": "当前 chunk 起始。",
                        },
                    }
                ],
            }
        )
        warnings: list[str] = []

        validated = service._validate_scene_chunk_contract_output(
            contracts,
            scene=scene,
            chunk=chunk,
            previous_tail_segment=None,
            creative_strict=False,
            warning_sink=warnings,
        )

        self.assertEqual(validated.segments[0].segment_id, "tmp-seg-01")
        self.assertTrue(any("transition_goal" in item for item in warnings))

    def test_soft_accept_scene_chunk_contract_batch_records_planner_warning(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖边等待",
                "summary": "主角在镜湖边等待。",
                "scene_anchor": "镜湖边长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖",
                    "character_blocking": "单人等待",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "chunk-01",
                "order_index": 1,
                "title": "等待",
                "summary": "陈默在镜湖边等待。",
                "must_cover": ["陈默在镜湖边等待。"],
                "transition_goal": "等待状态建立。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并保持站姿",
                            "end_state_lock": "陈默仍站在长椅旁等待",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "场景开始",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待状态。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        softened = service._soft_accept_scene_chunk_contract_batch(
            contracts,
            scene=scene,
            chunk=chunk,
            previous_tail_segment=None,
            effective_expected_segment_count=1,
            failure=ValueError("segment ch01-sc01-seg01 的 continuity_link.opening_match 过于空泛，必须写出可拍到的开场状态。"),
        )

        self.assertIsNotNone(softened)
        story_memory = service._flush_planner_warnings_to_story_memory(StoryMemoryPackage())
        self.assertTrue(
            any("opening_match 过于空泛" in item for item in story_memory.generation_notes.planner_warnings)
        )

    def test_scene_chunk_contract_output_allows_atmospheric_closure_when_tail_matches_chunk_summary(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc04",
                "chapter_number": 1,
                "title": "告白",
                "summary": "告白后世界安静下来。",
                "scene_anchor": "樱花步道 / 黄昏 / 微风",
                "involved_characters": ["林屿", "苏晚"],
                "covered_event_ids": ["ch01-ev07"],
                "covered_event_summaries": ["林屿告白后，世界仿佛安静下来，时间凝在这一刻。"],
                "scene_bible": {
                    "location": "樱花步道",
                    "time_window": "黄昏",
                    "weather": "微风",
                    "lighting": "暖色夕阳",
                    "background_anchors": ["樱花树", "步道"],
                    "fixed_props": ["路灯"],
                    "spatial_layout": "步道沿樱花树向前延伸",
                    "character_blocking": "林屿刚告白完，苏晚静静看着他",
                    "continuity_notes": "这一拍重点是告白后的静谧余韵。",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc04-chunk2",
                "order_index": 2,
                "title": "告白后的世界安静",
                "summary": "告白后世界安静下来，风停了，远处广播声也远了，时间仿佛凝固在这一刻。",
                "must_cover": ["风停花落静止", "远处广播声远去", "林屿感知到告白后的寂静"],
                "transition_goal": "告白瞬间的静谧感落地，场景结束",
                "expected_segment_count": 2,
            }
        )
        previous_tail_segment = SceneSegmentContractBatchSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "ch01-sc04-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc04",
                        "title": "说出口",
                        "summary": "林屿把喜欢说出口。",
                        "involved_characters": ["林屿", "苏晚"],
                        "start_frame_characters": ["林屿", "苏晚"],
                        "end_frame_characters": ["林屿", "苏晚"],
                        "timed_beats": [
                            "0-6秒：林屿看着苏晚，把藏了很久的话说出口。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定双人镜头",
                            "blocking": "林屿面对苏晚站定，说完后停住",
                            "action_progression": "从吸气推进到完整说出口",
                            "emotion_progression": "紧张后释然",
                            "screen_direction": "两人围绕同一对视轴线站定",
                            "end_state_lock": "林屿说完后停住，苏晚安静看着他",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "开场时两人已经面对面站在樱花步道上。",
                            "carry_over_elements": [],
                            "allowed_changes": "从吸气推进到完整说出口。",
                            "transition_reason": "当前 chunk 起始。",
                        },
                    }
                ]
            }
        ).segments[0]
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "tmp-seg-02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc04",
                        "title": "世界安静下来",
                        "summary": "风声忽然变轻，广播声远去，林屿感觉时间像凝在这一刻。",
                        "involved_characters": ["林屿", "苏晚"],
                        "start_frame_characters": ["林屿", "苏晚"],
                        "end_frame_characters": ["林屿", "苏晚"],
                        "timed_beats": [
                            "0-3秒：林屿说完后停住呼吸，苏晚安静看着他，樱花在风里慢慢停下来。",
                            "3-6秒：远处广播声变得很远，世界像安静下来，时间仿佛凝在这一刻。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定双人镜头，轻微停顿收束",
                            "blocking": "两人仍面对面站在樱花步道上，谁都没有先移开视线",
                            "action_progression": "从告白后的停顿推进到世界安静下来的余韵",
                            "emotion_progression": "紧张后坠入静谧",
                            "screen_direction": "两人围绕同一对视轴线停住",
                            "end_state_lock": "风声变轻，广播声远去，两人停在这一刻的静谧里",
                        },
                        "continuity_link": {
                            "previous_segment_id": "ch01-sc04-seg01",
                            "transition_mode": "continue",
                            "opening_match": "承接林屿刚说完后的停顿状态，苏晚仍安静看着他。",
                            "carry_over_elements": ["面对面站位", "樱花步道", "告白后的停顿"],
                            "allowed_changes": "从说完后的停顿推进到世界安静下来的余韵。",
                            "transition_reason": "承接告白后的静谧收束。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_chunk_contract_output(
            contracts,
            scene=scene,
            chunk=chunk,
            previous_tail_segment=previous_tail_segment,
        )

        self.assertEqual(validated.segments[0].segment_id, "tmp-seg-02")

    def test_scene_segment_contract_output_auto_expands_short_duration_to_fit_action_budget(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖会面",
                "summary": "陈默在镜湖边等待林晚走近。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": [],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                    "character_blocking": "陈默站在长椅旁，林晚从步道走近",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "她走近",
                        "summary": "陈默看见林晚走近，两人在长椅旁停下。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-2秒：陈默站在长椅旁等待。",
                            "2-5秒：林晚从步道走近，两人在长椅旁停下。",
                            "5-8秒：两人对视，气氛安静下来。",
                        ],
                        "duration_seconds": 5,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定轻微前推",
                            "blocking": "陈默在长椅旁，林晚从右侧步道走近后停下",
                            "action_progression": "从等待到走近，再到停下对视",
                            "emotion_progression": "紧张转为安静",
                            "screen_direction": "林晚从右侧走近陈默",
                            "end_state_lock": "两人在长椅旁停下对视",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已经站在镜湖长椅旁等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "林晚走近，两人停下对视。",
                            "transition_reason": "当前 chunk 起始。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(validated.segments[0].duration_seconds, 8)

    def test_scene_segment_contract_output_auto_expands_medium_duration_to_fit_action_budget(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖会面",
                "summary": "陈默和林晚在镜湖边经历一连串动作。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": [],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                    "character_blocking": "两人在长椅旁移动并停下",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "连续动作",
                        "summary": "两人完成过多连续动作。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默", "林晚"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-2秒：陈默抬头。",
                            "2-4秒：林晚停步。",
                            "4-6秒：陈默递出信封。",
                            "6-10秒：林晚接过信封后，两人停住对视。",
                        ],
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "稳定跟拍",
                            "blocking": "两人在长椅旁连续移动",
                            "action_progression": "完成多轮连续动作",
                            "emotion_progression": "紧张推进到回应",
                            "screen_direction": "保持同一运动轴线",
                            "end_state_lock": "两人并肩走向湖边",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "两人已经站在镜湖长椅旁。",
                            "carry_over_elements": [],
                            "allowed_changes": "完成多轮动作。",
                            "transition_reason": "当前 chunk 起始。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(validated.segments[0].duration_seconds, 10)

    def test_scene_segment_contract_output_still_splits_when_action_budget_exceeds_max_duration(self) -> None:
        service = NovelToVideoService()
        action_beats = [
            "0-3秒：陈默抬头，林晚停步，陈默递出信封。",
            "3-6秒：林晚接过信封，低头读信，抬头看向陈默。",
            "6-9秒：陈默后退半步，林晚靠近一步，两人重新停住。",
            "9-12秒：陈默开口，林晚回应，两人并肩走向湖边。",
            "12-15秒：两人停下回头，重新走回长椅旁。",
        ]

        with self.assertRaisesRegex(SegmentActionSplitRequiredError, "动作容量过载"):
            service._validate_segment_action_capacity(
                segment_id="ch01-sc01-seg02",
                timed_beats=action_beats,
                duration_seconds=12,
                allow_split_retry=True,
            )

    def test_scene_segment_contract_output_auto_expands_duration_to_fit_speech_budget(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖告白",
                "summary": "主角在镜湖边终于开口告白。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠湖，镜头从侧前方拍摄",
                    "character_blocking": "陈默站在长椅旁开口",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "终于开口",
                        "summary": "陈默终于说出压在心里的话。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默"],
                        "end_frame_characters": ["陈默"],
                        "narration": "",
                        "dialogue_lines": [f"陈默：{'我' * 34}"],
                        "subtitle_lines": ["我" * 34],
                        "timed_beats": [
                            "0-4秒：陈默深吸一口气，终于抬头看向前方。",
                            "4-9秒：他把压在心里的话完整说出来。",
                            "9-12秒：他说完后仍站在原地，保持目光望向前方等待回应。",
                        ],
                        "duration_seconds": 9,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "从犹豫推进到完整开口",
                            "end_state_lock": "陈默说完后仍站在原地等待回应",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已站在镜湖长椅旁，手里攥着信封，准备开口。",
                            "carry_over_elements": [],
                            "allowed_changes": "把犹豫推进到正式告白。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(validated.segments[0].duration_seconds, 12)

    def test_scene_segment_contract_output_normalizes_multi_character_shared_shot_closeup(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖会面",
                "summary": "陈默和林晚在镜湖边会面。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                    "character_blocking": "陈默与林晚在长椅旁面对面站定",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "正式会面",
                        "summary": "两人在镜湖边正式对视。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-4秒：陈默先停在镜湖边等待。",
                            "4-8秒：林晚走近后，两人停住并正式对视。",
                        ],
                        "start_frame_prompt": "陈默独自站在镜湖边等待。",
                        "end_frame_prompt": "两人仍停在镜湖边维持对视。",
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "镜头逐渐推向陈默侧脸特写。",
                            "blocking": "两人在长椅旁面对面站定",
                            "action_progression": "从停步推进到稳定对视",
                            "end_state_lock": "两人停在对视姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "两人已站在镜湖长椅旁，刚停下脚步。",
                            "carry_over_elements": [],
                            "allowed_changes": "从停步推进到正式对视。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(
            validated.segments[0].shot_state.camera_motion,
            "镜头轻微推进或稳定跟随，保持 陈默、林晚 多人同框；只通过站位、视线和表情差异突出主要情绪。",
        )
        self.assertIn("多人", validated.segments[0].motion_plan.camera_path)

    def test_scene_segment_contract_output_rejects_mid_frame_partial_drop_of_anchor_pair(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖会面",
                "summary": "陈默和林晚在镜湖边会面。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "并肩停步",
                        "summary": "两人在镜湖边停步对视。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默", "林晚"],
                        "mid_frame_characters": ["陈默"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-4秒：两人一起停在镜湖长椅旁。",
                            "4-8秒：镜头推进后，两人仍保持对视。",
                        ],
                        "start_frame_prompt": "两人一起停在镜湖长椅旁。",
                        "mid_frame_prompt": "陈默独自站在镜湖边。",
                        "end_frame_prompt": "两人仍停在镜湖长椅旁对视。",
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "镜头缓慢推进",
                            "blocking": "两人面对面站定",
                            "action_progression": "从停步推进到稳定对视",
                            "end_state_lock": "两人停在对视姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "两人已一起停在镜湖长椅旁，保持面对面站位。",
                            "carry_over_elements": [],
                            "allowed_changes": "从停步推进到更稳定的对视。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "不能只保留首尾同组角色的一部分"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_scene_segment_contract_output_allows_disjoint_insert_mid_frame(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖会面",
                "summary": "陈默和林晚在镜湖边会面，镜头中途切到路人。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚", "路人甲"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "background_anchors": ["镜湖", "长椅", "步道"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "会面与插入镜头",
                        "summary": "两人在镜湖边对视，中段切到旁边路人经过。",
                        "involved_characters": ["陈默", "林晚", "路人甲"],
                        "start_frame_characters": ["陈默", "林晚"],
                        "mid_frame_characters": ["路人甲"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-3秒：陈默和林晚在镜湖长椅旁停步对视。",
                            "3-5秒：镜头切到步道上的路人甲从远处经过。",
                            "5-8秒：镜头切回两人，仍保持原位对视。",
                        ],
                        "start_frame_prompt": "陈默和林晚一起停在镜湖长椅旁。",
                        "mid_frame_prompt": "路人甲独自从镜湖步道上经过。",
                        "end_frame_prompt": "镜头切回后，两人仍在镜湖长椅旁对视。",
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "中景",
                            "camera_motion": "镜头平稳推进并中途切到插入镜头",
                            "blocking": "两人在长椅旁面对面，路人甲在步道独立经过",
                            "action_progression": "会面中插入步道经过镜头，再回到两人对视",
                            "end_state_lock": "镜头切回后两人仍维持对视姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默和林晚已一起停在镜湖长椅旁，保持面对面站位。",
                            "carry_over_elements": [],
                            "allowed_changes": "先建立双人对视，再短暂切到步道上的路人镜头，最后切回两人。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(validated.segments[0].mid_frame_characters, ["路人甲"])

    def test_scene_segment_contract_output_allows_insert_cut_for_subset_mid_frame_group(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖告白",
                "summary": "陈默和林晚对话，中段切入林晚的单人反应特写。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "background_anchors": ["镜湖", "长椅", "步道"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "告白停顿",
                        "summary": "两人在镜湖边对视，中段切入林晚的单人反应特写，再回到双人关系。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默", "林晚"],
                        "mid_frame_characters": ["林晚"],
                        "mid_frame_mode": "insert_cut",
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-3秒：陈默和林晚在镜湖长椅旁对视，气氛短暂凝住。",
                            "3-5秒：镜头从双人关系镜头短促切入林晚的单人反应特写，她先低头又抬眼。",
                            "5-8秒：镜头切回双人中景，两人重新回到对视关系。",
                        ],
                        "start_frame_prompt": "陈默和林晚一起停在镜湖长椅旁，保持对视。",
                        "mid_frame_prompt": "短促切入林晚的单人反应特写，她低头后又抬眼，情绪明显起伏。",
                        "end_frame_prompt": "镜头切回后，两人仍停在镜湖长椅旁对视，关系重新稳定。",
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "双人中景建立关系后，中段短促切入单人反应特写，再回到双人中景收束",
                            "camera_motion": "先稳定保持双人关系镜头，再自然切入中段单人反应特写，最后切回双人主镜头",
                            "blocking": "陈默和林晚面对面站定，中段只切入林晚的面部和肩线反应",
                            "action_progression": "从对视停顿推进到林晚的情绪反应，再回到双人对视收束",
                            "end_state_lock": "镜头切回后，两人维持稳定对视姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默和林晚已一起停在镜湖长椅旁，保持面对面站位。",
                            "carry_over_elements": [],
                            "allowed_changes": "在双人对视中插入林晚的单人情绪反应，再回到两人对视。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
        )

        self.assertEqual(validated.segments[0].mid_frame_mode, "insert_cut")
        self.assertEqual(validated.segments[0].mid_frame_characters, ["林晚"])

    def test_scene_segment_contract_output_rejects_timed_beats_under_duration(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖等待",
                "summary": "陈默在镜湖边等待。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "停在原地",
                        "summary": "陈默在镜湖边等待并整理情绪。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "end_frame_characters": ["陈默"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-3秒：陈默站在镜湖长椅旁等待。",
                            "3-6秒：他抬头看向步道方向。",
                            "6-9秒：他低头整理手中的信封。",
                        ],
                        "start_frame_prompt": "陈默站在镜湖长椅旁等待。",
                        "end_frame_prompt": "陈默仍站在原地，整理信封后再次抬头。",
                        "duration_seconds": 11,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "单人中景",
                            "camera_motion": "轻微前推，保持陈默单人入镜",
                            "blocking": "陈默站在长椅旁，没有离开原位",
                            "action_progression": "从等待推进到抬头，再到低头整理信封",
                            "end_state_lock": "陈默整理完信封后仍停在原地，目光重新望向前方",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已经站在镜湖长椅旁，保持等待姿态。",
                            "carry_over_elements": [],
                            "allowed_changes": "从等待推进到短暂整理信封，再回到等待。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "尾部约 2s 缺少明确动作或收束节拍"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_scene_segment_contract_output_rejects_flat_keyframe_semantic_distance(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖停顿",
                "summary": "陈默在镜湖边停顿。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "停在原地",
                        "summary": "陈默停在镜湖长椅旁，没有明显变化。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默"],
                        "end_frame_characters": ["陈默"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-4秒：陈默停在镜湖长椅旁，保持等待姿态。",
                            "4-8秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
                        ],
                        "start_frame_prompt": "陈默停在镜湖长椅旁。",
                        "mid_frame_prompt": "陈默仍停在镜湖长椅旁。",
                        "end_frame_prompt": "陈默依旧停在镜湖长椅旁。",
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "单人中景",
                            "camera_motion": "轻微前推，保持陈默单人入镜",
                            "blocking": "陈默站在长椅旁，没有离开原位",
                            "action_progression": "保持等待姿态，没有明显变化",
                            "end_state_lock": "陈默仍停在原地，姿态几乎不变",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已经停在镜湖长椅旁，保持等待姿态。",
                            "carry_over_elements": [],
                            "allowed_changes": "继续保持当前等待状态。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "关键帧语义距离过近"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_scene_segment_contract_output_rejects_flat_start_end_keyframe_semantic_distance_without_mid(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖停顿",
                "summary": "陈默在镜湖边停顿。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "停在原地",
                        "summary": "陈默停在镜湖长椅旁，没有明显变化。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "end_frame_characters": ["陈默"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-3秒：陈默停在镜湖长椅旁，保持等待姿态。",
                            "3-6秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
                        ],
                        "start_frame_prompt": "陈默停在镜湖长椅旁。",
                        "end_frame_prompt": "陈默依旧停在镜湖长椅旁。",
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "单人中景",
                            "camera_motion": "轻微前推，保持陈默单人入镜",
                            "blocking": "陈默站在长椅旁，没有离开原位",
                            "action_progression": "保持等待姿态，没有明显变化",
                            "end_state_lock": "陈默仍停在原地，姿态几乎不变",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已经停在镜湖长椅旁，保持等待姿态。",
                            "carry_over_elements": [],
                            "allowed_changes": "继续保持当前等待状态。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "关键帧语义距离过近"):
            service._validate_scene_segment_contract_output(
                contracts,
                scene=scene,
            )

    def test_scene_chunk_contract_output_rejects_segments_beyond_expected_limit(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖等待",
                "summary": "陈默在镜湖边等待后与林晚会面。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "wait-and-meet",
                "order_index": 1,
                "title": "等待与会面",
                "summary": "等待后直接会面。",
                "must_cover": ["等待", "会面"],
                "transition_goal": "两人开始对话。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并听见脚步声",
                            "end_state_lock": "陈默听见脚步声后微微回头，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已站在镜湖长椅旁，面向湖面等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立单人等待的开场基线。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    },
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "会面",
                        "summary": "林晚走近后，两人正式会面。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "林晚走近后，两人终于站定面对面。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林晚走近后，两人终于站定面对面。"],
                        "timed_beats": ["0-6秒：林晚走近后，两人终于站定面对面。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "continue",
                        "shot_state": {
                            "action_progression": "从等待推进到正式会面",
                            "end_state_lock": "两人面对面站定",
                        },
                        "continuity_link": {
                            "previous_segment_id": "ch01-sc01-seg01",
                            "transition_mode": "continue",
                            "opening_match": "陈默仍在长椅旁微微回头，保持上一段听见脚步声后停住的姿态。",
                            "carry_over_elements": ["镜湖长椅", "陈默站位", "右向视线"],
                            "allowed_changes": "林晚入镜，两人从等待推进到正式会面。",
                            "transition_reason": "同一 chunk 内继续推进到会面动作。",
                        },
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "超过当前 chunk 的执行上限"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
            )

    def test_scene_chunk_contract_batch_retries_with_more_segments_when_single_segment_exceeds_12s(self) -> None:
        class SplitRetryBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "完整告白",
                                "summary": "两人把整轮告白和回应都放进同一段里。",
                                "involved_characters": ["陈默", "林晚"],
                                "start_frame_characters": ["陈默"],
                                "mid_frame_characters": ["陈默", "林晚"],
                                "end_frame_characters": ["陈默", "林晚"],
                                "narration": "",
                                "dialogue_lines": [
                                    f"陈默：{'我' * 40}",
                                    f"林晚：{'好' * 38}",
                                ],
                                "subtitle_lines": [
                                    "我" * 40,
                                    "好" * 38,
                                ],
                                "timed_beats": [
                                    "0-4秒：陈默终于开口。",
                                    "4-8秒：林晚认真听着。",
                                    "8-12秒：两人都想把整轮对白一次说完。",
                                ],
                                "duration_seconds": 12,
                                "requires_mid_frame": True,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中景",
                                    "camera_motion": "轻微前推",
                                    "blocking": "陈默在前，林晚站在对面",
                                    "action_progression": "从犹豫开口推进到完整告白与回应",
                                    "emotion_progression": "紧张迅速升高",
                                    "prop_continuity": "书包和信封保持在手边",
                                    "screen_direction": "保持面对面站位",
                                    "end_state_lock": "两人仍停在面对面的告白姿态",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "陈默已站在花园长椅旁，面向林晚准备开口。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "推进到完整告白与回应。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            }
                        ],
                    }
                return {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg01",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "试探开口",
                            "summary": "陈默先试探着开口，把气氛推到正式告白前。",
                            "involved_characters": ["陈默", "林晚"],
                            "start_frame_characters": ["陈默"],
                            "mid_frame_characters": ["陈默", "林晚"],
                            "end_frame_characters": ["陈默", "林晚"],
                            "narration": "",
                            "dialogue_lines": ["陈默：林晚，我想先把一直压着的话说出来。"],
                            "subtitle_lines": ["林晚，我想先把一直压着的话说出来。"],
                            "timed_beats": [
                                "0-4秒：陈默深吸一口气，终于看向林晚。",
                                "4-8秒：他先用一句试探的话打开局面。",
                            ],
                            "duration_seconds": 8,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "双人中景",
                                "camera_motion": "缓慢前推",
                                "blocking": "两人站定，陈默先开口",
                                "action_progression": "从沉默对视推进到试探开口",
                                "emotion_progression": "紧张但开始稳定",
                                "prop_continuity": "信封仍握在陈默手里",
                                "screen_direction": "保持面对面站位",
                                "end_state_lock": "陈默说完开场句，等待林晚反应",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "陈默已站在花园长椅旁，面向林晚准备开口。",
                                "carry_over_elements": [],
                                "allowed_changes": "把气氛推进到正式告白前的开场句。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        },
                        {
                            "segment_id": "ch01-sc01-seg02",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "正式告白",
                            "summary": "陈默把最核心的告白内容完整说出来。",
                            "involved_characters": ["陈默", "林晚"],
                            "start_frame_characters": ["陈默", "林晚"],
                            "mid_frame_characters": ["陈默", "林晚"],
                            "end_frame_characters": ["陈默", "林晚"],
                            "narration": "",
                            "dialogue_lines": ["陈默：我喜欢你很久了，今天不想再躲着这句话。"],
                            "subtitle_lines": ["我喜欢你很久了，今天不想再躲着这句话。"],
                            "timed_beats": [
                                "0-5秒：陈默一口气把最重要的话说出来。",
                                "5-10秒：林晚愣住，情绪被彻底推高。",
                            ],
                            "duration_seconds": 10,
                            "requires_mid_frame": True,
                            "transition_hint": "continue",
                            "shot_state": {
                                "framing": "双人中近景",
                                "camera_motion": "轻微前压",
                                "blocking": "两人仍保持面对面站位",
                                "action_progression": "从开场句推进到完整告白",
                                "emotion_progression": "紧张转为坦白后的释放",
                                "prop_continuity": "信封仍在陈默手里，林晚没有离开站位",
                                "screen_direction": "延续面对面视线",
                                "end_state_lock": "林晚怔住，陈默仍望着她等待回答",
                            },
                            "continuity_link": {
                                "previous_segment_id": "ch01-sc01-seg01",
                                "transition_mode": "continue",
                                "opening_match": "承接上一段尾部，陈默仍看着林晚，刚说完开场句。",
                                "carry_over_elements": ["面对面站位", "信封", "花园长椅背景"],
                                "allowed_changes": "把试探开口推进到正式告白。",
                                "transition_reason": "同一 chunk 内继续推进到核心告白。",
                            },
                        },
                        {
                            "segment_id": "ch01-sc01-seg03",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "回应落点",
                            "summary": "林晚给出第一句明确回应，让这一轮对白自然落点。",
                            "involved_characters": ["陈默", "林晚"],
                            "start_frame_characters": ["陈默", "林晚"],
                            "mid_frame_characters": ["林晚", "陈默"],
                            "end_frame_characters": ["陈默", "林晚"],
                            "narration": "",
                            "dialogue_lines": ["林晚：我听见了，也不想再让你一个人等下去。"],
                            "subtitle_lines": ["我听见了，也不想再让你一个人等下去。"],
                            "timed_beats": [
                                "0-4秒：林晚先稳住呼吸，认真看向陈默。",
                                "4-9秒：她给出第一句明确回应，关系落到新的状态。",
                            ],
                            "duration_seconds": 9,
                            "requires_mid_frame": True,
                            "transition_hint": "continue",
                            "shot_state": {
                                "framing": "双人中近景",
                                "camera_motion": "轻微停顿后慢推",
                                "blocking": "林晚接住陈默的视线并回应",
                                "action_progression": "从怔住推进到明确回应",
                                "emotion_progression": "克制转为温柔确认",
                                "prop_continuity": "两人站位不变，信封仍留在画面里",
                                "screen_direction": "保持对视方向",
                                "end_state_lock": "两人停在新的确认关系里",
                            },
                            "continuity_link": {
                                "previous_segment_id": "ch01-sc01-seg02",
                                "transition_mode": "continue",
                                "opening_match": "承接上一段尾部，林晚怔住，陈默仍望着她等待回答。",
                                "carry_over_elements": ["对视方向", "花园长椅背景", "信封"],
                                "allowed_changes": "把正式告白推进到第一句明确回应。",
                                "transition_reason": "同一 chunk 内继续推进到回应落点。",
                            },
                        },
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-split-retry",
        )
        backend = SplitRetryBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-split-retry-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园告白",
                "summary": "两人在花园长椅旁完成一轮告白与回应。",
                "scene_anchor": "花园长椅，傍晚，暖色侧光",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "花园长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["花园长椅", "树影", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，人物面对面站在长椅前",
                    "character_blocking": "两人先对视，再完成告白与回应",
                    "continuity_notes": "保持长椅、树影和石板路关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc01-c02",
                "order_index": 2,
                "title": "告白与回应",
                "summary": "这一轮对白很长，必须分成更细的执行段。",
                "must_cover": ["试探开口", "正式告白", "明确回应"],
                "transition_goal": "两人停在新的关系状态里。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 2)
        self.assertEqual(len(result.segments), 3)
        self.assertIn("至少拆成 3 个 segment", backend.requests[-1].user_prompt)
        self.assertIn("这次最多只能输出 3 个 segment", backend.requests[-1].user_prompt)

    def test_scene_chunk_contract_batch_retries_with_more_segments_when_action_budget_overflows(self) -> None:
        class ActionSplitRetryBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if self.calls == 1:
                    return {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "一段塞满动作",
                                "summary": "陈默把等待、回头和开口全塞进一个短段里。",
                                "involved_characters": ["陈默"],
                                "start_frame_characters": ["陈默"],
                                "mid_frame_characters": ["陈默"],
                                "end_frame_characters": ["陈默"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-2秒：陈默站在长椅旁等待。",
                                    "2-4秒：他回头看向步道方向。",
                                    "4-6秒：他深呼吸后终于开口。",
                                ],
                                "duration_seconds": 6,
                                "requires_mid_frame": True,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "单人中景",
                                    "camera_motion": "轻微前推",
                                    "blocking": "陈默站在长椅旁没有离开原位",
                                    "action_progression": "从等待推进到回头再到开口",
                                    "emotion_progression": "紧张不断升高",
                                    "prop_continuity": "信封一直握在手里",
                                    "screen_direction": "先面向湖面，再回头看向步道",
                                    "end_state_lock": "陈默开口后仍站在长椅旁",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "陈默已站在花园长椅旁等待。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "从等待推进到回头再到开口。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            }
                        ],
                    }
                return {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg01",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "等待回头",
                            "summary": "陈默先在长椅旁等待，再回头看向步道。",
                            "involved_characters": ["陈默"],
                            "start_frame_characters": ["陈默"],
                            "mid_frame_characters": ["陈默"],
                            "end_frame_characters": ["陈默"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "timed_beats": [
                                "0-3秒：陈默站在长椅旁等待。",
                                "3-6秒：他听见动静后回头看向步道方向。",
                            ],
                            "duration_seconds": 6,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "单人中景",
                                "camera_motion": "轻微前推",
                                "blocking": "陈默站在长椅旁等待后再回头",
                                "action_progression": "从等待推进到回头确认来路",
                                "emotion_progression": "紧张开始抬升",
                                "prop_continuity": "信封仍握在手里",
                                "screen_direction": "从面向湖面转为看向步道",
                                "end_state_lock": "陈默回头后停住，准备开口",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "陈默已站在花园长椅旁等待。",
                                "carry_over_elements": [],
                                "allowed_changes": "从等待推进到回头确认来路。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        },
                        {
                            "segment_id": "ch01-sc01-seg02",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "终于开口",
                            "summary": "陈默在短暂停顿后终于把第一句说出来。",
                            "involved_characters": ["陈默"],
                            "start_frame_characters": ["陈默"],
                            "mid_frame_characters": ["陈默"],
                            "end_frame_characters": ["陈默"],
                            "narration": "",
                            "dialogue_lines": ["陈默：林晚，我还是想把这句话说出来。"],
                            "subtitle_lines": ["林晚，我还是想把这句话说出来。"],
                            "timed_beats": [
                                "0-3秒：陈默稳住呼吸，继续看向步道方向。",
                                "3-8秒：他终于把压在心里的第一句说出来。",
                            ],
                            "duration_seconds": 8,
                            "requires_mid_frame": True,
                            "transition_hint": "continue",
                            "shot_state": {
                                "framing": "单人中近景",
                                "camera_motion": "轻微停顿后前压",
                                "blocking": "陈默仍站在原位，开口时上身略微前倾",
                                "action_progression": "从停顿推进到真正开口",
                                "emotion_progression": "紧张转为决心",
                                "prop_continuity": "信封仍留在手边",
                                "screen_direction": "继续看向步道方向",
                                "end_state_lock": "陈默说完第一句后仍站在长椅旁等待回应",
                            },
                            "continuity_link": {
                                "previous_segment_id": "ch01-sc01-seg01",
                                "transition_mode": "continue",
                                "opening_match": "承接上一段尾部，陈默刚回头停住，仍站在长椅旁准备开口。",
                                "carry_over_elements": ["花园长椅背景", "信封", "朝步道方向的视线"],
                                "allowed_changes": "把回头停顿推进到真正开口。",
                                "transition_reason": "同一 chunk 内继续推进到开口动作。",
                            },
                        },
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-action-split-retry",
        )
        backend = ActionSplitRetryBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-action-split-retry-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园等待",
                "summary": "陈默在花园长椅旁等待后终于开口。",
                "scene_anchor": "花园长椅，傍晚，暖色侧光",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "花园长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["花园长椅", "树影", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，陈默站在长椅前方",
                    "character_blocking": "先等待回头，再真正开口",
                    "continuity_notes": "保持长椅、树影和石板路关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc01-c01",
                "order_index": 1,
                "title": "等待到开口",
                "summary": "短时长内不能把等待、回头和开口硬塞进同一个 segment。",
                "must_cover": ["等待", "回头确认", "正式开口"],
                "transition_goal": "陈默说出第一句，让场面进入正式对话。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 2)
        self.assertEqual(len(result.segments), 2)
        self.assertIn("至少拆成 2 个 segment", backend.requests[-1].user_prompt)
        self.assertIn("这次最多只能输出 2 个 segment", backend.requests[-1].user_prompt)

    def test_scene_chunk_contract_batch_runs_overflow_repair_after_chunk_retries_exhausted(self) -> None:
        class OverflowRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-overflow-repair":
                    return {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "终于开口",
                                "summary": "陈默先把压在心里的第一层告白说出来。",
                                "involved_characters": ["陈默", "林晚"],
                                "start_frame_characters": ["陈默"],
                                "mid_frame_characters": ["陈默", "林晚"],
                                "end_frame_characters": ["陈默", "林晚"],
                                "narration": "",
                                "dialogue_lines": ["陈默：林晚，我喜欢你很久了。"],
                                "subtitle_lines": ["林晚，我喜欢你很久了。"],
                                "timed_beats": [
                                    "0-4秒：陈默先抬头看向林晚。",
                                    "4-8秒：他说出第一句明确告白。",
                                ],
                                "duration_seconds": 8,
                                "requires_mid_frame": True,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中景",
                                    "camera_motion": "缓慢前推",
                                    "blocking": "两人面对面站定",
                                    "action_progression": "从沉默对视推进到正式开口",
                                    "emotion_progression": "紧张被说出口的勇气打破",
                                    "prop_continuity": "信封仍握在陈默手里",
                                    "screen_direction": "保持面对面站位",
                                    "end_state_lock": "陈默说完第一句后仍看着林晚等待反应",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "陈默已站在花园长椅旁，手里攥着信封，正看向林晚准备开口。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "把犹豫推进到第一句明确告白。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            },
                            {
                                "segment_id": "ch01-sc01-seg02",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "回应落下",
                                "summary": "林晚在短暂停顿后给出明确回应，两人的关系状态正式改变。",
                                "involved_characters": ["陈默", "林晚"],
                                "start_frame_characters": ["陈默", "林晚"],
                                "mid_frame_characters": ["陈默", "林晚"],
                                "end_frame_characters": ["陈默", "林晚"],
                                "narration": "",
                                "dialogue_lines": [
                                    "林晚：我听到了，我也不想再把这句话藏着。",
                                ],
                                "subtitle_lines": ["我听到了，我也不想再把这句话藏着。"],
                                "timed_beats": [
                                    "0-4秒：林晚先怔住，目光没有移开。",
                                    "4-9秒：她缓慢开口给出明确回应。",
                                ],
                                "duration_seconds": 9,
                                "requires_mid_frame": True,
                                "transition_hint": "continue",
                                "shot_state": {
                                    "framing": "双人中近景",
                                    "camera_motion": "轻微前推后停住",
                                    "blocking": "两人仍面对面站定，林晚开始回应",
                                    "action_progression": "从等待回应推进到明确回应落下",
                                    "emotion_progression": "紧张转为确认后的轻微松动",
                                    "prop_continuity": "信封仍在陈默手里",
                                    "screen_direction": "保持面对面站位",
                                    "end_state_lock": "两人停在新的关系确认状态里",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "ch01-sc01-seg01",
                                    "transition_mode": "continue",
                                    "opening_match": "承接上一段尾部，陈默仍看着林晚等待反应，林晚先短暂停住后准备开口。",
                                    "carry_over_elements": ["面对面站位", "信封", "对视关系"],
                                    "allowed_changes": "把等待反应推进到明确回应落下。",
                                    "transition_reason": "同一 chunk 内继续推进到回应节点。",
                                },
                            },
                        ],
                    }
                return {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg03",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "完整长对白",
                            "summary": "模型把整轮告白和回应继续塞进一个超长片段里。",
                            "involved_characters": ["陈默", "林晚"],
                            "start_frame_characters": ["陈默"],
                            "mid_frame_characters": ["陈默", "林晚"],
                            "end_frame_characters": ["陈默", "林晚"],
                            "narration": "",
                            "dialogue_lines": [
                                f"陈默：{'我' * 26}",
                                f"林晚：{'好' * 22}",
                            ],
                            "subtitle_lines": [
                                "我" * 26,
                                "好" * 22,
                            ],
                            "timed_beats": [
                                "0-4秒：陈默抬头看向林晚。",
                                "4-8秒：他一口气把整段告白说完。",
                                "8-12秒：林晚也尝试把整句回应一次说完。",
                            ],
                            "duration_seconds": 12,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "双人中景",
                                "camera_motion": "缓慢前推",
                                "blocking": "两人面对面站定",
                                "action_progression": "从开口推进到完整告白与回应",
                                "emotion_progression": "紧张持续升高",
                                "prop_continuity": "信封仍在陈默手里",
                                "screen_direction": "保持面对面站位",
                                "end_state_lock": "两人仍停在面对面的回应姿态",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "陈默已站在花园长椅旁，手里攥着信封，准备开口。",
                                "carry_over_elements": [],
                                "allowed_changes": "把整轮告白与回应塞进一个片段。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-overflow-repair",
        )
        backend = OverflowRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-overflow-repair-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园告白",
                "summary": "两人在花园长椅旁完成一轮告白与回应。",
                "scene_anchor": "花园长椅，傍晚，暖色侧光",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "花园长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["花园长椅", "树影", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，人物面对面站在长椅前",
                    "character_blocking": "两人先对视，再完成告白与回应",
                    "continuity_notes": "保持长椅、树影和石板路关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc01-c02",
                "order_index": 2,
                "title": "告白与回应",
                "summary": "这一轮对白很长，必须被正式拆开。",
                "must_cover": ["正式告白", "明确回应"],
                "transition_goal": "两人停在新的关系状态里。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 4)
        self.assertEqual(
            [item.segment_id for item in result.segments],
            ["ch01-sc01-ck02-seg01", "ch01-sc01-ck02-seg02"],
        )
        self.assertEqual(
            backend.requests[-1].metadata.get("task"),
            "video-scene-segment-overflow-repair",
        )
        self.assertIn("上一轮失败 batch JSON", backend.requests[-1].user_prompt)
        self.assertIn("ch01-sc01-seg03", backend.requests[-1].user_prompt)

    def test_scene_chunk_contract_batch_runs_timeline_repair_after_chunk_retries_exhausted(self) -> None:
        class TimelineRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-timeline-repair":
                    return {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "湖边等待",
                                "summary": "陈默在镜湖长椅旁等待，并把尾部停顿收束完整。",
                                "involved_characters": ["陈默"],
                                "start_frame_characters": ["陈默"],
                                "mid_frame_characters": ["陈默"],
                                "end_frame_characters": ["陈默"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-4秒：陈默站在镜湖长椅旁等待。",
                                    "4-8秒：他抬头看向步道方向，呼吸明显收紧。",
                                    "8-10秒：他停住动作，目光仍望向前方，等待下一拍回应。",
                                ],
                                "duration_seconds": 10,
                                "requires_mid_frame": True,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "单人中景",
                                    "camera_motion": "轻微前推后停住",
                                    "blocking": "陈默始终站在长椅旁，没有离开原位",
                                    "action_progression": "从等待推进到抬头，再收束到停住动作",
                                    "emotion_progression": "紧张感逐渐上升后停在等待反应的状态",
                                    "screen_direction": "目光始终朝向步道前方",
                                    "end_state_lock": "陈默停在抬头后的等待姿态里，视线没有移开",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "陈默已经站在镜湖长椅旁，保持等待姿态。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "从等待推进到抬头，再落到尾部停顿收束。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            }
                        ],
                    }
                return {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg01",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "湖边等待",
                            "summary": "陈默在镜湖长椅旁等待。",
                            "involved_characters": ["陈默"],
                            "start_frame_characters": ["陈默"],
                            "mid_frame_characters": ["陈默"],
                            "end_frame_characters": ["陈默"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "timed_beats": [
                                "0-4秒：陈默站在镜湖长椅旁等待。",
                                "4-8秒：他抬头看向步道方向。",
                            ],
                            "duration_seconds": 10,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "单人中景",
                                "camera_motion": "轻微前推",
                                "blocking": "陈默站在长椅旁，没有离开原位",
                                "action_progression": "从等待推进到抬头",
                                "emotion_progression": "紧张等待",
                                "screen_direction": "目光朝向步道前方",
                                "end_state_lock": "陈默抬头后停在原地，仍看向前方",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "陈默已经站在镜湖长椅旁，保持等待姿态。",
                                "carry_over_elements": [],
                                "allowed_changes": "从等待推进到抬头。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-timeline-repair",
        )
        backend = TimelineRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-timeline-repair-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖等待",
                "summary": "陈默在镜湖长椅旁等待林晚出现。",
                "scene_anchor": "镜湖长椅，傍晚，微风",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "湖蓝"],
                    "background_anchors": ["镜湖", "长椅", "步道"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                    "character_blocking": "陈默独自在长椅旁等待并抬头",
                    "continuity_notes": "保持长椅、湖面和步道关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc01-c01",
                "order_index": 1,
                "title": "镜湖等待",
                "summary": "陈默等待并抬头看向步道方向。",
                "must_cover": ["陈默等待", "陈默抬头看向步道"],
                "transition_goal": "情绪停在等待下一拍回应的状态。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 4)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            backend.requests[-1].metadata.get("task"),
            "video-scene-segment-timeline-repair",
        )
        self.assertEqual(
            backend.requests[-1].metadata.get("offending_segment_id"),
            "ch01-sc01-seg01",
        )
        self.assertIn("上一轮失败 batch JSON", backend.requests[-1].user_prompt)
        self.assertIn("尾部仍有约 2 秒没有合同约束", backend.requests[-1].user_prompt)
        self.assertIn(
            "8-10秒：他停住动作，目光仍望向前方，等待下一拍回应。",
            result.segments[0].timed_beats,
        )

    def test_timeline_repair_auto_expands_when_repaired_beats_are_action_dense(self) -> None:
        class DenseTimelineRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-timeline-repair":
                    return {
                        "scene_id": "ch01-sc03",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc03-seg02",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc03",
                                "title": "密集动作补尾",
                                "summary": "两人在长椅旁完成一组密集动作。",
                                "involved_characters": ["林屿", "苏晚"],
                                "start_frame_characters": ["林屿", "苏晚"],
                                "mid_frame_characters": ["林屿", "苏晚"],
                                "end_frame_characters": ["林屿", "苏晚"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-2秒：林屿抬头。",
                                    "2-4秒：苏晚停步。",
                                    "4-6秒：林屿递出信封。",
                                    "6-8秒：苏晚接过信封。",
                                ],
                                "duration_seconds": 8,
                                "requires_mid_frame": True,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中景",
                                    "camera_motion": "稳定轻微前推",
                                    "blocking": "两人在长椅旁面对面站定",
                                    "action_progression": "从抬头到停步，再到递出和接过信封",
                                    "emotion_progression": "紧张推进到安静",
                                    "screen_direction": "保持面对面轴线",
                                    "end_state_lock": "苏晚接过信封后停住",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "两人已经站在长椅旁。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "完成递出和接过信封。",
                                    "transition_reason": "当前 chunk 起始。",
                                },
                            }
                        ],
                    }
                return {
                    "scene_id": "ch01-sc03",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc03-seg02",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc03",
                            "title": "密集动作",
                            "summary": "两人在长椅旁开始一组动作。",
                            "involved_characters": ["林屿", "苏晚"],
                            "start_frame_characters": ["林屿", "苏晚"],
                            "mid_frame_characters": ["林屿", "苏晚"],
                            "end_frame_characters": ["林屿", "苏晚"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "timed_beats": [
                                "0-2秒：林屿抬头。",
                                "2-4秒：苏晚停步。",
                                "4-6秒：林屿递出信封。",
                                "6-8秒：苏晚接过信封。",
                            ],
                            "duration_seconds": 10,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "双人中景",
                                "camera_motion": "稳定轻微前推",
                                "blocking": "两人在长椅旁面对面站定",
                                "action_progression": "从抬头到停步，再到递出和接过信封",
                                "emotion_progression": "紧张推进到安静",
                                "screen_direction": "保持面对面轴线",
                                "end_state_lock": "苏晚接过信封后停住",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "两人已经站在长椅旁。",
                                "carry_over_elements": [],
                                "allowed_changes": "完成递出和接过信封。",
                                "transition_reason": "当前 chunk 起始。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "dense-timeline-repair",
        )
        backend = DenseTimelineRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "dense-timeline-repair-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc03",
                "chapter_number": 1,
                "title": "长椅动作",
                "summary": "林屿和苏晚在长椅旁完成递信动作。",
                "scene_anchor": "长椅旁，傍晚，暖色侧光",
                "involved_characters": ["林屿", "苏晚"],
                "scene_bible": {
                    "location": "长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "浅蓝"],
                    "background_anchors": ["长椅", "树影", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，两人面对面站立",
                    "character_blocking": "两人面对面完成递信动作",
                    "continuity_notes": "保持长椅和两人面对面站位稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc03-c01",
                "order_index": 1,
                "title": "递出信封",
                "summary": "林屿递出信封，苏晚接过。",
                "must_cover": ["抬头", "停步", "递出信封", "接过信封"],
                "transition_goal": "苏晚接过信封后停住。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(result.segments[0].duration_seconds, 10)
        self.assertEqual(backend.requests[-1].metadata.get("task"), "video-scene-segment-timeline-repair")

    def test_scene_chunk_contract_batch_runs_action_repair_after_chunk_retries_exhausted(self) -> None:
        class ActionRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-action-repair":
                    return {
                        "scene_id": "ch01-sc02",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc02-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc02",
                                "title": "停步回望",
                                "summary": "两人先停下脚步，完成第一拍对视与情绪建立。",
                                "involved_characters": ["林辰", "苏晴"],
                                "start_frame_characters": ["林辰", "苏晴"],
                                "mid_frame_characters": ["林辰", "苏晴"],
                                "end_frame_characters": ["林辰", "苏晴"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-3秒：林辰和苏晴同时停下脚步，在花架下转向彼此。",
                                    "3-5秒：两人短暂对视，气氛从行走过渡到停住。",
                                ],
                                "duration_seconds": 5,
                                "requires_mid_frame": False,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中景",
                                    "camera_motion": "轻微跟停后稳定下来",
                                    "blocking": "两人从并肩走动收束到面对面停住",
                                    "action_progression": "从走动推进到停步与对视",
                                    "emotion_progression": "轻松转为紧张确认",
                                    "screen_direction": "镜头右向左跟停，随后稳定保持双人同框",
                                    "end_state_lock": "两人停在面对面站位里，准备进入下一拍开口",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "两人刚在花架下停住脚步，开始转向彼此。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "从并肩行走推进到停步回望。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            },
                            {
                                "segment_id": "ch01-sc02-seg02",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc02",
                                "title": "递出试探",
                                "summary": "林辰完成开口与递出物件，苏晴给出第一层反应。",
                                "involved_characters": ["林辰", "苏晴"],
                                "start_frame_characters": ["林辰", "苏晴"],
                                "mid_frame_characters": ["林辰", "苏晴"],
                                "end_frame_characters": ["林辰", "苏晴"],
                                "narration": "",
                                "dialogue_lines": ["林辰：这个，我一直想亲手给你。"],
                                "subtitle_lines": ["这个，我一直想亲手给你。"],
                                "timed_beats": [
                                    "0-4秒：承接上一段尾部，林辰仍站在苏晴面前，先深吸一口气再开口并递出小盒子。",
                                    "4-8秒：苏晴先怔住，但没有躲开，目光仍停在他递来的小盒子上。",
                                ],
                                "duration_seconds": 8,
                                "requires_mid_frame": True,
                                "transition_hint": "continue",
                                "shot_state": {
                                    "framing": "双人中近景",
                                    "camera_motion": "稳定轻推，跟住递出动作",
                                    "blocking": "林辰站在左侧递出小盒子，苏晴站在右侧停住接收这一拍",
                                    "action_progression": "从开口推进到递出物件，再落到对方第一层反应",
                                    "emotion_progression": "紧张推进到试探后的屏息等待",
                                    "prop_continuity": "小盒子始终在林辰手里并被明确递出",
                                    "screen_direction": "保持左到右的递出方向",
                                    "end_state_lock": "小盒子已递到两人之间，苏晴停在准备回应的状态里",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "ch01-sc02-seg01",
                                    "transition_mode": "continue",
                                    "opening_match": "承接上一段尾部，两人仍保持面对面站位，林辰刚结束对视后准备开口。",
                                    "carry_over_elements": ["双人面对面站位", "花架下停步状态"],
                                    "allowed_changes": "把停步对视推进到开口递出与第一层反应。",
                                    "transition_reason": "同一 chunk 内继续推进。",
                                },
                            },
                        ],
                    }
                return {
                    "scene_id": "ch01-sc02",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc02-seg02",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc02",
                            "title": "全部塞一起",
                            "summary": "停步、回望、开口、递出物件和对方反应都塞在一个片段里。",
                            "involved_characters": ["林辰", "苏晴"],
                            "start_frame_characters": ["林辰", "苏晴"],
                            "mid_frame_characters": ["林辰", "苏晴"],
                            "end_frame_characters": ["林辰", "苏晴"],
                            "narration": "",
                            "dialogue_lines": ["林辰：这个，我一直想亲手给你。"],
                            "subtitle_lines": ["这个，我一直想亲手给你。"],
                            "timed_beats": [
                                "0-2秒：两人同时停下脚步。",
                                "2-4秒：林辰回头看向苏晴。",
                                "4-6秒：林辰开口说话。",
                                "6-9秒：他把小盒子递出去，苏晴露出第一层反应。",
                            ],
                            "duration_seconds": 9,
                            "requires_mid_frame": True,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "双人中景",
                                "camera_motion": "边停边推近",
                                "blocking": "两人从并肩前行推进到面对面停住，再到递出物件",
                                "action_progression": "停步、回望、开口、递出物件和第一层反应全部塞进同一段",
                                "emotion_progression": "轻松迅速抬升到紧张试探",
                                "prop_continuity": "小盒子从手里被递到两人之间",
                                "screen_direction": "从前进方向转为面对面",
                                "end_state_lock": "两人停在递出后的第一层反应里",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "两人还在并肩走动后刚准备停住。",
                                "carry_over_elements": [],
                                "allowed_changes": "把多轮动作硬塞在 9 秒里。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-action-repair",
        )
        backend = ActionRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-action-repair-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "花架停步",
                "summary": "林辰和苏晴在花架下停步，关系开始进入试探。",
                "scene_anchor": "花架下，傍晚，暖色侧光",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "花架小径",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "花藤绿"],
                    "background_anchors": ["花架", "石板路", "树影"],
                    "fixed_props": ["小盒子"],
                    "spatial_layout": "花架沿石板路延伸，两人从路中央停下转向彼此",
                    "character_blocking": "并肩行走后停步回望，再开口递出物件",
                    "continuity_notes": "保持花架、石板路和两人左右站位稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc02-chunk02",
                "order_index": 2,
                "title": "停步试探",
                "summary": "从停步回望推进到开口递出物件。",
                "must_cover": ["停步回望", "开口试探", "递出物件"],
                "transition_goal": "苏晴给出第一层反应，关系进入下一拍。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 4)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(
            backend.requests[-1].metadata.get("task"),
            "video-scene-segment-action-repair",
        )
        self.assertEqual(
            backend.requests[-1].metadata.get("offending_segment_id"),
            "ch01-sc02-seg02",
        )
        self.assertEqual(
            backend.requests[-1].metadata.get("required_segment_count"),
            2,
        )
        self.assertIn("上一轮失败 batch JSON", backend.requests[-1].user_prompt)
        self.assertIn("当前约有 4 个推进点", backend.requests[-1].user_prompt)
        self.assertIn("至少拆成 2 个 segment", backend.requests[-1].user_prompt)

    def test_scene_chunk_contract_batch_runs_action_repair_iteratively_until_overload_clears(self) -> None:
        class IterativeActionRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []
                self.action_repair_calls = 0

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-action-repair":
                    self.action_repair_calls += 1
                    if self.action_repair_calls <= 3:
                        return {
                            "scene_id": "ch01-sc03",
                            "chapter_number": 1,
                            "segments": [
                                {
                                    "segment_id": "ch01-sc03-seg04a",
                                    "chapter_number": 1,
                                    "scene_id": "ch01-sc03",
                                    "title": "先靠近",
                                    "summary": "两人先靠近并短暂停住，但这一段仍然塞了太多推进。",
                                    "involved_characters": ["林屿", "苏晚"],
                                    "start_frame_characters": ["林屿", "苏晚"],
                                    "mid_frame_characters": [],
                                    "end_frame_characters": ["林屿", "苏晚"],
                                    "narration": "",
                                    "dialogue_lines": [],
                                    "subtitle_lines": [],
                                    "timed_beats": [
                                        "0-3秒：林屿向苏晚迈近一步，然后苏晚没有后退并抬眼看向他。",
                                        "3-6秒：两人同时停住，气氛继续收紧。",
                                    ],
                                    "duration_seconds": 6,
                                    "requires_mid_frame": False,
                                    "transition_hint": "auto",
                                    "shot_state": {
                                        "framing": "双人中景",
                                        "camera_motion": "轻微前推",
                                        "blocking": "两人从相隔半步推进到更近距离停住",
                                        "action_progression": "靠近、抬眼、停住都塞在同一段里",
                                        "emotion_progression": "试探迅速收紧",
                                        "screen_direction": "保持面对面轴线",
                                        "end_state_lock": "两人停在更近距离，准备进入下一拍。",
                                    },
                                    "continuity_link": {
                                        "previous_segment_id": "",
                                        "transition_mode": "start",
                                        "opening_match": "两人已经停在彼此前方，准备继续靠近。",
                                        "carry_over_elements": [],
                                        "allowed_changes": "从靠近推进到停住。",
                                        "transition_reason": "当前 chunk 的起始段。",
                                    },
                                },
                                {
                                    "segment_id": "ch01-sc03-seg04b",
                                    "chapter_number": 1,
                                    "scene_id": "ch01-sc03",
                                    "title": "停在屏息",
                                    "summary": "两人停在更近距离，等待下一拍开口。",
                                    "involved_characters": ["林屿", "苏晚"],
                                    "start_frame_characters": ["林屿", "苏晚"],
                                    "mid_frame_characters": [],
                                    "end_frame_characters": ["林屿", "苏晚"],
                                    "narration": "",
                                    "dialogue_lines": [],
                                    "subtitle_lines": [],
                                    "timed_beats": [
                                        "0-3秒：承接上一拍，两人继续保持更近的站位。",
                                        "3-6秒：气氛停在短暂屏息里，准备进入下一拍开口。",
                                    ],
                                    "duration_seconds": 6,
                                    "requires_mid_frame": False,
                                    "transition_hint": "continue",
                                    "shot_state": {
                                        "framing": "双人中近景",
                                        "camera_motion": "轻微停顿后稳住",
                                        "blocking": "两人保持更近的面对面站位",
                                        "action_progression": "继续保持停住后的屏息等待",
                                        "emotion_progression": "紧张停在即将开口前",
                                        "screen_direction": "保持面对面轴线",
                                        "end_state_lock": "两人仍停在更近距离里。",
                                    },
                                    "continuity_link": {
                                        "previous_segment_id": "ch01-sc03-seg04a",
                                        "transition_mode": "continue",
                                        "opening_match": "承接上一段尾部，两人刚在更近距离停住。",
                                        "carry_over_elements": ["更近距离站位"],
                                        "allowed_changes": "继续停在屏息等待里。",
                                        "transition_reason": "同一 chunk 内继续推进。",
                                    },
                                },
                            ],
                        }
                    return {
                        "scene_id": "ch01-sc03",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc03-seg04a1",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc03",
                                "title": "迈近一步",
                                "summary": "林屿先向苏晚迈近一步，完成距离推进。",
                                "involved_characters": ["林屿", "苏晚"],
                                "start_frame_characters": ["林屿", "苏晚"],
                                "mid_frame_characters": [],
                                "end_frame_characters": ["林屿", "苏晚"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-3秒：林屿向苏晚迈近一步，距离明显缩短。",
                                    "3-5秒：苏晚没有躲开，视线仍留在他脸上。",
                                ],
                                "duration_seconds": 5,
                                "requires_mid_frame": False,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中景",
                                    "camera_motion": "轻微前推",
                                    "blocking": "两人从相隔半步推进到更近距离",
                                    "action_progression": "先完成靠近，再停住看向彼此",
                                    "emotion_progression": "试探开始升温",
                                    "screen_direction": "保持面对面轴线",
                                    "end_state_lock": "两人已经进入更近距离站位。",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "两人已经面向彼此站住，林屿先迈近一步。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "从原站位推进到更近距离。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            },
                            {
                                "segment_id": "ch01-sc03-seg04a2",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc03",
                                "title": "抬眼停住",
                                "summary": "苏晚抬眼看向林屿，两人同时停住，气氛收紧。",
                                "involved_characters": ["林屿", "苏晚"],
                                "start_frame_characters": ["林屿", "苏晚"],
                                "mid_frame_characters": [],
                                "end_frame_characters": ["林屿", "苏晚"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-3秒：承接上一拍，苏晚抬眼迎向林屿的目光。",
                                    "3-6秒：两人同时停住，气氛停在短暂屏息里。",
                                ],
                                "duration_seconds": 6,
                                "requires_mid_frame": False,
                                "transition_hint": "continue",
                                "shot_state": {
                                    "framing": "双人中近景",
                                    "camera_motion": "轻微前推后停住",
                                    "blocking": "两人在更近距离里停住，视线对上",
                                    "action_progression": "从抬眼推进到停住屏息",
                                    "emotion_progression": "试探迅速收紧成屏息等待",
                                    "screen_direction": "保持面对面轴线",
                                    "end_state_lock": "两人停在更近距离，等待下一拍开口。",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "ch01-sc03-seg04a1",
                                    "transition_mode": "continue",
                                    "opening_match": "承接上一段尾部，两人已经处在更近距离里。",
                                    "carry_over_elements": ["更近距离站位"],
                                    "allowed_changes": "从抬眼推进到停住屏息。",
                                    "transition_reason": "同一 chunk 内继续推进。",
                                },
                            },
                            {
                                "segment_id": "ch01-sc03-seg04b",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc03",
                                "title": "停在屏息",
                                "summary": "两人停在更近距离，等待下一拍开口。",
                                "involved_characters": ["林屿", "苏晚"],
                                "start_frame_characters": ["林屿", "苏晚"],
                                "mid_frame_characters": [],
                                "end_frame_characters": ["林屿", "苏晚"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-3秒：承接上一拍，两人继续保持更近的站位。",
                                    "3-6秒：气氛停在短暂屏息里，准备进入下一拍开口。",
                                ],
                                "duration_seconds": 6,
                                "requires_mid_frame": False,
                                "transition_hint": "continue",
                                "shot_state": {
                                    "framing": "双人中近景",
                                    "camera_motion": "轻微停顿后稳住",
                                    "blocking": "两人保持更近的面对面站位",
                                    "action_progression": "继续保持停住后的屏息等待",
                                    "emotion_progression": "紧张停在即将开口前",
                                    "screen_direction": "保持面对面轴线",
                                    "end_state_lock": "两人仍停在更近距离里。",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "ch01-sc03-seg04a2",
                                    "transition_mode": "continue",
                                    "opening_match": "承接上一段尾部，两人刚在更近距离停住。",
                                    "carry_over_elements": ["更近距离站位"],
                                    "allowed_changes": "继续停在屏息等待里。",
                                    "transition_reason": "同一 chunk 内继续推进。",
                                },
                            },
                        ],
                    }
                return {
                    "scene_id": "ch01-sc03",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc03-seg04",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc03",
                            "title": "全塞一起",
                            "summary": "靠近、抬眼、停住屏息都塞在一个片段里。",
                            "involved_characters": ["林屿", "苏晚"],
                            "start_frame_characters": ["林屿", "苏晚"],
                            "mid_frame_characters": [],
                            "end_frame_characters": ["林屿", "苏晚"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "timed_beats": [
                                "0-3秒：林屿向苏晚迈近一步，然后苏晚抬眼看向他。",
                                "3-6秒：两人同时停住，气氛继续收紧。",
                            ],
                            "duration_seconds": 6,
                            "requires_mid_frame": False,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "双人中景",
                                "camera_motion": "轻微前推后停住",
                                "blocking": "两人从相隔半步推进到更近距离停住",
                                "action_progression": "靠近、抬眼、停住全塞在同一段",
                                "emotion_progression": "试探迅速收紧",
                                "screen_direction": "保持面对面轴线",
                                "end_state_lock": "两人停在更近距离里，准备进入下一拍。",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "两人已经面向彼此站住。",
                                "carry_over_elements": [],
                                "allowed_changes": "把靠近、抬眼和停住都塞进一个片段。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-action-repair-iterative",
        )
        backend = IterativeActionRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-action-repair-iterative-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc03",
                "chapter_number": 1,
                "title": "花架靠近",
                "summary": "林屿和苏晚在花架下从靠近推进到停住屏息。",
                "scene_anchor": "花架下，傍晚，暖色侧光",
                "involved_characters": ["林屿", "苏晚"],
                "scene_bible": {
                    "location": "花架小径",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "花藤绿"],
                    "background_anchors": ["花架", "石板路", "树影"],
                    "fixed_props": [],
                    "spatial_layout": "两人停在花架下的石板路中央，面对面站立",
                    "character_blocking": "先靠近，再抬眼停住，最后停在屏息等待里",
                    "continuity_notes": "保持花架、石板路和两人面对面站位稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc03-chunk02",
                "order_index": 2,
                "title": "靠近停住",
                "summary": "从主动靠近推进到短暂屏息。",
                "must_cover": ["主动靠近", "停在屏息"],
                "transition_goal": "气氛收紧到即将开口前。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 10)
        self.assertEqual(backend.action_repair_calls, 7)
        self.assertEqual(len(result.segments), 3)
        self.assertEqual(
            backend.requests[-1].metadata.get("task"),
            "video-scene-segment-action-repair",
        )
        self.assertEqual(
            backend.requests[-1].metadata.get("offending_segment_id"),
            "ch01-sc03-seg04a",
        )
        self.assertIn("上一轮失败 batch JSON", backend.requests[-1].user_prompt)
        self.assertIn("ch01-sc03-seg04a", backend.requests[-1].user_prompt)
        self.assertIn("当前约有 3 个推进点", backend.requests[-1].user_prompt)

    def test_scene_chunk_contract_batch_normalizes_focus_conflict_without_extra_repair(self) -> None:
        class FocusRepairBackend:
            def __init__(self) -> None:
                self.calls = 0
                self.requests: list[PromptRequest] = []

            def generate(self, request: PromptRequest):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request: PromptRequest, schema):
                self.calls += 1
                self.requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-focus-repair":
                    return {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg05",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "title": "长椅旁的停顿",
                                "summary": "林屿和苏晚在长椅旁停下，气氛进入短暂屏息。",
                                "involved_characters": ["林屿", "苏晚"],
                                "start_frame_characters": ["林屿", "苏晚"],
                                "mid_frame_characters": [],
                                "end_frame_characters": ["林屿", "苏晚"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "timed_beats": [
                                    "0-3秒：林屿和苏晚在长椅旁同时停住，互相看向对方。",
                                    "3-6秒：镜头轻微前推，保持两人同框，气氛停在即将开口前的屏息状态。",
                                ],
                                "duration_seconds": 6,
                                "requires_mid_frame": False,
                                "transition_hint": "auto",
                                "shot_state": {
                                    "framing": "双人中近景，保持林屿和苏晚同框。",
                                    "camera_motion": "轻微前推，保持林屿、苏晚同框，只通过站位和表情差异突出林屿的紧张。",
                                    "blocking": "两人停在长椅旁，站位不分离。",
                                    "action_progression": "从停步推进到短暂对视，再停在准备开口前。",
                                    "emotion_progression": "平静迅速收紧成屏息等待。",
                                    "screen_direction": "保持两人面对面的稳定轴线。",
                                    "end_state_lock": "两人仍停在彼此面前，准备进入下一拍开口。",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "林屿和苏晚已经在长椅旁停住，视线落到彼此身上。",
                                    "carry_over_elements": [],
                                    "allowed_changes": "从停步推进到短暂对视与屏息等待。",
                                    "transition_reason": "当前 chunk 的起始段。",
                                },
                            }
                        ],
                    }
                return {
                    "scene_id": "ch01-sc01",
                    "chapter_number": 1,
                    "segments": [
                        {
                            "segment_id": "ch01-sc01-seg05",
                            "chapter_number": 1,
                            "scene_id": "ch01-sc01",
                            "title": "长椅旁的停顿",
                            "summary": "林屿和苏晚在长椅旁停下。",
                            "involved_characters": ["林屿", "苏晚"],
                            "start_frame_characters": ["林屿", "苏晚"],
                            "mid_frame_characters": [],
                            "end_frame_characters": ["林屿", "苏晚"],
                            "narration": "",
                            "dialogue_lines": [],
                            "subtitle_lines": [],
                            "timed_beats": [
                                "0-3秒：林屿和苏晚在长椅旁同时停住。",
                                "3-6秒：两人继续停在原地，准备开口。",
                            ],
                            "duration_seconds": 6,
                            "requires_mid_frame": False,
                            "transition_hint": "auto",
                            "shot_state": {
                                "framing": "林屿单人近景，苏晚仍在他身旁。",
                                "camera_motion": "轻微前推，推向林屿侧脸特写。",
                                "blocking": "两人停在长椅旁，站位不分离。",
                                "action_progression": "从停步推进到准备开口。",
                                "emotion_progression": "平静迅速收紧成紧张。",
                                "screen_direction": "保持两人面对面的稳定轴线。",
                                "end_state_lock": "两人仍停在彼此面前，准备进入下一拍开口。",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": "林屿和苏晚已经在长椅旁停住。",
                                "carry_over_elements": [],
                                "allowed_changes": "从停步推进到准备开口。",
                                "transition_reason": "当前 chunk 的起始段。",
                            },
                        }
                    ],
                }

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunk-focus-repair",
        )
        backend = FocusRepairBackend()
        service = NovelToVideoService(
            backend=backend,
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunk-focus-repair-memory"),
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "长椅停步",
                "summary": "林屿和苏晚在长椅旁停下，准备进入下一拍开口。",
                "scene_anchor": "长椅旁，傍晚，暖色侧光",
                "involved_characters": ["林屿", "苏晚"],
                "scene_bible": {
                    "location": "长椅旁",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "dominant_palette": ["暖橙", "浅蓝"],
                    "background_anchors": ["长椅", "树影", "石板路"],
                    "fixed_props": [],
                    "spatial_layout": "长椅靠近石板路，两人停在长椅前面对面站立",
                    "character_blocking": "两人停步后面对面站住，准备开口",
                    "continuity_notes": "保持长椅、树影和两人站位稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc01-ch03",
                "order_index": 3,
                "title": "停步屏息",
                "summary": "两人停下后进入短暂屏息，准备开口。",
                "must_cover": ["停步对视"],
                "transition_goal": "气氛收紧到即将开口前。",
                "expected_segment_count": 1,
            }
        )

        result = service._build_scene_chunk_contract_batch(
            novel_package=story_result.novel_package,
            story_memory=story_memory,
            chapter_number=1,
            scene=scene,
            chunk=chunk,
            previous_chunk_exit_state={},
            previous_tail_segment=None,
        )

        self.assertEqual(backend.calls, 1)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(
            backend.requests[-1].metadata.get("task"),
            "video-scene-segment-planner",
        )
        self.assertEqual(
            result.segments[0].shot_state.framing,
            "多人同框中景关系镜头，保持 林屿、苏晚 同框，完整交代角色相对位置。",
        )
        self.assertEqual(
            result.segments[0].shot_state.camera_motion,
            "镜头轻微推进或稳定跟随，保持 林屿、苏晚 多人同框；只通过站位、视线和表情差异突出主要情绪。",
        )

    def test_build_subtitle_lines_does_not_fallback_to_timed_beats(self) -> None:
        service = NovelToVideoService()

        self.assertEqual(
            service._build_subtitle_lines(
                narration="",
                dialogue_lines=[],
                timed_beats=["0-5秒：他只是转身看向湖面。"],
            ),
            [],
        )

    def test_scene_chunk_contract_output_requires_cross_chunk_first_segment_to_continue_or_cut(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖等待",
                "summary": "陈默等待后与林晚会面。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "lighting": "暖金色侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "meet",
                "order_index": 2,
                "title": "正式会面",
                "summary": "等待之后正式会面。",
                "must_cover": ["会面"],
                "transition_goal": "两人开始对话。",
                "expected_segment_count": 1,
            }
        )
        previous_tail_segment = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并听见脚步声",
                            "end_state_lock": "陈默听见脚步声后微微回头，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已站在镜湖长椅旁等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待的开场基线。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        ).segments[0]
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "会面",
                        "summary": "林晚走近后，两人正式会面。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "林晚走近后，两人正式会面。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林晚走近后，两人正式会面。"],
                        "timed_beats": ["0-6秒：林晚走近后，两人正式会面。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "从等待推进到会面",
                            "end_state_lock": "两人面对面站定",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默仍在长椅旁回头。",
                            "carry_over_elements": [],
                            "allowed_changes": "林晚入镜，两人正式会面。",
                            "transition_reason": "错误地把跨 chunk 首段写成重新开场。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "只能是 continue 或 cut"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
                previous_tail_segment=previous_tail_segment,
            )

    def test_scene_chunk_contract_output_allows_cross_chunk_first_segment_to_continue(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖等待",
                "summary": "陈默等待后与林晚会面。",
                "scene_anchor": "镜湖长椅，傍晚",
                "involved_characters": ["陈默", "林晚"],
                "scene_bible": {
                    "location": "镜湖长椅",
                    "time_window": "傍晚",
                    "lighting": "暖金色侧光",
                    "background_anchors": ["镜湖", "长椅"],
                    "spatial_layout": "长椅靠湖，步道从右侧延伸",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "meet",
                "order_index": 2,
                "title": "正式会面",
                "summary": "等待之后正式会面。",
                "must_cover": ["会面"],
                "transition_goal": "两人开始对话。",
                "expected_segment_count": 1,
            }
        )
        previous_tail_segment = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "等待并听见脚步声",
                            "end_state_lock": "陈默听见脚步声后微微回头，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已站在镜湖长椅旁等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待的开场基线。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        ).segments[0]
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "会面",
                        "summary": "林晚走近后，两人正式会面。",
                        "involved_characters": ["陈默", "林晚"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": ["陈默", "林晚"],
                        "end_frame_characters": ["陈默", "林晚"],
                        "narration": "林晚走近后，两人正式会面。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林晚走近后，两人正式会面。"],
                        "timed_beats": ["0-6秒：林晚走近后，两人正式会面。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "continue",
                        "shot_state": {
                            "action_progression": "从等待推进到会面",
                            "end_state_lock": "两人面对面站定",
                        },
                        "continuity_link": {
                            "previous_segment_id": "ch01-sc01-seg01",
                            "transition_mode": "continue",
                            "opening_match": "陈默仍在长椅旁微微回头，保持上一段听见脚步声后停住的姿态。",
                            "carry_over_elements": ["镜湖长椅", "陈默站位", "右向视线"],
                            "allowed_changes": "林晚入镜，两人从等待推进到正式会面。",
                            "transition_reason": "跨 chunk 承接后推进到正式会面。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_chunk_contract_output(
            contracts,
            scene=scene,
            chunk=chunk,
            previous_tail_segment=previous_tail_segment,
        )

        self.assertEqual(validated.segments[0].continuity_link.transition_mode, "continue")

    def test_build_scene_chunk_exit_state_includes_opening_match_seed(self) -> None:
        service = NovelToVideoService()
        tail_segment = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": ["陈默"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "blocking": "陈默停在镜湖长椅旁，肩膀微微绷紧",
                            "action_progression": "等待并听见脚步声",
                            "prop_continuity": "书包仍在肩侧",
                            "screen_direction": "向右前方回头",
                            "end_state_lock": "陈默听见脚步声后微微回头，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "陈默已站在镜湖长椅旁等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立等待的开场基线。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        ).segments[0]

        exit_state = service._build_scene_chunk_exit_state(tail_segment)

        self.assertEqual(exit_state["visible_tail_state"], "陈默听见脚步声后微微回头，动作停住")
        self.assertIn("角色：陈默", exit_state["carry_over_elements"])
        self.assertIn("朝向：向右前方回头", exit_state["carry_over_elements"])
        self.assertIn("道具：书包仍在肩侧", exit_state["carry_over_elements"])
        self.assertIn("陈默听见脚步声后微微回头，动作停住", exit_state["opening_match_seed"])

    def test_scene_chunk_contract_output_rejects_duplicate_adjacent_segments(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "玫瑰园入口",
                "summary": "主角在玫瑰园入口等待后停步赏花。",
                "scene_anchor": "玫瑰园入口，傍晚",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "校园玫瑰园入口",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["玫瑰花架", "石径"],
                    "fixed_props": ["花瓣"],
                    "spatial_layout": "入口石径通向花园内部",
                    "character_blocking": "林辰先停步，随后看向花架",
                    "continuity_notes": "保持入口与花架关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "flower-stop",
                "order_index": 1,
                "title": "停步赏花",
                "summary": "林辰在玫瑰园入口停步赏花。",
                "must_cover": ["停下脚步", "看向花架"],
                "transition_goal": "准备继续往花园内部走",
                "expected_segment_count": 2,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "停步",
                        "summary": "林辰在玫瑰园入口停下脚步赏花。",
                        "involved_characters": ["林辰"],
                        "start_frame_characters": ["林辰"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["林辰"],
                        "narration": "林辰在入口停下脚步，看着花架。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林辰在入口停下脚步，看着花架。"],
                        "timed_beats": ["0-5秒：林辰在入口停下脚步，看着花架。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "action_progression": "停下脚步并看着花架",
                        },
                        "continuity_link": {
                            "transition_mode": "start",
                            "opening_match": "林辰已站在玫瑰园入口，面向花架停下脚步。",
                            "allowed_changes": "停下脚步并看向花架。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    },
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "停步赏花延续",
                        "summary": "林辰停在玫瑰园入口，继续停步赏花，没有继续前进。",
                        "involved_characters": ["林辰"],
                        "start_frame_characters": ["林辰"],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["林辰"],
                        "narration": "林辰仍停在入口看着花架。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林辰仍停在入口看着花架。"],
                        "timed_beats": ["0-5秒：林辰仍停在入口看着花架。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "continue",
                        "shot_state": {
                            "action_progression": "停在原地继续看着花架，没有新的动作推进",
                        },
                        "continuity_link": {
                            "previous_segment_id": "ch01-sc01-seg01",
                            "transition_mode": "continue",
                            "opening_match": "林辰仍停在入口，保持上一段停下脚步看着花架的姿势。",
                            "allowed_changes": "继续保持当前停步赏花状态。",
                            "carry_over_elements": ["站位不变"],
                            "transition_reason": "同一 chunk 内继续停步赏花。",
                        },
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "重复表达同一事件"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
            )

    def test_scene_chunk_contract_output_rejects_segment_action_budget_overload(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "入口等待",
                "summary": "单人等待后准备开口。",
                "scene_anchor": "花园入口，傍晚",
                "involved_characters": ["林辰"],
                "scene_bible": {
                    "location": "花园入口",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["入口拱门", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "入口正对花园内部",
                    "character_blocking": "林辰站在入口处等待",
                    "continuity_notes": "保持入口空间稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "overloaded-segment",
                "order_index": 1,
                "title": "一段塞太多动作",
                "summary": "把等待、回头、整理衣领和开口全塞进一个短段。",
                "must_cover": ["等待", "回头", "开口"],
                "transition_goal": "站定后准备继续推进。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "全塞一段",
                        "summary": "林辰在短时间里连续完成多次动作变化。",
                        "involved_characters": ["林辰"],
                        "start_frame_characters": ["林辰"],
                        "mid_frame_characters": ["林辰"],
                        "end_frame_characters": ["林辰"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-2秒：林辰站在入口等待。",
                            "2-4秒：他回头看向路口并整理衣领。",
                            "4-6秒：他深呼吸后终于开口。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "单人中景",
                            "camera_motion": "轻微前推",
                            "blocking": "林辰站在入口处",
                            "action_progression": "从等待推进到回头、整理衣领和开口",
                            "emotion_progression": "紧张逐渐抬升",
                            "prop_continuity": "信封在手中",
                            "screen_direction": "保持朝向入口内侧",
                            "end_state_lock": "林辰开口后仍停在入口处",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "林辰已站在花园入口等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "从等待推进到回头、整理衣领和开口。",
                            "transition_reason": "当前 chunk 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaises(SegmentActionSplitRequiredError):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
            )

    def test_scene_chunk_output_rejects_duplicate_adjacent_chunks(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "玫瑰园入口",
                "summary": "林辰与苏晴走到玫瑰园入口并短暂停步。",
                "scene_anchor": "玫瑰园入口，傍晚",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "校园玫瑰园入口",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["玫瑰花架", "石径"],
                    "fixed_props": ["花瓣"],
                    "spatial_layout": "入口石径通向花园内部",
                    "character_blocking": "两人停步后再继续前进",
                    "continuity_notes": "保持入口石径和花架方向稳定",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "flower-stop-1",
                        "order_index": 1,
                        "title": "停步赏花",
                        "summary": "林辰在玫瑰园入口停下脚步赏花。",
                        "must_cover": ["停下脚步", "看向花架"],
                        "transition_goal": "准备继续前进。",
                        "expected_segment_count": 1,
                    },
                    {
                        "chunk_id": "flower-stop-2",
                        "order_index": 2,
                        "title": "停步赏花延续",
                        "summary": "林辰停在玫瑰园入口，继续停步赏花，没有继续前进。",
                        "must_cover": ["停下脚步", "继续看向花架"],
                        "transition_goal": "继续保持停步赏花状态。",
                        "expected_segment_count": 1,
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "重复表达同一事件"):
            service._validate_scene_segment_chunk_output(
                chunk_plan,
                scene=scene,
            )

    def test_scene_chunk_output_rejects_action_overloaded_chunk(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园长椅前",
                "summary": "两人在长椅前从试探推进到关系确认。",
                "scene_anchor": "花园长椅，傍晚",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "花园长椅前",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["长椅", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，人物面对面站立",
                    "character_blocking": "两人从试探到确认逐步靠近",
                    "continuity_notes": "保持长椅和石板路关系稳定",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "confession-all-in-one",
                        "order_index": 1,
                        "title": "整轮告白都塞在一起",
                        "summary": "从试探开口一路推进到明确回应和关系落点。",
                        "must_cover": ["试探开口", "正式告白", "明确回应"],
                        "transition_goal": "两人停在新的关系确认状态里。",
                        "expected_segment_count": 1,
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "动作容量过载"):
            service._validate_scene_segment_chunk_output(
                chunk_plan,
                scene=scene,
            )

    def test_scene_chunk_output_rejects_excessive_total_expected_segments(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "长场景",
                "summary": "两人在校园内从相遇走到告白前。",
                "scene_anchor": "校园黄昏步道",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "校园黄昏步道",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "夕阳侧光",
                    "dominant_palette": ["暖金", "深蓝"],
                    "background_anchors": ["树影", "步道", "路灯"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "步道逐步通往花园",
                    "character_blocking": "两人边走边交流",
                    "continuity_notes": "保持步道方向稳定",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "walk-1",
                        "order_index": 1,
                        "title": "起步",
                        "summary": "两人从教学楼前走出。",
                        "must_cover": ["走出教学楼"],
                        "transition_goal": "进入步道。",
                        "expected_segment_count": 3,
                    },
                    {
                        "chunk_id": "walk-2",
                        "order_index": 2,
                        "title": "并肩",
                        "summary": "两人沿步道并肩前进。",
                        "must_cover": ["并肩前进"],
                        "transition_goal": "靠近花园。",
                        "expected_segment_count": 3,
                    },
                    {
                        "chunk_id": "walk-3",
                        "order_index": 3,
                        "title": "放慢",
                        "summary": "两人在树影下放慢脚步。",
                        "must_cover": ["放慢脚步"],
                        "transition_goal": "停在花园前。",
                        "expected_segment_count": 3,
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "超过 scene 上限"):
            service._validate_scene_segment_chunk_output(
                chunk_plan,
                scene=scene,
            )

    def test_materialize_scene_segment_does_not_fallback_single_character_frames(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="单人等待",
            idea="一个人在镜湖边等待。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=800,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "single-frame-strict",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖边等待",
                "summary": "主角在镜湖边等待。",
                "scene_anchor": "镜湖边长椅，傍晚",
                "involved_characters": ["陈默"],
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["镜湖", "长椅"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖",
                    "character_blocking": "单人等待",
                    "continuity_notes": "保持镜湖与长椅关系稳定",
                },
            }
        )
        contract = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "陈默在镜湖边等待。",
                        "involved_characters": ["陈默"],
                        "start_frame_characters": [],
                        "mid_frame_characters": [],
                        "end_frame_characters": ["陈默"],
                        "narration": "陈默在镜湖边等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["陈默在镜湖边等待。"],
                        "timed_beats": ["0-5秒：陈默在镜湖边等待。"],
                        "duration_seconds": 5,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                    }
                ],
            }
        ).segments[0]

        with self.assertRaisesRegex(ValueError, "start_frame_characters 不能为空"):
            service._materialize_scene_segment(
                novel_package=story_result.novel_package,
                scene=scene,
                contract=contract,
            )

    def test_scene_segment_contract_output_requires_explicit_mid_frame_fields_when_effectively_needed(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "mid-frame-contract-inference",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        first_character, second_character = self._ensure_two_outline_characters(story_result)
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花廊会面",
                "summary": "主角在花廊等待后与对方正式会面。",
                "scene_anchor": "紫藤花廊，傍晚",
                "involved_characters": [first_character.name, second_character.name],
                "scene_bible": {
                    "location": "校园紫藤花廊",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["紫藤花架", "小径"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "花廊入口连接校园小径",
                    "character_blocking": "先单人等待，再双人面对面站定",
                    "continuity_notes": "保持花廊与小径方向稳定",
                },
            }
        )
        contract = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "花廊等待与会面",
                        "summary": f"{first_character.name}等待片刻后，与{second_character.name}正式会面。",
                        "involved_characters": [first_character.name, second_character.name],
                        "start_frame_characters": [first_character.name],
                        "mid_frame_characters": [],
                        "end_frame_characters": [first_character.name, second_character.name],
                        "narration": "他等到对方走近，终于站定面对面。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["他等到对方走近，终于站定面对面。"],
                        "timed_beats": [
                            f"0-4秒：{first_character.name}独自在花廊下等待。",
                            f"4-9秒：{first_character.name}伸手示意，{second_character.name}停下脚步，与他面对面站定。",
                        ],
                        "duration_seconds": 9,
                        "requires_mid_frame": False,
                        "transition_hint": "continue",
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": f"{first_character.name}已独自在花廊下站定等待。",
                            "carry_over_elements": [],
                            "allowed_changes": f"{second_character.name}入镜，关系推进到正式会面。",
                            "transition_reason": "当前 scene 的起始段。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires_mid_frame 必须为 true，且必须显式给出 mid_frame_characters",
        ):
            service._validate_scene_segment_contract_output(
                contract,
                scene=scene,
            )

    def test_scene_segment_contract_output_allows_short_two_character_segment_without_mid_frame(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "mid-frame-short-two-character",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        first_character, second_character = self._ensure_two_outline_characters(story_result)
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花廊短会面",
                "summary": "两人在花廊入口短暂停下并对视。",
                "scene_anchor": "紫藤花廊入口，傍晚",
                "involved_characters": [first_character.name, second_character.name],
                "scene_bible": {
                    "location": "校园紫藤花廊入口",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["紫藤花架", "入口小径"],
                    "fixed_props": ["长椅"],
                    "spatial_layout": "花廊入口连接校园小径",
                    "character_blocking": "两人在入口短暂停下并面对面站定",
                    "continuity_notes": "保持花廊入口与小径方向稳定",
                },
            }
        )
        contract = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "花廊入口短会面",
                        "summary": f"{first_character.name}和{second_character.name}在花廊入口短暂停下并对视。",
                        "involved_characters": [first_character.name, second_character.name],
                        "start_frame_characters": [first_character.name],
                        "mid_frame_characters": [],
                        "end_frame_characters": [first_character.name, second_character.name],
                        "narration": "两人在花廊入口短暂停下，对视片刻。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["两人在花廊入口短暂停下，对视片刻。"],
                        "timed_beats": [
                            f"0-3秒：{first_character.name}先在花廊入口停下。",
                            f"3-6秒：{second_character.name}走近后，两人短暂停下并对视。",
                        ],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "transition_hint": "continue",
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": f"{first_character.name}已站在花廊入口等待。",
                            "carry_over_elements": [],
                            "allowed_changes": f"{second_character.name}走近后，两人短暂停下并对视。",
                            "transition_reason": "当前 scene 的起始段。",
                        },
                    }
                ],
            }
        )

        validated = service._validate_scene_segment_contract_output(
            contract,
            scene=scene,
        )

        self.assertFalse(validated.segments[0].requires_mid_frame)
        self.assertEqual(validated.segments[0].mid_frame_characters, [])

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
        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
        roster = self.novel_builder.build_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "characters": [
                    self.novel_builder.build_character_roster(
                        brief,
                        architecture,
                        cast_analysis=cast_analysis,
                    ).characters[0].model_copy(
                        update={"name": "程野", "gender": "男", "image_prompt": "程野，男，高中生。"}
                    ),
                    self.novel_builder.build_character_roster(
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
        cast_analysis = self.novel_builder.build_cast_analysis(
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
        self.assertIn("固定索引合同", prompt)
        self.assertIn("characters[0].cast_slot_id", prompt)
        self.assertIn("characters[1].cast_slot_id", prompt)

    def test_dual_lead_repair_does_not_synthesize_missing_second_character(self) -> None:
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
        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
        roster = self.novel_builder.build_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "characters": [
                    self.novel_builder.build_character_roster(
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

        self.assertEqual(len(repaired.characters), 1)
        self.assertEqual(repaired.characters[0].name, "程野")
        self.assertEqual(repaired.characters[0].gender, "男")

    def test_novel_pipeline_uses_compact_prompt_contexts_and_metrics(self) -> None:
        class RecordingBackend(DeterministicStoryBackend):
            def __init__(self) -> None:
                super().__init__()
                self.requests: list[PromptRequest] = []

            def generate_structured(self, request: PromptRequest, schema):
                self.requests.append(request)
                return super().generate_structured(request, schema)

        backend = RecordingBackend()
        service = NovelGeneratorService(backend=backend)
        brief = StoryBrief(
            title_hint="镜湖告白",
            idea="毕业前夕，一个男生准备在镜湖边对喜欢的人告白。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=3,
            total_word_target=2400,
            must_include=["告白", "镜湖"],
            style_keywords=["晚风", "灯光", "湖面倒影"],
        )

        story_source = service.build_story_source(brief)
        service.build_novel_package_from_story_source(story_source)

        requests_by_task = {
            str(request.metadata.get("task", "")).strip(): request
            for request in backend.requests
        }
        cast_request = requests_by_task["cast-analyzer"]
        character_request = requests_by_task["character-designer"]
        chapter_request = requests_by_task["chapter-planner"]

        for request in (cast_request, character_request, chapter_request):
            self.assertGreater(request.metadata.get("total_prompt_chars", 0), 0)
            self.assertEqual(
                request.metadata["total_prompt_chars"],
                request.metadata["system_prompt_chars"] + request.metadata["user_prompt_chars"],
            )
            self.assertEqual(
                request.metadata["prompt_soft_limit_chars"],
                service.PROMPT_WARNING_THRESHOLD_CHARS,
            )

        self.assertIn("项目底稿：", cast_request.user_prompt)
        self.assertIn("- 前提：", cast_request.user_prompt)
        self.assertNotIn('{"title":', cast_request.user_prompt)
        self.assertNotIn('"visual_motifs"', cast_request.user_prompt)
        self.assertIn("角色阵容：", chapter_request.user_prompt)
        self.assertNotIn('{"characters"', chapter_request.user_prompt)
        self.assertNotIn('"voice_profile"', chapter_request.user_prompt)
        self.assertTrue(cast_request.metadata["total_prompt_chars"] < 4200)
        self.assertTrue(character_request.metadata["total_prompt_chars"] < 5200)
        self.assertTrue(chapter_request.metadata["total_prompt_chars"] < 4200)

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
        cast_analysis = self.novel_builder.build_cast_analysis(
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

    def test_dual_lead_chapter_repair_does_not_append_missing_counterpart(self) -> None:
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
        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
        roster = self.novel_builder.build_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )
        chapter_plan_set = self.novel_builder.build_chapter_plan_set(
            brief,
            roster,
            cast_analysis=cast_analysis,
        ).model_copy(
            update={
                "chapters": [
                    self.novel_builder.build_chapter_plan_set(
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
            repaired.chapters[0].featured_characters,
            [roster.characters[0].name],
        )

    def test_repair_chapter_plan_set_no_longer_appends_missing_chapters(self) -> None:
        service = NovelGeneratorService()
        brief = StoryBrief(
            title_hint="雨夜告白",
            idea="一个女生终于在雨夜向喜欢的男生告白。",
            genre="校园恋爱",
            tone="青春、克制",
            chapter_count=2,
            total_word_target=2400,
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
        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
        roster = self.novel_builder.build_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )
        chapter_plan_set = ChapterPlanSetSchema(
            chapters=[
                self.novel_builder.build_chapter_plan_set(
                    brief,
                    roster,
                    cast_analysis=cast_analysis,
                ).chapters[0]
            ]
        )

        repaired = service._repair_chapter_plan_set(
            chapter_plan_set,
            brief,
            roster,
            cast_analysis=cast_analysis,
        )

        self.assertEqual(len(repaired.chapters), 1)

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
            self.novel_builder.build_cast_analysis(brief, architecture).model_copy(
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

        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)

        self.assertGreaterEqual(cast_analysis.recommended_core_cast_count, 3)
        self.assertLessEqual(cast_analysis.recommended_core_cast_count, len(cast_analysis.slots))
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

    def test_deterministic_cast_analysis_uses_grounded_role_labels(self) -> None:
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

        cast_analysis = self.novel_builder.build_cast_analysis(brief, architecture)
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

    def test_missing_chapters_are_not_silently_backfilled_into_segment_plan(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        visual_bible = build_test_visual_bible(story_result.novel_package)
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
            [item.chapter_number for item in repaired.segments],
            [1],
        )

    def test_scene_segment_contract_prompt_keeps_duration_and_mid_frame_rules(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "segment-contract-prompt",
        )
        story_result.novel_package.chapters[0].markdown = (
            "陈默先到镜湖边长椅旁等林晚。"
            "他一边看着湖面对岸的灯光，一边反复练习开口的话。"
            "林晚沿着步道走近，他终于抬头看向她。"
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "segment-contract-prompt-memory"),
        )
        scene_payload = {
            "scene_id": "ch01-sc01",
            "chapter_number": 1,
            "title": "镜湖等待",
            "summary": "陈默在镜湖边等待林晚走近。",
            "scene_anchor": "镜湖边长椅，对岸亮灯，傍晚微风",
            "involved_characters": ["陈默", "林晚"],
            "scene_bible": {
                "location": "镜湖边长椅",
                "time_window": "傍晚",
                "weather": "微风",
                "lighting": "湖面对岸暖灯亮起",
                "dominant_palette": ["暖橙", "深蓝"],
                "background_anchors": ["镜湖", "长椅", "对岸灯光"],
                "fixed_props": ["书包"],
                "spatial_layout": "长椅靠湖，步道从右后方延伸",
                "character_blocking": "陈默先独自等待，林晚沿步道靠近",
                "continuity_notes": "保持镜湖、长椅与对岸灯光关系稳定",
            },
        }
        chunk_payload = {
            "chunk_id": "chunk-01",
            "order_index": 1,
            "title": "等待与靠近",
            "summary": "陈默等待，林晚逐步靠近。",
            "must_cover": ["陈默等待", "林晚沿步道走近"],
            "transition_goal": "两人即将开始对话",
            "expected_segment_count": 2,
        }

        prompt = service._build_scene_segment_contract_user_prompt(
            story_result.novel_package,
            chapter_number=1,
            story_memory=story_memory,
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
            previous_chunk_exit_state={},
        )

        self.assertIn("当前 chunk 一般拆成 1-3 个 segment", prompt)
        self.assertIn("按中文自然口播语速估算音频长度", prompt)
        self.assertIn("如果旁白、对白或硬字幕超过当前时长可说完的字数，必须拆成下一个片段", prompt)
        self.assertIn("动作容量预算也必须同时满足", prompt)
        self.assertIn("告白、回应、对峙、双人长对话 scene 要优先少段而不是碎段", prompt)
        self.assertIn("不要把“准备开口”和“真正开口”拆成两个近义连续片段", prompt)
        self.assertIn("requires_mid_frame", prompt)
        self.assertIn("mid_frame_characters", prompt)
        self.assertIn("`expected_segment_count` 是上限，不是目标值", prompt)
        self.assertIn("`mid_frame_characters` 必须严格跟随片段中间那一拍真实出镜角色", prompt)
        self.assertIn("如果首尾同组多人在中段仍是连续表演", prompt)
        self.assertIn("非法反例", prompt)
        self.assertIn("`opening_match` 必须写成可拍到的开场画面", prompt)
        self.assertIn("`shot_state.framing` 和 `shot_state.camera_motion` 是整个 segment 共享镜头", prompt)
        self.assertIn("`shot_state.camera_motion=推向林晨侧脸特写`", prompt)
        self.assertIn("保持苏雨、林晨同框", prompt)
        self.assertIn("不要输出 `start_frame_prompt`", prompt)
        self.assertIn("当前 chunk 这次最多只能输出 2 个 segment", prompt)
        self.assertIn("禁止在任何字段写工程注记或制作标签", prompt)
        self.assertIn("`subtitle_lines` 只允许写本段真正会被听到的对白或旁白", prompt)
        self.assertIn("`timed_beats` 就必须把口播落到具体时间段里", prompt)
        self.assertIn("不要写 `4-8秒：陈默终于告白。`", prompt)
        self.assertIn("最后一个 segment 必须真正落到这个结果", prompt)
        self.assertIn(
            "最后一个 segment 的最后一条 `timed_beats` 与 `shot_state.end_state_lock` 必须写成这个结果已经发生",
            prompt,
        )
        self.assertNotIn("推荐最少片段数", prompt)

    def test_scene_segment_contract_prompt_requires_chunk_opening_match_seed(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "segment-contract-cross-chunk-prompt",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "segment-contract-cross-chunk-memory"),
        )
        scene_payload = {
            "scene_id": "ch01-sc01",
            "chapter_number": 1,
            "title": "镜湖等待",
            "summary": "陈默在镜湖边等待林晚走近。",
            "scene_anchor": "镜湖边长椅，对岸亮灯，傍晚微风",
            "involved_characters": ["陈默", "林晚"],
            "scene_bible": {
                "location": "镜湖边长椅",
                "time_window": "傍晚",
                "weather": "微风",
                "lighting": "湖面对岸暖灯亮起",
                "dominant_palette": ["暖橙", "深蓝"],
                "background_anchors": ["镜湖", "长椅", "对岸灯光"],
                "fixed_props": ["书包"],
                "spatial_layout": "长椅靠湖，步道从右后方延伸",
                "character_blocking": "陈默先独自等待，林晚沿步道靠近",
                "continuity_notes": "保持镜湖、长椅与对岸灯光关系稳定",
            },
        }
        chunk_payload = {
            "chunk_id": "chunk-02",
            "order_index": 2,
            "title": "正式会面",
            "summary": "陈默听见脚步声后回头，与林晚正式会面。",
            "must_cover": ["回头承接", "正式会面"],
            "transition_goal": "两人进入对话。",
            "expected_segment_count": 1,
        }
        previous_chunk_exit_state = {
            "segment_id": "ch01-sc01-seg01",
            "visible_tail_state": "陈默听见脚步声后微微回头，动作停住",
            "opening_match_seed": "陈默听见脚步声后微微回头，动作停住；保持角色：陈默，朝向：右前方，道具：书包仍在肩侧",
            "carry_over_elements": ["角色：陈默", "朝向：右前方", "道具：书包仍在肩侧"],
        }

        prompt = service._build_scene_segment_contract_user_prompt(
            story_result.novel_package,
            chapter_number=1,
            story_memory=story_memory,
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
            previous_chunk_exit_state=previous_chunk_exit_state,
        )

        self.assertIn("`visible_tail_state` / `opening_match_seed`", prompt)
        self.assertIn("承接上一 chunk 尾部，角色A仍", prompt)
        self.assertIn("opening_match_seed", prompt)
        self.assertIn("陈默听见脚步声后微微回头，动作停住", prompt)

    def test_segment_continuity_repair_prompt_requires_putting_spoken_lines_into_timed_beats(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "segment-repair-prompt",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        character_profiles = service._build_character_profiles(visual_bible)

        prompt = service._build_segment_continuity_repair_user_prompt(
            story_title=story_result.novel_package.outline.title,
            character_profiles=character_profiles,
            scene_payload={
                "scene_id": "ch01-sc01",
                "title": "镜湖告白",
            },
            segment_payload={
                "segment_id": "ch01-sc01-seg01",
                "scene_id": "ch01-sc01",
                "scene_title": "镜湖告白",
                "scene_summary": "两人准备开口。",
                "scene_anchor": "镜湖边",
                "involved_characters": ["陈默", "林晚"],
                "dialogue_lines": ["陈默：我喜欢你很久了。"],
                "narration": "",
                "subtitle_lines": ["我喜欢你很久了。"],
                "timed_beats": ["0-6秒：陈默终于开口。"],
            },
            previous_segment_payload=None,
            next_segment_payload=None,
            continuity_issues=[
                {
                    "code": "spoken_timing_weak",
                    "message": "timed_beats 没有写明哪一秒谁说了哪句。",
                }
            ],
            speech_budget_context={
                "current_duration_seconds": 6,
                "required_duration_seconds": 5,
                "max_duration_seconds": 12,
                "speech_chars_per_second": 3,
            },
        )

        self.assertIn("如果本段存在 `dialogue_lines` 或 `narration`", prompt)
        self.assertIn("`timed_beats` 必须直接写出哪一秒谁说了哪句", prompt)
        self.assertIn("优先把真实口播句子准确挂回 `timed_beats`", prompt)

    def test_character_sheet_prompt_uses_gender_appearance_and_outfit_only(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
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
                        "name": "林晨",
                        "role": "学生会主席",
                        "gender": "男",
                        "appearance": "20岁男大学生，黑发，清瘦挺拔，气质克制干净",
                        "outfit": "白色衬衫，深色长裤，白色板鞋",
                        "color_palette": ["白色", "深蓝"],
                        "portrait_prompt": "站在图书馆前，电影海报式构图，学生会主席气质。",
                    }
                ]
            }
        )

        character_profiles = service._build_character_profiles(visual_bible)
        prompt = character_profiles[0].portrait_prompt

        self.assertIn("画面唯一可见文字：林晨。", prompt)
        self.assertIn("内部造型约束：性别 男", prompt)
        self.assertIn("不写进画面", prompt)
        self.assertIn("外观：20岁男大学生，黑发，清瘦挺拔，气质克制干净。", prompt)
        self.assertIn("服装：白色衬衫，深色长裤，白色板鞋。", prompt)
        self.assertIn("只画同一角色的正面、左侧面、背面", prompt)
        self.assertNotIn("补充人物描述", prompt)
        self.assertNotIn("内部理解参考", prompt)
        self.assertNotIn("学生会主席", prompt)
        self.assertNotIn("站在图书馆前", prompt)

    def test_scene_chunk_planner_prompt_blocks_scene_replay_and_makes_expected_count_hard_limit(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "scene-chunk-prompt",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "scene-chunk-prompt-memory"),
        )
        scene_payload = {
            "scene_id": "ch01-sc02",
            "chapter_number": 1,
            "title": "离开图书馆后前往镜湖",
            "summary": "两人离开图书馆后继续向镜湖走去，不再重演门口等待和相遇。",
            "scene_anchor": "教学楼外步道 / 傍晚 / 离开图书馆后",
            "involved_characters": ["陈默", "林晚"],
            "covered_event_summaries": [
                "两人离开图书馆，继续沿教学楼外步道前行。",
                "两人逐渐走入镜湖步道，不再回到图书馆门口等待阶段。",
            ],
            "scene_bible": {
                "location": "教学楼外步道",
                "time_window": "傍晚",
                "weather": "微风",
                "lighting": "夕阳侧光",
                "dominant_palette": ["暖橙", "深蓝"],
                "background_anchors": ["教学楼外墙", "林荫步道"],
                "fixed_props": ["书包"],
                "spatial_layout": "两人沿步道从图书馆方向继续向前",
                "character_blocking": "陈默在前半步，林晚在后侧跟上",
                "continuity_notes": "这是上一 scene 汇合后的继续前进，不要回到等待阶段",
            },
        }

        prompt = service._build_scene_chunk_planner_user_prompt(
            story_result.novel_package,
            chapter_number=1,
            story_memory=story_memory,
            scene_payload=scene_payload,
        )

        self.assertIn("当前 scene 的第一个 chunk 必须从本 scene 在正文里的真正起点开始", prompt)
        self.assertIn("不能回放", prompt)
        self.assertIn("当前 scene 已绑定这些关键事件 ID", prompt)
        self.assertIn("当前 scene 只允许覆盖下面这些绑定事件内容", prompt)
        self.assertIn("离开图书馆，继续沿教学楼外步道前行", prompt)
        self.assertIn("最后一个 chunk 必须真正落到当前 scene 的最后一个事件结果", prompt)
        self.assertIn("`expected_segment_count` 是后续 segment planner 的硬上限", prompt)
        self.assertIn("告白、回应类 scene 优先拆成 1-3 个 chunk", prompt)
        self.assertIn("一个 chunk 必须对应一个连续事件目标", prompt)
        self.assertIn("`expected_segment_count` 要按保守上限填写，优先填 1", prompt)
        self.assertIn("`must_cover + transition_goal` 已经包含 4 个及以上推进点", prompt)

    def test_scene_segment_contract_prompt_requires_scene_transition_contract_on_first_chunk(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "segment-contract-scene-transition-prompt",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "segment-contract-scene-transition-memory"),
        )
        scene_payload = {
            "scene_id": "ch01-sc02",
            "chapter_number": 1,
            "title": "从花廊走向镜湖",
            "summary": "两人沿着花廊出口继续走向镜湖步道。",
            "scene_anchor": "镜湖步道 / 傍晚 / 花廊出口后",
            "involved_characters": ["陈默", "林晚"],
            "scene_transition_contract": {
                "previous_scene_id": "ch01-sc01",
                "transition_mode": "adjacent_move",
                "previous_scene_exit_state": "两人刚从花廊下并肩迈步离开，仍保持紧张对视后的沉默。",
                "next_scene_entry_match": "当前场开头先承接两人并肩前行的状态，再带出镜湖步道。",
                "bridge_action": "先跟着两人离开花廊出口，再顺势露出镜湖步道和栏杆。",
                "carry_over_elements": ["并肩关系", "沉默未散", "向右前方行进"],
                "screen_direction_policy": "继续保持向右前方行进，不要突然反向。",
                "visual_bridge": "先看脚步和肩线，再 reveal 镜湖步道空间。",
                "audio_bridge": "ambient_bridge",
                "transition_focus_seconds": 2,
            },
            "scene_bible": {
                "location": "镜湖步道",
                "time_window": "傍晚",
                "weather": "微风",
                "lighting": "湖面反光与暖色侧光并存",
                "dominant_palette": ["暖橙", "湖蓝"],
                "background_anchors": ["镜湖步道", "栏杆", "湖面"],
                "fixed_props": ["石质栏杆"],
                "spatial_layout": "步道沿湖延伸，花廊出口在后方",
                "character_blocking": "两人并肩从花廊出口方向走入镜湖步道",
                "continuity_notes": "先承接离开花廊后的行进，再稳定到镜湖空间",
            },
        }
        chunk_payload = {
            "chunk_id": "chunk-01",
            "order_index": 1,
            "title": "走入镜湖步道",
            "summary": "两人从花廊出口继续走入镜湖步道。",
            "must_cover": ["承接并肩前行", "带出镜湖步道"],
            "transition_goal": "两人在镜湖边慢下来，准备说话。",
            "expected_segment_count": 1,
        }

        prompt = service._build_scene_segment_contract_user_prompt(
            story_result.novel_package,
            chapter_number=1,
            story_memory=story_memory,
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
            previous_chunk_exit_state={},
        )

        self.assertIn("当前是本 scene 的首个 chunk，必须消费 `scene_transition_contract`", prompt)
        self.assertIn("第一条或前两条 `timed_beats` 必须包含 `bridge_action`", prompt)
        self.assertIn("允许在 `opening_match` 里明确写出“承接上一场尾部”的可拍状态", prompt)
        self.assertIn("\"previous_scene_id\":\"ch01-sc01\"", prompt)

    def test_chapter_event_planner_prompt_requires_splitting_overloaded_event_chain(self) -> None:
        chapter_markdown = (
            "陈默在长椅旁等待。林晚从教学楼方向走来。"
            "陈默终于开口说喜欢她，林晚听完后主动抱住他。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="镜湖告白",
                characters=[SimpleNamespace(name="陈默"), SimpleNamespace(name="林晚")],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=["陈默", "林晚"],
                        goal="说出心意",
                        summary="两人在镜湖边完成一次告白与回应。",
                        key_conflict="陈默迟迟不敢开口",
                    )
                ],
            ),
            chapters=[SimpleNamespace(number=1, markdown=chapter_markdown)],
        )
        service = NovelToVideoService()

        prompt = service._build_chapter_event_coverage_user_prompt(
            novel_package,
            chapter_number=1,
        )

        self.assertIn("普通 event 最多只保留 1-2 个紧密绑定的推进点", prompt)
        self.assertIn("如果当前章节已经拆成多个 event，章节首尾 event 最多允许 3 个紧密绑定推进点", prompt)
        self.assertIn("等待 -> 会面 -> 开口", prompt)
        self.assertIn("背景介绍、关系说明、人物履历、内心说明、回忆补叙如果只是解释上下文，不要单独抽成 must-cover event", prompt)
        self.assertIn("中间 event 尤其要保持窄", prompt)
        self.assertIn("source_evidence` 只保留当前 event 对应的 1-2 个相邻正文片段", prompt)

    def test_chapter_event_coverage_validation_rejects_short_chapter_ending_too_early(self) -> None:
        lead_a = "陈默"
        lead_b = "林晚"
        chapter_markdown = (
            f"{lead_a}在长椅旁等了很久，反复数着脚边的落叶。"
            f"{lead_b}终于从教学楼方向走来，在他面前停下。"
            f"{lead_a}喉结滚动，先夸她今天画得真好，又沉默了很久。"
            f"风把她的发尾轻轻吹起来，他终于说出喜欢她很多年。"
            f"{lead_b}先怔住，然后笑着问他为什么现在才说。"
            f"{lead_a}紧张得差点说不完整，她却主动站近一步，轻轻抱住他。"
            f"他抬手回抱，闭上眼睛，听见她在耳边说其实她也等了很久。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        summary=chapter_markdown,
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        service = NovelToVideoService()
        event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}等待{lead_b}到来。",
                        "source_evidence": ["等了很久", "终于从教学楼方向走来"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_a}先夸{lead_b}今天画得真好。",
                        "source_evidence": ["画得真好"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "章节关键事件没有覆盖到章节尾部的真实收束"):
            service._validate_chapter_event_coverage_output(
                event_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

    def test_chapter_event_coverage_validation_rejects_action_overloaded_event(self) -> None:
        lead_a = "陈默"
        lead_b = "林晚"
        chapter_markdown = (
            f"{lead_a}在长椅旁等待。"
            f"{lead_b}从教学楼方向走来，在他面前停下。"
            f"{lead_a}终于抬头开口。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        summary=chapter_markdown,
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        service = NovelToVideoService()
        event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}等待{lead_b}走来后终于开口。",
                        "source_evidence": ["等待", "走来", "开口"],
                        "involved_characters": [lead_a, lead_b],
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "关键事件 ch01-ev01 过于粗"):
            service._validate_chapter_event_coverage_output(
                event_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

    def test_chapter_event_coverage_validation_does_not_double_count_source_evidence_fragments(self) -> None:
        lead_a = "林辰"
        lead_b = "苏雨"
        chapter_markdown = (
            f"{lead_a}在花园入口紧张等待。"
            f"{lead_b}走到他面前时，他深呼吸，准备开口。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        summary=chapter_markdown,
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        service = NovelToVideoService()
        event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}紧张等待{lead_b}来到面前后，深呼吸准备开口。",
                        "source_evidence": ["紧张等待", "走到他面前", "深呼吸", "准备开口"],
                        "involved_characters": [lead_a, lead_b],
                    }
                ],
            }
        )

        validated = service._validate_chapter_event_coverage_output(
            event_plan,
            novel_package=novel_package,
            chapter_number=1,
        )

        self.assertEqual(validated.events[0].event_id, "ch01-ev01")

    def test_chapter_event_coverage_validation_allows_three_tightly_bound_nodes_on_last_event(self) -> None:
        lead_a = "陈默"
        lead_b = "林晚"
        chapter_markdown = (
            f"{lead_a}在长椅旁等待{lead_b}到来。"
            f"{lead_a}鼓起勇气说喜欢她。"
            f"{lead_b}先怔住，然后靠近抱住他，轻声答应。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        summary=chapter_markdown,
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        service = NovelToVideoService()
        event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}等待{lead_b}到来。",
                        "source_evidence": ["等待", "到来"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_a}鼓起勇气说喜欢她。",
                        "source_evidence": ["说喜欢她"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_b}怔住后靠近抱住{lead_a}并答应。",
                        "source_evidence": ["怔住", "靠近抱住他", "轻声答应"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )

        validated = service._validate_chapter_event_coverage_output(
            event_plan,
            novel_package=novel_package,
            chapter_number=1,
        )

        self.assertEqual(validated.events[-1].event_id, "ch01-ev03")

    def test_validate_or_repair_chapter_event_plan_runs_targeted_repair_for_coarse_middle_event(self) -> None:
        lead_a = "林辰"
        lead_b = "苏雨"
        chapter_markdown = (
            f"{lead_a}在樱花树下等待。"
            f"他们上学期在图书馆认识，后来也偶尔相遇。"
            f"{lead_b}从小径走近，看到花后问他是不是在等她。"
            f"{lead_a}紧张地说自己有话想说。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="樱花告白",
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=[lead_a, lead_b],
                        goal="让告白真正开始",
                        summary="林辰在樱花树下等到苏雨，告白前的问答开始。",
                        key_conflict="林辰不敢直接开口",
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        invalid_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "从小径走近"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"两人在图书馆认识后再次相遇，{lead_b}走近看到花并发问。",
                        "source_evidence": ["在图书馆认识", "偶尔相遇", "看到花后问他是不是在等她"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}紧张地说自己有话想说。",
                        "source_evidence": ["有话想说"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        repaired_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "从小径走近"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看到{lead_a}手里的花后问他是不是在等她。",
                        "source_evidence": ["看到花后问他是不是在等她"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}紧张地说自己有话想说。",
                        "source_evidence": ["有话想说"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        service = NovelToVideoService()

        with patch.object(service, "_run_strict_structured_agent", return_value=repaired_plan) as repair_mock:
            validated = service._validate_or_repair_chapter_event_plan(
                invalid_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

        self.assertEqual(validated.events[1].summary, f"{lead_b}看到{lead_a}手里的花后问他是不是在等她。")
        request = repair_mock.call_args.kwargs["request"]
        self.assertEqual(request.metadata["task"], "video-chapter-event-repair")
        self.assertEqual(request.metadata["offending_event_id"], "ch01-ev02")
        self.assertIn("回忆补叙", request.user_prompt)
        self.assertIn("中间 event 必须更窄", request.user_prompt)
        self.assertIn("ch01-ev02", request.user_prompt)

    def test_repair_chapter_event_plan_falls_back_to_targeted_event_split(self) -> None:
        lead_a = "林辰"
        lead_b = "苏雨"
        chapter_markdown = (
            f"{lead_a}在樱花树下等待。"
            f"{lead_b}走近后先看到他手里的花，接着问他是不是在等自己。"
            f"{lead_a}沉默了两秒，最后才说自己有话想说。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="樱花告白",
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=[lead_a, lead_b],
                        goal="让告白真正开始",
                        summary="两人在樱花树下会面，问答后进入告白前停顿。",
                        key_conflict="林辰不敢直接开口",
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        invalid_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "走近"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看到花后先发问又继续追问，{lead_a}沉默片刻后终于说自己有话想说。",
                        "source_evidence": ["看到他手里的花", "问他是不是在等自己", "沉默了两秒", "最后才说自己有话想说"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        split_plan = ChapterCoverageEventSplitPlanSchema.model_validate(
            {
                "events": [
                    {
                        "summary": f"{lead_b}看到{lead_a}手里的花后问他是不是在等自己。",
                        "source_evidence": ["看到他手里的花", "问他是不是在等自己"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "summary": f"{lead_a}沉默片刻后说自己有话想说。",
                        "source_evidence": ["沉默了两秒", "有话想说"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ]
            }
        )
        service = NovelToVideoService()

        def strict_agent_side_effect(*, schema, request, validator, attempts=3):
            if request.metadata["task"] == "video-chapter-event-repair":
                raise RuntimeError(
                    "Structured repair failed for task=video-chapter-event-repair "
                    "schema=ChapterCoveragePlanSchema after 3 attempts: "
                    "关键事件 ch01-ev02 过于粗：当前至少包含 4 个推进点。"
                    "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
                )
            self.assertEqual(request.metadata["task"], "video-chapter-event-split-repair")
            return validator(split_plan)

        with patch.object(service, "_run_strict_structured_agent", side_effect=strict_agent_side_effect) as repair_mock:
            validated = service._repair_chapter_event_plan_after_validation_failure(
                chapter_event_plan=invalid_plan,
                novel_package=novel_package,
                chapter_number=1,
                failure=ValueError(
                    "关键事件 ch01-ev02 过于粗：当前至少包含 4 个推进点。"
                    "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
                ),
            )

        self.assertEqual(
            [item.event_id for item in validated.events],
            ["ch01-ev01", "ch01-ev02", "ch01-ev03"],
        )
        self.assertEqual(
            validated.events[1].summary,
            f"{lead_b}看到{lead_a}手里的花后问他是不是在等自己。",
        )
        self.assertEqual(
            validated.events[2].summary,
            f"{lead_a}沉默片刻后说自己有话想说。",
        )
        split_request = repair_mock.call_args_list[1].kwargs["request"]
        self.assertEqual(split_request.metadata["task"], "video-chapter-event-split-repair")
        self.assertEqual(split_request.metadata["offending_event_id"], "ch01-ev02")
        self.assertIn("只把这个过粗 event 拆成 2-4 个更细", split_request.user_prompt)
        self.assertIn("不要输出 `event_id`", split_request.user_prompt)

    def test_validate_chapter_event_split_plan_allows_other_coarse_events_to_remain_for_next_round(self) -> None:
        lead_a = "林辰"
        lead_b = "苏雨"
        chapter_markdown = (
            f"{lead_a}在樱花树下等待。"
            f"{lead_b}走近后先看见他手里的花，问他是不是在等自己。"
            f"{lead_a}沉默了两秒。"
            f"随后{lead_a}深吸一口气，说自己有话想说，把花递给{lead_b}，等她接过。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="樱花告白",
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=[lead_a, lead_b],
                        goal="让告白真正开始",
                        summary="两人在樱花树下会面，问答后进入递花时刻。",
                        key_conflict="林辰不敢直接开口",
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        chapter_event_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待，{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "走近后"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看见花后发问，{lead_a}沉默了两秒。",
                        "source_evidence": ["看见他手里的花", "问他是不是在等自己", "沉默了两秒"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}深吸一口气，说自己有话想说，把花递给{lead_b}，等她接过。",
                        "source_evidence": ["深吸一口气", "有话想说", "把花递给苏雨", "等她接过"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        split_plan = ChapterCoverageEventSplitPlanSchema.model_validate(
            {
                "events": [
                    {
                        "summary": f"{lead_b}看见{lead_a}手里的花后问他是不是在等自己。",
                        "source_evidence": ["看见他手里的花", "问他是不是在等自己"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "summary": f"{lead_a}沉默了两秒。",
                        "source_evidence": ["沉默了两秒"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ]
            }
        )
        service = NovelToVideoService()

        validated = service._validate_chapter_event_split_plan(
            split_plan,
            chapter_event_plan=chapter_event_plan,
            novel_package=novel_package,
            chapter_number=1,
            offending_event_index=1,
        )

        self.assertEqual(len(validated.events), 2)
        merged_plan = service._merge_chapter_event_split_plan(
            chapter_event_plan=chapter_event_plan,
            split_plan=split_plan,
            chapter_number=1,
            offending_event_index=1,
        )
        with self.assertRaisesRegex(ValueError, "关键事件 ch01-ev04 过于粗"):
            service._validate_chapter_event_coverage_output(
                merged_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

    def test_validate_or_repair_chapter_event_plan_repairs_multiple_coarse_events_iteratively(self) -> None:
        lead_a = "林辰"
        lead_b = "苏雨"
        chapter_markdown = (
            f"{lead_a}在樱花树下等待。"
            f"{lead_b}走近后先看见他手里的花，问他是不是在等自己。"
            f"{lead_a}沉默了两秒。"
            f"随后{lead_a}深吸一口气，说自己有话想说，把花递给{lead_b}，等她接过。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="樱花告白",
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=[lead_a, lead_b],
                        goal="让告白真正开始",
                        summary="两人在樱花树下会面，问答后进入递花时刻。",
                        key_conflict="林辰不敢直接开口",
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        invalid_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待，{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "走近后"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看见花后发问，{lead_a}沉默了两秒。",
                        "source_evidence": ["看见他手里的花", "问他是不是在等自己", "沉默了两秒"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}深吸一口气，说自己有话想说，把花递给{lead_b}，等她接过。",
                        "source_evidence": ["深吸一口气", "有话想说", "把花递给苏雨", "等她接过"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        first_repaired_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待，{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "走近后"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看见{lead_a}手里的花后问他是不是在等自己。",
                        "source_evidence": ["看见他手里的花", "问他是不是在等自己"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}沉默了两秒。",
                        "source_evidence": ["沉默了两秒"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev04",
                        "summary": f"{lead_a}深吸一口气，说自己有话想说，把花递给{lead_b}，等她接过。",
                        "source_evidence": ["深吸一口气", "有话想说", "把花递给苏雨", "等她接过"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        second_repaired_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}在樱花树下等待，{lead_b}走近。",
                        "source_evidence": ["在樱花树下等待", "走近后"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev02",
                        "summary": f"{lead_b}看见{lead_a}手里的花后问他是不是在等自己。",
                        "source_evidence": ["看见他手里的花", "问他是不是在等自己"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev03",
                        "summary": f"{lead_a}沉默了两秒。",
                        "source_evidence": ["沉默了两秒"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev04",
                        "summary": f"{lead_a}深吸一口气，说自己有话想说。",
                        "source_evidence": ["深吸一口气", "有话想说"],
                        "involved_characters": [lead_a, lead_b],
                    },
                    {
                        "event_id": "ch01-ev05",
                        "summary": f"{lead_a}把花递给{lead_b}，等她接过。",
                        "source_evidence": ["把花递给苏雨", "等她接过"],
                        "involved_characters": [lead_a, lead_b],
                    },
                ],
            }
        )
        service = NovelToVideoService()

        def repair_side_effect(*, chapter_event_plan, novel_package, chapter_number, failure):
            failure_text = str(failure)
            if "ch01-ev03" in failure_text:
                return first_repaired_plan
            if "ch01-ev04" in failure_text:
                return second_repaired_plan
            raise AssertionError(f"unexpected failure text: {failure_text}")

        with patch.object(
            service,
            "_repair_chapter_event_plan_after_validation_failure",
            side_effect=repair_side_effect,
        ) as repair_mock:
            validated = service._validate_or_repair_chapter_event_plan(
                invalid_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

        self.assertEqual(repair_mock.call_count, 2)
        self.assertEqual(
            [item.event_id for item in validated.events],
            ["ch01-ev01", "ch01-ev02", "ch01-ev03", "ch01-ev04", "ch01-ev05"],
        )
        self.assertEqual(
            validated.events[-1].summary,
            f"{lead_a}把花递给{lead_b}，等她接过。",
        )

    def test_validate_or_repair_chapter_event_plan_soft_accepts_coarse_event_with_warning(self) -> None:
        lead_a = "陈默"
        lead_b = "林晚"
        chapter_markdown = (
            f"{lead_a}在长椅旁等待。"
            f"{lead_b}从教学楼方向走来，在他面前停下。"
            f"{lead_a}终于抬头开口。"
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="长椅告白",
                characters=[
                    SimpleNamespace(name=lead_a),
                    SimpleNamespace(name=lead_b),
                ],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白前",
                        featured_characters=[lead_a, lead_b],
                        goal="让会面真正开始",
                        summary=chapter_markdown,
                        key_conflict="陈默开不了口",
                    )
                ],
            ),
            chapters=[
                SimpleNamespace(
                    number=1,
                    markdown=chapter_markdown,
                )
            ],
        )
        invalid_plan = ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": 1,
                "events": [
                    {
                        "event_id": "ch01-ev01",
                        "summary": f"{lead_a}等待{lead_b}走来后终于开口。",
                        "source_evidence": ["等待", "走来", "开口"],
                        "involved_characters": [lead_a, lead_b],
                    }
                ],
            }
        )
        service = NovelToVideoService()

        with patch.object(
            service,
            "_repair_chapter_event_plan_after_validation_failure",
            side_effect=RuntimeError("repair unavailable"),
        ):
            validated = service._validate_or_repair_chapter_event_plan(
                invalid_plan,
                novel_package=novel_package,
                chapter_number=1,
            )

        self.assertEqual(validated.events[0].event_id, "ch01-ev01")
        story_memory = service._flush_planner_warnings_to_story_memory(StoryMemoryPackage())
        self.assertTrue(
            any("关键事件 ch01-ev01 过于粗" in item for item in story_memory.generation_notes.planner_warnings)
        )

    def test_validate_or_repair_scene_chunk_plan_runs_targeted_repair_for_action_overload(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园入口",
                "summary": "两人在花园入口从等待推进到正式开始对话。",
                "scene_anchor": "花园入口 / 傍晚 / 微风",
                "involved_characters": ["林辰", "苏雨"],
                "scene_bible": {
                    "location": "花园入口",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖色侧光",
                    "background_anchors": ["入口拱门", "石板路"],
                    "fixed_props": ["花坛"],
                    "spatial_layout": "入口面对石板路，花坛在左侧",
                    "character_blocking": "先等待，再走近开口",
                    "continuity_notes": "保持入口拱门和石板路关系稳定",
                },
            }
        )
        invalid_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "ch01-sc01-ch01",
                        "order_index": 1,
                        "title": "全塞一起",
                        "summary": "林辰等待、苏雨走近、林辰开口、苏雨回应全部塞在一起。",
                        "must_cover": ["林辰等待", "苏雨走近", "林辰开口"],
                        "transition_goal": "苏雨回应并进入正式对话。",
                        "expected_segment_count": 1,
                    }
                ],
            }
        )
        repaired_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "ch01-sc01-ch01",
                        "order_index": 1,
                        "title": "全塞一起",
                        "summary": "林辰等待、苏雨走近、林辰开口、苏雨回应全部塞在一起。",
                        "must_cover": ["林辰等待", "苏雨走近", "林辰开口"],
                        "transition_goal": "苏雨回应并进入正式对话。",
                        "expected_segment_count": 2,
                    }
                ],
            }
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="花园告白",
                characters=[SimpleNamespace(name="林辰"), SimpleNamespace(name="苏雨")],
                chapters=[SimpleNamespace(number=1, title="告白", featured_characters=["林辰", "苏雨"], goal="开始对话", summary="在花园入口等待并开口。", key_conflict="林辰不敢开口", beats=["林辰等待", "苏雨走近", "林辰开口", "苏雨回应"])],
            ),
            chapters=[SimpleNamespace(number=1, markdown="林辰等待。苏雨走近。林辰开口。苏雨回应。")],
        )
        story_memory = StoryMemoryPackage()

        with patch.object(service, "_run_strict_structured_agent", return_value=repaired_plan) as repair_mock:
            validated = service._validate_or_repair_scene_chunk_plan(
                invalid_plan,
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=1,
                scene=scene,
            )

        self.assertEqual(validated.chunks[0].expected_segment_count, 2)
        request = repair_mock.call_args.kwargs["request"]
        self.assertEqual(request.metadata["task"], "video-scene-chunk-repair")
        self.assertEqual(request.metadata["offending_chunk_id"], "ch01-sc01-ch01")
        self.assertEqual(request.metadata["required_segment_count"], 2)
        self.assertIn("当前失败项邻域", request.user_prompt)
        self.assertIn("如果当前失败项已经包含 4 个及以上推进点", request.user_prompt)
        self.assertIn("expected_segment_count", request.user_prompt)

    def test_validate_or_repair_scene_chunk_plan_soft_accepts_action_overload_with_warning(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "花园长椅前",
                "summary": "两人在长椅前从试探推进到关系确认。",
                "scene_anchor": "花园长椅，傍晚",
                "involved_characters": ["林辰", "苏晴"],
                "scene_bible": {
                    "location": "花园长椅前",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "暖金色侧光",
                    "dominant_palette": ["暖橙", "墨绿"],
                    "background_anchors": ["长椅", "石板路"],
                    "fixed_props": ["信封"],
                    "spatial_layout": "长椅靠近石板路，人物面对面站立",
                    "character_blocking": "两人从试探到确认逐步靠近",
                    "continuity_notes": "保持长椅和石板路关系稳定",
                },
            }
        )
        invalid_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "confession-all-in-one",
                        "order_index": 1,
                        "title": "整轮告白都塞在一起",
                        "summary": "从试探开口一路推进到明确回应和关系落点。",
                        "must_cover": ["试探开口", "正式告白", "明确回应"],
                        "transition_goal": "两人停在新的关系确认状态里。",
                        "expected_segment_count": 1,
                    }
                ],
            }
        )
        novel_package = SimpleNamespace(
            outline=SimpleNamespace(
                title="花园告白",
                characters=[SimpleNamespace(name="林辰"), SimpleNamespace(name="苏晴")],
                chapters=[
                    SimpleNamespace(
                        number=1,
                        title="告白",
                        featured_characters=["林辰", "苏晴"],
                        goal="关系确认",
                        summary="两人在长椅前从试探推进到关系确认。",
                        key_conflict="林辰不敢开口",
                        beats=["试探开口", "正式告白", "明确回应"],
                    )
                ],
            ),
            chapters=[SimpleNamespace(number=1, markdown="林辰试探开口。林辰正式告白。苏晴明确回应。")],
        )
        story_memory = StoryMemoryPackage()

        with patch.object(
            service,
            "_repair_scene_chunk_plan_after_validation_failure",
            side_effect=RuntimeError("repair unavailable"),
        ):
            validated = service._validate_or_repair_scene_chunk_plan(
                invalid_plan,
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=1,
                scene=scene,
            )

        self.assertEqual(validated.chunks[0].chunk_id, "confession-all-in-one")
        story_memory = service._flush_planner_warnings_to_story_memory(StoryMemoryPackage())
        self.assertTrue(
            any("动作容量过载" in item for item in story_memory.generation_notes.planner_warnings)
        )

    def test_chapter_segment_planner_uses_story_memory_and_calls_once_per_chapter(self) -> None:
        class ChapterCountingVideoBackend(DeterministicVideoBackend):
            def __init__(self) -> None:
                super().__init__()
                self.event_requests: list[PromptRequest] = []
                self.scene_requests: list[PromptRequest] = []
                self.chunk_requests: list[PromptRequest] = []
                self.segment_requests: list[PromptRequest] = []

            def generate_structured(self, request: PromptRequest, schema):
                if request.metadata.get("task") == "video-chapter-event-planner":
                    self.event_requests.append(request)
                if request.metadata.get("task") == "video-chapter-scene-planner":
                    self.scene_requests.append(request)
                if request.metadata.get("task") == "video-scene-chunk-planner":
                    self.chunk_requests.append(request)
                if request.metadata.get("task") == "video-scene-segment-planner":
                    self.segment_requests.append(request)
                return super().generate_structured(request, schema)

        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="镜湖告白",
            idea="毕业前夕，一个男生准备在镜湖边对喜欢的人告白。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=3,
            total_word_target=2400,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "story-memory-source",
        )
        backend = ChapterCountingVideoBackend()
        artifacts = build_video_planning_artifacts(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "story-memory-plan",
            backend=backend,
        )

        self.assertEqual(len(backend.event_requests), 3)
        self.assertEqual(
            [request.metadata.get("chapter_number") for request in backend.event_requests],
            [1, 2, 3],
        )
        self.assertTrue(all("当前章节正文全文：" in request.user_prompt for request in backend.event_requests))
        self.assertEqual(len(backend.scene_requests), 3)
        self.assertEqual(
            [request.metadata.get("chapter_number") for request in backend.scene_requests],
            [1, 2, 3],
        )
        self.assertTrue(all("story memory" in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(all("当前章必须覆盖的关键事件" in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(
            all(request.user_prompt.count("该章应由模型自行判断拆成几段") == 1 for request in backend.scene_requests)
        )
        self.assertTrue(all('"chapter_batch_view"' in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(all('"recent_chapter_memory"' in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(all('"focus_cast_bible"' in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(all('"carry_over_summary"' in request.user_prompt for request in backend.scene_requests))
        self.assertTrue(all('"planning_index"' not in request.user_prompt for request in backend.scene_requests))
        self.assertEqual(len(backend.chunk_requests), 3)
        self.assertTrue(all("目标 scene JSON" in request.user_prompt for request in backend.chunk_requests))
        self.assertTrue(all('"focus_cast_bible"' in request.user_prompt for request in backend.chunk_requests))
        self.assertTrue(all('"carry_over_visuals"' in request.user_prompt for request in backend.chunk_requests))
        self.assertTrue(all('"recent_chapter_memory"' not in request.user_prompt for request in backend.chunk_requests))
        self.assertTrue(all('"planning_index"' not in request.user_prompt for request in backend.chunk_requests))
        self.assertEqual(len(backend.segment_requests), 3)
        self.assertTrue(all("目标 scene JSON" in request.user_prompt for request in backend.segment_requests))
        self.assertTrue(all('"focus_cast_bible"' in request.user_prompt for request in backend.segment_requests))
        self.assertTrue(all('"relationship_state"' in request.user_prompt for request in backend.segment_requests))
        self.assertTrue(all('"recent_chapter_memory"' not in request.user_prompt for request in backend.segment_requests))
        self.assertTrue(all('"planning_index"' not in request.user_prompt for request in backend.segment_requests))
        self.assertTrue(all(request.metadata.get("total_prompt_chars", 0) > 0 for request in backend.scene_requests))
        self.assertTrue(all(request.metadata.get("total_prompt_chars", 0) > 0 for request in backend.chunk_requests))
        self.assertTrue(all(request.metadata.get("total_prompt_chars", 0) > 0 for request in backend.segment_requests))
        self.assertTrue(
            all(
                request.metadata["total_prompt_chars"]
                == request.metadata["system_prompt_chars"] + request.metadata["user_prompt_chars"]
                for request in backend.scene_requests + backend.chunk_requests + backend.segment_requests
            )
        )
        self.assertTrue(all(request.metadata["total_prompt_chars"] < 6500 for request in backend.scene_requests))
        self.assertTrue(all(request.metadata["total_prompt_chars"] < 4200 for request in backend.chunk_requests))
        self.assertTrue(all(request.metadata["total_prompt_chars"] < 6400 for request in backend.segment_requests))
        self.assertTrue(artifacts.story_memory_path.exists())
        loaded = load_video_planning_artifacts(artifacts.output_dir)
        self.assertIsNotNone(loaded.project_package.story_memory)

    def test_scene_chunk_planner_prompt_uses_scene_focused_excerpt(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="镜湖聚焦摘录",
            idea="毕业前夕，一个男生在镜湖边等待喜欢的人。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "focused-excerpt",
        )
        story_result.novel_package.chapters[0].markdown = (
            "他先在机房里检查了很久的代码和投影设备。"
            "图书馆门口的风吹得人有些发冷。"
            "陈默站在镜湖边长椅旁等待林晚出现，湖面对岸亮起一排暖灯。"
            "他反复练习开口的话，直到看见林晚沿着湖边步道走来。"
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "focused-excerpt-memory"),
        )
        scene_payload = {
            "scene_id": "ch01-sc01",
            "chapter_number": 1,
            "title": "镜湖长椅",
            "summary": "陈默在镜湖边长椅等待林晚出现。",
            "scene_anchor": "镜湖边长椅，湖面对岸亮灯，傍晚微风",
            "involved_characters": ["陈默", "林晚"],
            "scene_bible": {
                "location": "镜湖边长椅",
                "time_window": "傍晚",
                "weather": "微风",
                "lighting": "对岸暖灯",
                "dominant_palette": ["暖橙", "深蓝"],
                "background_anchors": ["镜湖", "长椅", "对岸灯光"],
                "fixed_props": ["书包"],
                "spatial_layout": "长椅靠湖，步道从右后方延伸而来",
                "character_blocking": "陈默先独自等待，林晚后续沿步道走近",
                "continuity_notes": "保持镜湖、长椅和对岸灯光关系稳定",
            },
        }

        prompt = service._build_scene_chunk_planner_user_prompt(
            story_result.novel_package,
            chapter_number=1,
            story_memory=story_memory,
            scene_payload=scene_payload,
        )

        self.assertIn("本次聚焦：", prompt)
        self.assertIn("镜湖边长椅", prompt)
        self.assertIn("陈默站在镜湖边长椅旁等待林晚出现", prompt)
        self.assertNotIn("机房里检查了很久的代码", prompt)

    def test_scene_chunk_planner_merges_chunk_contracts_into_sequential_segments(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="镜湖告白分块测试",
            idea="黄昏时分，一个男生在校园里等待喜欢的人到来并准备告白。",
            genre="校园情感",
            tone="克制、温柔",
            chapter_count=1,
            total_word_target=1200,
        )
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "chunked-scene",
        )
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        visual_bible = build_test_visual_bible(story_result.novel_package)
        story_memory = service._build_story_memory(
            story_result.novel_package,
            visual_bible,
            str(self.temp_root / "chunked-scene-memory"),
        )
        character_names = [
            item.name for item in story_result.novel_package.outline.characters[:2]
        ]
        first_character = character_names[0]
        raw_scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "title": "镜湖长椅",
                "summary": "主角先独自等待，随后对方入镜，两人正式开始对话。",
                "scene_anchor": "镜湖边长椅，傍晚，湖面对岸亮起灯光",
                "involved_characters": character_names,
                "scene_bible": {
                    "location": "镜湖边长椅",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "柔和侧光",
                    "dominant_palette": ["暖橙", "深蓝"],
                    "background_anchors": ["湖面", "长椅", "对岸灯光"],
                    "fixed_props": ["书包"],
                    "spatial_layout": "长椅靠湖，人物沿步道进入画面",
                    "character_blocking": "先单人等待，再双人对话",
                    "continuity_notes": "同一 scene 内保持湖边与长椅的背景关系稳定",
                },
            }
        )
        chunk_plan = SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "chunks": [
                    {
                        "chunk_id": "wait",
                        "order_index": 1,
                        "title": "等待",
                        "summary": "主角独自在长椅旁等待，对方尚未入镜。",
                        "must_cover": ["单人等待", "紧张情绪"],
                        "transition_goal": "停在听到脚步声前的悬置状态。",
                        "expected_segment_count": 1,
                    },
                    {
                        "chunk_id": "meet",
                        "order_index": 2,
                        "title": "会面",
                        "summary": "对方入镜，两人正式开始对话。",
                        "must_cover": ["对方入镜", "正式开口"],
                        "transition_goal": "推进到双人关系建立。",
                        "expected_segment_count": 1,
                    },
                ],
            }
        )
        first_batch = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "等待",
                        "summary": "主角在湖边长椅旁等待。",
                        "involved_characters": [first_character],
                        "start_frame_characters": [first_character],
                        "mid_frame_characters": [],
                        "end_frame_characters": [first_character],
                        "narration": "他在长椅旁等待。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["他在长椅旁等待。"],
                        "timed_beats": ["0-6秒：他在长椅旁等待。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": False,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "中景",
                            "camera_motion": "缓慢推进",
                            "blocking": "单人站在长椅侧前方",
                            "action_progression": "等待并听见远处脚步声",
                            "emotion_progression": "紧张逐步累积",
                            "prop_continuity": "书包留在肩侧",
                            "screen_direction": "面向右前方",
                            "end_state_lock": "他在听到脚步声后微微回头，动作停住",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": "主角已站在长椅侧前方，面向前方等待。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立单人等待的开场基线。",
                            "transition_reason": "当前 scene 的起始段。",
                        },
                    }
                ],
            }
        )
        second_batch = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc01",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "title": "会面",
                        "summary": "对方走近后，两人正式开始对话。",
                        "involved_characters": character_names,
                        "start_frame_characters": [first_character],
                        "mid_frame_characters": character_names,
                        "end_frame_characters": character_names,
                        "narration": "脚步声靠近，对话终于开始。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["脚步声靠近，对话终于开始。"],
                        "timed_beats": ["0-6秒：脚步声靠近，对话终于开始。"],
                        "duration_seconds": 6,
                        "requires_mid_frame": True,
                        "transition_hint": "continue",
                        "shot_state": {
                            "framing": "中景转双人中近景",
                            "camera_motion": "轻微前推",
                            "blocking": "另一人从右侧入镜，停在主角身前",
                            "action_progression": "从回头承接到正式开口",
                            "emotion_progression": "紧张转为面对面交流",
                            "prop_continuity": "书包仍在肩侧",
                            "screen_direction": "延续上一段的右向视线",
                            "end_state_lock": "两人停在面对面的对话姿态",
                        },
                        "continuity_link": {
                            "previous_segment_id": "ch01-sc01-seg01",
                            "transition_mode": "continue",
                            "opening_match": "承接上一段尾部，他仍站在长椅旁并转向来人。",
                            "carry_over_elements": ["长椅站位", "书包", "右向视线"],
                            "allowed_changes": "对方入镜，等待推进到正式对话。",
                            "transition_reason": "同一 scene 内继续推进到会面动作。",
                        },
                    }
                ],
            }
        )

        with patch.object(
            NovelToVideoService,
            "_execute_structured_request",
            autospec=True,
            side_effect=[chunk_plan, first_batch, second_batch],
        ):
            plan = service._build_scene_plan_from_scene_structure(
                novel_package=story_result.novel_package,
                story_memory=story_memory,
                chapter_number=1,
                raw_scene=raw_scene,
            )

        self.assertEqual(
            [item.segment_id for item in plan.segments],
            ["ch01-sc01-seg01", "ch01-sc01-seg02"],
        )
        self.assertEqual(
            plan.segments[1].continuity_link.previous_segment_id,
            "ch01-sc01-seg01",
        )
        self.assertEqual(plan.segments[1].continuity_link.transition_mode, "continue")
        self.assertIn("承接上一段尾部", plan.segments[1].continuity_link.opening_match)

    def test_repair_segment_plan_preserves_all_llm_segments_within_same_chapter(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        visual_bible = build_test_visual_bible(story_result.novel_package)
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
        self.assertTrue(all(item.requires_mid_frame for item in normalized.segments))
        self.assertTrue(all(item.mid_frame_prompt for item in normalized.segments))
        self.assertTrue(all(item.timed_beats for item in normalized.segments))
        self.assertTrue(all(item.subtitle_lines for item in normalized.segments))
        self.assertTrue(all(item.start_frame_prompt for item in normalized.segments))
        self.assertTrue(all("当前子片段" not in item.start_frame_prompt for item in normalized.segments))

        segments = [VideoSegment.from_dict(item.model_dump()) for item in normalized.segments]
        scenes = service._prepare_scene_master_frames(
            [VideoScene.from_dict(item.model_dump()) for item in normalized.scenes],
            str(self.temp_root),
        )
        character_profiles = [
            CharacterVisualProfile(
                name="林雪",
                role="信使",
                gender="女",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            )
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}
        scene_tasks = service._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertFalse(scene_tasks[0].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[0].continuity_source_segment_id, "")
        self.assertTrue(scene_tasks[0].requires_mid_frame)
        self.assertTrue(scene_tasks[0].mid_frame_path.endswith("_mid.png"))
        self.assertTrue(scene_tasks[0].scene_master_frame_prompt)
        self.assertTrue(scene_tasks[0].scene_master_frame_path.endswith("_master.png"))
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "snowport_01_01")
        self.assertTrue(scene_tasks[1].requires_mid_frame)
        self.assertTrue(scene_tasks[2].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[2].continuity_source_segment_id, "snowport_01_02")
        self.assertTrue(scene_tasks[2].requires_mid_frame)

    def test_scene_master_frame_prompt_is_pure_environment_without_characters(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=8,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="陈默告白前的等待",
                summary="陈默在紫藤花架下等待林晚赴约。",
                scene_anchor="陈默与林晚在紫藤花架下对视。",
                involved_characters=["陈默", "林晚"],
                covered_event_ids=[],
                segments=[],
                scene_bible=SceneBible(
                    location="大学中心花园的紫藤花架",
                    time_window="傍晚",
                    weather="晴天微风",
                    lighting="暖金色夕阳逆光",
                    dominant_palette=["暖金", "藤紫", "青绿"],
                    background_anchors=["紫藤花架", "鹅卵石小径", "远处教学楼"],
                    fixed_props=["木质长椅", "路灯"],
                    spatial_layout="陈默站在花架下，林晚从右侧小径走近。",
                    character_blocking="陈默在左，林晚在右，逐步靠近。",
                    continuity_notes="保持陈默与林晚的站位和情绪推进连续。",
                ),
            )
        )

        self.assertIn("纯室外环境参考图", prompt)
        self.assertIn("场景基线锁定", prompt)
        self.assertIn("无人物空场景", prompt)
        self.assertIn("大学中心花园的紫藤花架", prompt)
        self.assertIn("紫藤花架", prompt)
        self.assertIn("木质长椅", prompt)
        self.assertIn("暖金", prompt)
        self.assertNotIn("陈默", prompt)
        self.assertNotIn("林晚", prompt)
        self.assertNotIn("角色调度", prompt)

    def test_scene_master_frame_prompt_uses_structured_environment_template(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="花田尽头",
                summary="林屿在图书馆旁的郁金香花田等待苏晚。",
                scene_anchor="图书馆旁的郁金香花田，尽头银杏树下",
                involved_characters=["林屿", "苏晚"],
                covered_event_ids=[],
                segments=[],
                scene_bible=SceneBible(
                    location="图书馆旁的郁金香花田，尽头银杏树下（室外）",
                    time_window="傍晚",
                    weather="微风",
                    lighting="夕阳铺满花田，金色斜阳",
                    dominant_palette=["红色", "金色", "绿色"],
                    background_anchors=["银杏树", "红色郁金香花田", "石板路", "远处图书馆建筑外立面"],
                    fixed_props=["银杏树干", "石板路", "花田围栏"],
                    spatial_layout="银杏树位于花田尽头；石板路从花田间穿过通向图书馆方向；图书馆位于远景，仅外立面可见。",
                    character_blocking="林屿站在银杏树下，苏晚从石板路走来。",
                    continuity_notes="保持花田、银杏树和远景图书馆外立面的空间关系稳定。",
                ),
            )
        )

        self.assertTrue(prompt.startswith("原创虚构场景母图，风格化概念插画，非真人摄影。"))
        self.assertIn("这是一个纯室外环境参考图", prompt)
        self.assertIn("远景建筑只作为背景建筑外立面出现", prompt)
        self.assertIn("场景基线锁定：", prompt)
        self.assertIn("地点：图书馆旁的郁金香花田，尽头银杏树下（室外）", prompt)
        self.assertIn("空间布局：", prompt)
        self.assertIn("银杏树位于花田尽头", prompt)
        self.assertIn("图书馆位于远景，仅外立面可见", prompt)
        self.assertIn("主色调：红色、金色、绿色", prompt)
        self.assertIn("背景锚点：银杏树、红色郁金香花田、石板路、远处图书馆建筑外立面", prompt)
        self.assertIn("固定道具：银杏树干、石板路、花田围栏", prompt)
        self.assertIn("画面必须为无人物空场景", prompt)
        self.assertNotIn("林屿", prompt)
        self.assertNotIn("苏晚", prompt)
        self.assertNotIn("走来", prompt)

    def test_scene_master_frame_prompt_filters_weak_human_signals(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc05",
                chapter_number=1,
                title="花园中央平台",
                summary="告白后的情绪升温。",
                scene_anchor="向日葵花园中央平台",
                involved_characters=["陈默", "林晓"],
                covered_event_ids=[],
                segments=[],
                scene_bible=SceneBible(
                    location="向日葵花园中央平台",
                    time_window="夕阳沉到山脊线下，最后金光时刻",
                    weather="晴朗，微风",
                    lighting="最后的金色光芒像液体流淌，温暖柔和",
                    dominant_palette=["金黄色", "橙红色", "暖色调"],
                    background_anchors=["向日葵花海背景", "夕阳余晖", "两人剪影", "花园全景"],
                    fixed_props=["周围向日葵花丛", "平台空间"],
                    spatial_layout="两人在平台中央，距离很近",
                    character_blocking="两人面对面站立",
                    continuity_notes="保持花海、平台和夕阳余晖稳定",
                ),
            )
        )

        self.assertIn("向日葵花园中央平台", prompt)
        self.assertIn("花园全景", prompt)
        self.assertNotIn("两人在平台中央", prompt)
        self.assertNotIn("两人剪影", prompt)
        self.assertNotIn("面对面", prompt)

    def test_scene_master_frame_prompt_preserves_environment_spatial_contract_without_names(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc06",
                chapter_number=1,
                title="镜湖边的画架",
                summary="陈默在镜湖长椅旁，林晚从画架方向走近。",
                scene_anchor="镜湖、长椅、画架、后方步道",
                involved_characters=["陈默", "林晚"],
                covered_event_ids=[],
                segments=[],
                scene_bible=SceneBible(
                    location="镜湖边画架区",
                    time_window="傍晚",
                    weather="微风",
                    lighting="湖面对岸暖灯亮起",
                    dominant_palette=["暖橙", "深蓝"],
                    background_anchors=["镜湖", "长椅", "画架"],
                    fixed_props=["木质长椅", "画架"],
                    spatial_layout="陈默站在长椅旁，十米外画架正对湖面，林晚从画架后方步道走近。",
                    character_blocking="陈默在长椅一侧，林晚沿画架后方步道靠近。",
                    continuity_notes="保持长椅、画架和湖面的透视关系稳定。",
                ),
            )
        )

        self.assertIn("长椅", prompt)
        self.assertIn("画架", prompt)
        self.assertIn("十米外", prompt)
        self.assertIn("后方步道", prompt)
        self.assertNotIn("陈默", prompt)
        self.assertNotIn("林晚", prompt)
        self.assertNotIn("走近", prompt)

    def test_scene_master_frame_prompt_filters_transient_carried_props(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="栈道入口",
                summary="主角在栈道入口等待。",
                scene_anchor="红树林栈道入口，夕阳斜照",
                involved_characters=["林远"],
                covered_event_ids=[],
                segments=[],
                scene_bible=SceneBible(
                    location="红树林栈道入口",
                    time_window="傍晚",
                    weather="晴朗，海风轻拂",
                    lighting="夕阳斜照",
                    dominant_palette=["金色", "蓝色"],
                    background_anchors=["木板栈道", "公园入口牌"],
                    fixed_props=["手机", "木质长椅"],
                    spatial_layout="栈道入口连接石板路",
                    continuity_notes="保持入口空间与光线稳定",
                ),
            )
        )

        self.assertIn("木质长椅", prompt)
        self.assertNotIn("固定道具：手机", prompt)
        self.assertNotIn("手机", prompt)

    def test_prepare_scene_master_frame_enriches_weak_scene_bible_from_segment_environment(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=8,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )

        prepared = service._prepare_scene_master_frames(
            [
                VideoScene(
                    scene_id="ch01-sc01",
                    chapter_number=1,
                    title="考场里的发现",
                    summary="考试尾声，林栀偷看小册子，被巡视到桌边的周骁无声发现。",
                    scene_anchor="",
                    involved_characters=["林栀", "周骁"],
                    covered_event_ids=[],
                    segments=[
                        VideoSegment(
                            segment_id="ch01-sc01-seg01",
                            chapter_number=1,
                            scene_id="ch01-sc01",
                            scene_title="考场里的发现",
                            scene_summary="考试尾声，林栀偷看小册子，被巡视到桌边的周骁无声发现。",
                            scene_anchor="",
                            title="考场里的发现",
                            summary="考试尾声，林栀偷看小册子，被巡视到桌边的周骁无声发现。",
                            involved_characters=["林栀", "周骁"],
                            narration="最后一道题，她还是冒险了。",
                            dialogue_lines=["周骁：认真答题。"],
                            subtitle_lines=["最后一道题，她还是冒险了。", "周骁：认真答题。"],
                            sound_effects=["翻卷声", "笔尖划纸声"],
                            music_direction="低频紧张氛围",
                            timed_beats=[
                                "0-2秒：旁白推进。",
                                "2-6秒：脚步声逼近，空气骤然收紧。",
                            ],
                            start_frame_prompt=(
                                "考场倒数第二排，林栀伏在桌前，手心微汗压着答题卡，"
                                "外套下的小册子被悄悄抽出一角，夕阳落在桌角与膝上"
                            ),
                            end_frame_prompt=(
                                "考场内斜阳压低，周骁站在林栀课桌斜侧；"
                                "周围其他学生仅作模糊背景，不作为出镜主体"
                            ),
                            duration_seconds=6,
                            scene_bible=SceneBible(
                                continuity_notes="保持当前场景的空间、光线和氛围连续性。"
                            ),
                        )
                    ],
                    scene_bible=SceneBible(
                        continuity_notes="保持当前场景的空间、光线和氛围连续性。"
                    ),
                )
            ],
            str(self.temp_root),
        )[0]

        self.assertEqual(prepared.scene_bible.location, "考场")
        self.assertEqual(prepared.scene_bible.time_window, "下午")
        self.assertEqual(prepared.scene_bible.lighting, "夕阳")
        self.assertIn("答题卡", prepared.scene_bible.fixed_props)
        self.assertTrue(any("考场" in item for item in prepared.scene_bible.background_anchors))
        self.assertIn("地点：考场", prepared.scene_master_frame_prompt)
        self.assertIn("时间：下午", prepared.scene_master_frame_prompt)
        self.assertIn("光线：夕阳", prepared.scene_master_frame_prompt)
        self.assertIn("场景基线锁定", prepared.scene_master_frame_prompt)
        self.assertIn("考场", prepared.scene_master_frame_prompt)
        self.assertNotIn("林栀", prepared.scene_master_frame_prompt)
        self.assertNotIn("周骁", prepared.scene_master_frame_prompt)

    def test_prepare_scene_master_frame_filters_unanchored_carried_props(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=8,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )

        prepared = service._prepare_scene_master_frames(
            [
                VideoScene(
                    scene_id="ch01-sc01",
                    chapter_number=1,
                    title="栈道入口等待",
                    summary="主角在栈道入口等待。",
                    scene_anchor="红树林栈道入口，夕阳穿过枝叶",
                    involved_characters=["林远"],
                    covered_event_ids=[],
                    segments=[],
                    scene_bible=SceneBible(
                        location="红树林栈道入口",
                        time_window="傍晚",
                        weather="晴朗，海风轻拂",
                        lighting="夕阳斜照",
                        dominant_palette=["金色", "蓝色"],
                        background_anchors=["木板栈道", "公园入口牌"],
                        fixed_props=["手机", "木质长椅"],
                        spatial_layout="栈道入口连接石板路",
                        continuity_notes="保持入口空间与光线稳定",
                    ),
                )
            ],
            str(self.temp_root),
        )[0]

        self.assertEqual(prepared.scene_bible.fixed_props, ["木质长椅"])
        self.assertNotIn("手机", prepared.scene_master_frame_prompt)

    def test_frame_scene_bible_prompt_context_filters_transient_carried_props(self) -> None:
        service = NovelToVideoService()

        context = service._frame_scene_bible_prompt_context(
            SceneBible(
                location="红树林栈道入口",
                time_window="傍晚",
                weather="晴朗",
                lighting="夕阳斜照",
                dominant_palette=["金色", "蓝色"],
                background_anchors=["木板栈道", "公园入口牌"],
                fixed_props=["手机", "木质长椅"],
                spatial_layout="栈道入口连接石板路",
                continuity_notes="保持入口空间稳定",
            ),
            ["林远"],
            ["林远"],
        )

        self.assertIn("木质长椅", context)
        self.assertNotIn("手机", context)

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

    def test_short_segment_with_too_much_dialogue_is_split_by_speech_budget(self) -> None:
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
                        "segment_id": "confession_01",
                        "chapter_number": 1,
                        "title": "告白测试",
                        "summary": "雨棚下的告白。",
                        "involved_characters": ["林雾", "沈砚"],
                        "narration": "雨声压低了街口的喧哗，她终于停下脚步。",
                        "dialogue_lines": [
                            "林雾：我喜欢你很久了，不是今天才开始，也不是因为这场雨才突然想说。",
                            "沈砚：我听见了，你别急，我也有话想慢慢告诉你。",
                        ],
                        "subtitle_lines": [
                            "我喜欢你很久了，不是今天才开始。",
                            "我听见了，你别急，我也有话想告诉你。",
                        ],
                        "sound_effects": ["雨声"],
                        "music_direction": "克制温柔",
                        "timed_beats": ["0-5秒：两人在雨棚下完成告白对白。"],
                        "start_frame_prompt": "两人在雨棚下对视。",
                        "end_frame_prompt": "沈砚抬眼回应。",
                        "duration_seconds": 5,
                    }
                ]
            }
        )

        normalized = service._normalize_segments_for_seedance(raw_plan)

        self.assertGreater(len(normalized.segments), 1)
        self.assertTrue(all(5 <= item.duration_seconds <= 12 for item in normalized.segments))
        self.assertTrue(any(item.requires_mid_frame for item in normalized.segments))
        self.assertTrue(
            all(item.mid_frame_prompt for item in normalized.segments if item.requires_mid_frame)
        )
        self.assertEqual(
            [item.source_segment_id for item in normalized.segments],
            ["confession_01"] * len(normalized.segments),
        )
        self.assertTrue(all(item.subtitle_lines for item in normalized.segments))
        self.assertTrue(any(item.dialogue_lines for item in normalized.segments[1:]))

    def test_descriptive_narration_is_dropped_before_seedance_split_budget(self) -> None:
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
                        "segment_id": "confession_02",
                        "chapter_number": 1,
                        "title": "递花告白",
                        "summary": "陈默停下脚步，转身面对林晓，双手递上花束。",
                        "involved_characters": ["陈默", "林晓"],
                        "narration": "陈默停下脚步，转身面对林晓，双手递上花束，开始表达暗恋心意。",
                        "dialogue_lines": ["陈默：林晓，我喜欢你一年了。"],
                        "subtitle_lines": ["林晓，我喜欢你一年了。"],
                        "sound_effects": ["风声"],
                        "music_direction": "克制温柔",
                        "timed_beats": ["0-7秒：陈默停下脚步，转身面对林晓，双手递上花束。"],
                        "start_frame_prompt": "陈默递上花束。",
                        "end_frame_prompt": "林晓看向陈默。",
                        "duration_seconds": 7,
                    }
                ]
            }
        )

        normalized = service._normalize_segments_for_seedance(raw_plan)

        self.assertEqual(len(normalized.segments), 1)
        self.assertEqual(normalized.segments[0].segment_id, "confession_02")
        self.assertEqual(normalized.segments[0].narration, "")
        self.assertEqual(
            normalized.segments[0].dialogue_lines,
            ["陈默：林晓，我喜欢你一年了。"],
        )
        self.assertEqual(
            normalized.segments[0].subtitle_lines,
            ["林晓，我喜欢你一年了。"],
        )
        self.assertEqual(normalized.segments[0].duration_seconds, 7)

    def test_normalize_segments_for_seedance_is_idempotent_for_already_prepared_segments(self) -> None:
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
                        "segment_id": "confession_long_01",
                        "chapter_number": 1,
                        "title": "长对白告白",
                        "summary": "两人在雨棚下完成一整轮告白与回应。",
                        "involved_characters": ["林雾", "沈砚"],
                        "narration": "雨声压低了街口的喧哗，她终于停下脚步。",
                        "dialogue_lines": [
                            "林雾：我喜欢你很久了，不是今天才开始，也不是因为这场雨才突然想说。",
                            "沈砚：我听见了，你别急，我也有话想慢慢告诉你。",
                        ],
                        "subtitle_lines": [
                            "我喜欢你很久了，不是今天才开始。",
                            "我听见了，你别急，我也有话想告诉你。",
                        ],
                        "sound_effects": ["雨声"],
                        "music_direction": "克制温柔",
                        "timed_beats": ["0-5秒：两人在雨棚下完成告白对白。"],
                        "start_frame_prompt": "两人在雨棚下对视。",
                        "end_frame_prompt": "沈砚抬眼回应。",
                        "duration_seconds": 5,
                    }
                ]
            }
        )

        first_pass = service._normalize_segments_for_seedance(raw_plan)
        second_pass = service._normalize_segments_for_seedance(first_pass)

        self.assertEqual(
            [item.segment_id for item in first_pass.segments],
            [item.segment_id for item in second_pass.segments],
        )
        self.assertEqual(len(first_pass.segments), len(second_pass.segments))
        self.assertTrue(all("当前子片段" not in item.title for item in second_pass.segments))
        self.assertTrue(all("/ 第" not in item.title for item in second_pass.segments))
        self.assertTrue(
            all(
                "当前为第" not in " ".join(item.subtitle_lines)
                for item in second_pass.segments
            )
        )

    def test_scene_frame_prompts_strip_dialogue_and_subtitle_text(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )

        frame_prompt = service._stylize_frame_prompt(
            '林远说：我喜欢你很久了。屏幕显示：毕业倒计时。',
            ["林远"],
            "首帧",
        )

        self.assertIn("图片1是空场景参考图", frame_prompt)
        self.assertIn("图片2是林远角色参考图", frame_prompt)
        self.assertIn("纯画面，不要文字、字幕、水印或 Logo。", frame_prompt)
        self.assertNotIn("我喜欢你很久了", frame_prompt)
        self.assertNotIn("毕业倒计时", frame_prompt)
        self.assertIn("正在说话", frame_prompt)

    def test_frame_prompt_filters_off_frame_characters_and_style_overrides(self) -> None:
        service = NovelToVideoService()
        frame_prompt = service._stylize_frame_prompt(
            "陈默独自站在长椅旁等待，林晓穿浅蓝连衣裙，头发挽在脑后，从花园尽头走来。",
            ["陈默"],
            "首帧",
            involved_characters=["陈默", "林晓"],
        )

        self.assertIn("长椅旁等待", frame_prompt)
        self.assertNotIn("林晓", frame_prompt)
        self.assertNotIn("浅蓝连衣裙", frame_prompt)
        self.assertNotIn("头发挽在脑后", frame_prompt)

    def test_frame_prompt_filters_multi_character_single_subject_focus_conflict(self) -> None:
        service = NovelToVideoService()
        frame_prompt = service._stylize_frame_prompt(
            "两人并肩站在桥边看向湖面，镜头逐渐推向陈默侧脸特写。",
            ["陈默", "林晓"],
            "中段锚点帧",
            involved_characters=["陈默", "林晓"],
        )

        self.assertIn("两人并肩站在桥边看向湖面", frame_prompt)
        self.assertNotIn("推向陈默侧脸特写", frame_prompt)
        self.assertIn("只画当前帧真正出镜的角色", frame_prompt)

    def test_single_character_frame_prompt_filters_generic_multi_subject_semantics(self) -> None:
        service = NovelToVideoService()
        frame_prompt = service._stylize_frame_prompt(
            "林晓站在柳树下停住脚步，两人在柳树下开始对话。",
            ["林晓"],
            "中段锚点帧",
            involved_characters=["陈默", "林晓"],
        )

        self.assertIn("站在柳树下停住脚步", frame_prompt)
        self.assertNotIn("两人在柳树下开始对话", frame_prompt)

    def test_end_frame_shot_state_context_uses_end_state_lock_without_early_action_chain(self) -> None:
        service = NovelToVideoService()
        shot_state = ShotState(
            framing="中景",
            camera_motion="缓慢平移",
            blocking="陈默起身迎向林晓",
            action_progression="林晓走近，陈默起身，两人开始对话",
            emotion_progression="从紧张到放松",
            prop_continuity="手机仍在长椅旁",
            screen_direction="林晓从左侧入画",
            end_state_lock="两人面对面站定，对话正式开始",
        )

        context = service._frame_shot_state_prompt_context(
            shot_state,
            ["陈默", "林晓"],
            ["陈默", "林晓"],
            frame_type="尾帧",
        )

        self.assertIn("尾帧收在两人面对面站定，对话正式开始", context)
        self.assertNotIn("动作推进", context)
        self.assertNotIn("林晓走近，陈默起身", context)

    def test_mid_frame_prompt_context_ignores_future_action_progression_and_allowed_changes(self) -> None:
        service = NovelToVideoService()
        scene_bible = SceneBible(
            location="镜湖长椅",
            time_window="傍晚",
            weather="微风",
            lighting="湖面对岸暖灯亮起",
            dominant_palette=["暖橙", "深蓝"],
            background_anchors=["镜湖", "长椅", "画架"],
            fixed_props=["木质长椅", "画架"],
            spatial_layout="长椅靠湖，画架在十米外正对湖面",
            continuity_notes="保持长椅和画架的空间关系稳定",
        )
        shot_state = ShotState(
            framing="双人中景",
            camera_motion="稳定双人关系镜头",
            blocking="林晓停在长椅另一侧，和陈默隔着半步相望",
            action_progression="林晓继续走近，随后两人拥抱并亲吻",
            emotion_progression="从紧张停顿推进到确认心意",
            prop_continuity="双手空着",
            screen_direction="两人保持同一条对视轴线",
            end_state_lock="两人靠近后停住",
        )
        continuity_link = ContinuityLink(
            previous_segment_id="seg-1",
            transition_mode="continue",
            opening_match="上一段尾部已经建立两人隔着半步相望的状态",
            carry_over_elements=["长椅", "画架", "对视轴线"],
            allowed_changes="林晓继续靠近，随后两人拥抱并亲吻",
            transition_reason="同一 scene 内的关系推进",
        )

        frame_prompt = service._stylize_frame_prompt(
            "林晓停在长椅另一侧，抬眼看向陈默。",
            ["陈默", "林晓"],
            "中段锚点帧",
            involved_characters=["陈默", "林晓"],
            scene_bible=scene_bible,
            shot_state=shot_state,
            continuity_link=continuity_link,
        )

        self.assertIn("林晓停在长椅另一侧，抬眼看向陈默", frame_prompt)
        self.assertNotIn("随后两人拥抱并亲吻", frame_prompt)
        self.assertNotIn("继续走近", frame_prompt)

    def test_build_local_sound_effects_filters_transient_scene_props(self) -> None:
        service = NovelToVideoService()
        scene_bible = SceneBible(
            location="红树林栈道入口",
            time_window="傍晚",
            weather="海风轻拂",
            lighting="夕阳侧光",
            dominant_palette=["金色", "绿色"],
            background_anchors=["栈道", "红树林"],
            fixed_props=["手机", "木质长椅"],
            spatial_layout="入口连接栈道",
            continuity_notes="保持同一入口空间",
        )

        effects = service._build_local_sound_effects(
            scene_bible,
            ["0-6秒：林远停下脚步后看向栈道深处。"],
        )

        self.assertIn("海风轻拂环境声", effects)
        self.assertIn("木质长椅相关细节声", effects)
        self.assertNotIn("手机相关细节声", effects)

    def test_build_seedance_clip_prompt_omits_subtitle_instructions_for_silent_segment(self) -> None:
        service = NovelToVideoService()
        segment = VideoSegment(
            segment_id="seg-silent",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="红树林栈道",
            scene_summary="主角独自等待。",
            scene_anchor="红树林栈道 / 傍晚 / 海风",
            title="静默等待",
            summary="林远独自站在栈道入口等待。",
            involved_characters=["林远"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=["手机相关细节声", "海风掠过栈道"],
            music_direction="克制青春氛围",
            timed_beats=["0-6秒：林远在栈道入口停住，望向前方。"],
            start_frame_prompt="林远独自站在栈道入口。",
            end_frame_prompt="林远仍站在原地，目光望向前方。",
            duration_seconds=6,
            start_frame_characters=["林远"],
            end_frame_characters=["林远"],
            scene_bible=SceneBible(
                location="红树林栈道入口",
                time_window="傍晚",
                weather="海风轻拂",
                lighting="夕阳侧光",
                dominant_palette=["金色", "绿色"],
                background_anchors=["木板栈道", "红树林"],
                fixed_props=["手机", "木质长椅"],
                spatial_layout="入口连接栈道",
                continuity_notes="保持同一入口空间",
            ),
            shot_state=ShotState(
                framing="中景",
                camera_motion="固定镜头",
                blocking="林远站在入口轻微前倾",
                action_progression="从等待到抬眼观察前方",
                emotion_progression="紧张克制",
                prop_continuity="双手空着，不持任何道具",
                screen_direction="保持面向栈道深处",
                end_state_lock="林远仍停在栈道入口，身体没有明显位移",
            ),
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="开场就是林远独自站在栈道入口等待。",
                carry_over_elements=["栈道入口", "海风"],
                allowed_changes="只允许视线和呼吸节奏发生轻微变化。",
                transition_reason="场景起始段",
            ),
        )

        prompt = service._build_seedance_clip_prompt(segment)

        self.assertIn("本段无对白、无旁白、无字幕", prompt)
        self.assertIn("字幕约束：本段没有可烧录字幕", prompt)
        self.assertIn("参考图绑定：", prompt)
        self.assertIn("图片1 是首帧：林远独自站在栈道入口", prompt)
        self.assertIn("图片2 是尾帧：林远仍站在原地", prompt)
        self.assertIn("画面推进 0-3秒：先按图片1建立", prompt)
        self.assertIn("画面推进 3-6秒：在同一组角色和空间里连续推进", prompt)
        self.assertIn("这一段拍出“林远在栈道入口停住，望向前方”", prompt)
        self.assertNotIn("片段标题：", prompt)
        self.assertNotIn("参考图片时间轴：", prompt)
        self.assertNotIn("硬字幕文案：", prompt)
        self.assertNotIn("请把上述字幕直接烧录到画面底部", prompt)
        self.assertNotIn("手机相关细节声", prompt)

    def test_build_seedance_clip_prompt_describes_insert_cut_mid_frame(self) -> None:
        service = NovelToVideoService()
        segment = VideoSegment(
            segment_id="seg-insert-cut",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="镜湖告白",
            scene_summary="双人对视中切入单人反应特写。",
            scene_anchor="镜湖长椅 / 傍晚 / 微风",
            title="告白停顿",
            summary="双人对视中切入林晚的单人反应特写，再回到双人关系。",
            involved_characters=["陈默", "林晚"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=["微风掠过湖面"],
            music_direction="克制温柔",
            timed_beats=[
                "0-3秒：陈默和林晚在镜湖长椅旁对视。",
                "3-5秒：镜头短促切入林晚的单人反应特写。",
                "5-8秒：镜头切回双人中景，两人重新对视。",
            ],
            start_frame_prompt="陈默和林晚一起停在镜湖长椅旁，保持对视。",
            mid_frame_prompt="短促切入林晚的单人反应特写，她低头后又抬眼。",
            end_frame_prompt="镜头切回后，两人仍停在镜湖长椅旁对视，关系重新稳定。",
            duration_seconds=8,
            start_frame_characters=["陈默", "林晚"],
            mid_frame_characters=["林晚"],
            mid_frame_mode="insert_cut",
            end_frame_characters=["陈默", "林晚"],
            requires_mid_frame=True,
            scene_bible=SceneBible(
                location="镜湖长椅",
                time_window="傍晚",
                weather="微风",
                lighting="暖金色侧光",
                dominant_palette=["暖金", "湖蓝"],
                background_anchors=["镜湖", "长椅", "步道"],
                spatial_layout="长椅靠湖，步道从右侧延伸",
                continuity_notes="保持长椅与湖面透视稳定",
            ),
            shot_state=ShotState(
                framing="双人中景建立关系后，中段短促切入单人反应特写，再回到双人中景",
                camera_motion="先稳定双人关系镜头，再自然切入中段单人反应特写，最后切回双人主镜头",
                blocking="两人面对面站定，中段只切入林晚的面部与肩线反应",
                action_progression="从对视停顿推进到林晚的情绪反应，再回到双人对视",
                emotion_progression="从紧张停顿推进到情绪确认",
                screen_direction="保持两人的对视轴线稳定",
                end_state_lock="镜头切回后，两人维持稳定对视姿态",
            ),
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="开场就是陈默和林晚在镜湖长椅旁对视。",
                carry_over_elements=["镜湖长椅", "对视关系"],
                allowed_changes="在双人对视中插入林晚的单人情绪反应，再回到两人对视。",
                transition_reason="场景起始段",
            ),
            motion_plan=MotionPlan(
                start_to_mid="从双人主镜头切入林晚反应特写，切入前先保持陈默和林晚的对视关系。",
                mid_to_end="林晚抬眼后切回双人中景，让陈默和林晚重新落回同一条对视轴线。",
                camera_path="主镜头短切插入再切回，不要停成静态图。",
                character_motion="林晚低头后抬眼，陈默仍留在主镜头关系中。",
                continuity_guard="图片2 是插入特写，不要把它误拍成少了陈默的主关系镜头。",
            ),
        )

        prompt = service._build_seedance_clip_prompt(segment)

        self.assertIn("参考图绑定：", prompt)
        self.assertIn("图片1 是首帧：陈默和林晚一起停在镜湖长椅旁", prompt)
        self.assertIn("图片2 是中段帧：短促切入林晚的单人反应特写", prompt)
        self.assertIn("图片3 是尾帧：镜头切回后，两人仍停在镜湖长椅旁对视", prompt)
        self.assertIn("画面推进 0-3秒：先按图片1建立", prompt)
        self.assertIn("画面推进 3-5秒：再短促切到图片2", prompt)
        self.assertIn("画面推进 5-8秒：最后明确切回图片3", prompt)
        self.assertIn("这一段拍出“镜头短促切入林晚的单人反应特写”", prompt)
        self.assertIn("推进细节：从双人主镜头切入林晚反应特写", prompt)
        self.assertIn("林晚抬眼后切回双人中景", prompt)
        self.assertIn("插入镜头：图片2 只切 林晚 的反应或局部动作", prompt)
        self.assertNotIn("图片2 是插入镜头", prompt)

    def test_build_seedance_clip_prompt_includes_scene_transition_contract_on_scene_entry(self) -> None:
        service = NovelToVideoService()
        segment = VideoSegment(
            segment_id="ch01-sc02-seg01",
            chapter_number=1,
            scene_id="ch01-sc02",
            scene_title="镜湖步道",
            scene_summary="两人从花廊出口走入镜湖步道。",
            scene_anchor="镜湖步道 / 傍晚 / 微风",
            title="走入镜湖",
            summary="两人从花廊出口继续走入镜湖步道。",
            involved_characters=["陈默", "林晚"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=["晚风", "脚步声"],
            music_direction="克制温柔",
            timed_beats=[
                "0-3秒：先承接两人并肩前行的状态。",
                "3-6秒：镜湖步道与栏杆逐渐显露出来。",
            ],
            start_frame_prompt="两人保持上一场并肩前行的姿态，刚走入镜湖步道。",
            end_frame_prompt="两人在镜湖步道上放慢脚步，栏杆和湖面稳定入画。",
            duration_seconds=6,
            start_frame_characters=["陈默", "林晚"],
            end_frame_characters=["陈默", "林晚"],
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="开场先承接两人并肩前行的状态，再带出镜湖步道。",
                carry_over_elements=["并肩关系", "向右前方行进"],
                allowed_changes="从花廊出口过渡到镜湖步道空间。",
                transition_reason="新 scene 首段继续承接上一场尾部。",
            ),
        )
        scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="镜湖步道",
            summary="两人从花廊出口走入镜湖步道。",
            scene_anchor="镜湖步道 / 傍晚 / 微风",
            involved_characters=["陈默", "林晚"],
            covered_event_ids=[],
            segments=[segment],
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="adjacent_move",
                previous_scene_exit_state="两人刚从花廊下并肩迈步离开，仍保持沉默前行。",
                next_scene_entry_match="当前场开头先承接两人并肩前行的状态，再带出镜湖步道。",
                bridge_action="先跟着两人离开花廊出口，再顺势露出镜湖步道和栏杆。",
                carry_over_elements=["并肩关系", "沉默未散", "向右前方行进"],
                screen_direction_policy="继续保持向右前方行进，不要突然反向。",
                visual_bridge="先看肩线和脚步，再 reveal 镜湖步道与栏杆。",
                audio_bridge="ambient_bridge",
                transition_focus_seconds=2,
            ),
        )

        prompt = service._build_seedance_clip_prompt(segment, scene=scene)

        self.assertIn("这是当前 scene 的首段", prompt)
        self.assertIn("前 2 秒先把图片1 长成", prompt)
        self.assertIn("先跟着两人离开花廊出口，再顺势露出镜湖步道和栏杆", prompt)
        self.assertIn("视觉过桥：先看肩线和脚步，再 reveal 镜湖步道与栏杆", prompt)
        self.assertIn("音频承接：开头先延续上一场环境底噪或空间尾韵", prompt)

    def test_validate_segment_plan_output_rejects_direction_conflict(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        service = NovelToVideoService()
        plan = VideoSegmentPlanSchema.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "title": "红树林入口",
                        "summary": "主角沿着栈道继续前进。",
                        "scene_anchor": "红树林栈道入口 / 傍晚 / 海风",
                        "scene_bible": {
                            "location": "红树林栈道入口",
                            "time_window": "傍晚",
                            "weather": "海风轻拂",
                            "lighting": "夕阳侧光",
                            "dominant_palette": ["金色", "绿色"],
                            "background_anchors": ["木板栈道", "红树林"],
                            "fixed_props": ["木质长椅"],
                            "spatial_layout": "入口连接栈道",
                            "character_blocking": "林远站在入口准备迈步",
                            "continuity_notes": "保持入口到栈道深处的纵深关系",
                        },
                        "involved_characters": ["林远"],
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "scene_title": "红树林入口",
                                "scene_summary": "主角沿着栈道继续前进。",
                                "scene_anchor": "红树林栈道入口 / 傍晚 / 海风",
                                "scene_bible": {
                                    "location": "红树林栈道入口",
                                    "time_window": "傍晚",
                                    "weather": "海风轻拂",
                                    "lighting": "夕阳侧光",
                                    "dominant_palette": ["金色", "绿色"],
                                    "background_anchors": ["木板栈道", "红树林"],
                                    "fixed_props": ["木质长椅"],
                                    "spatial_layout": "入口连接栈道",
                                    "character_blocking": "林远站在入口准备迈步",
                                    "continuity_notes": "保持入口到栈道深处的纵深关系",
                                },
                                "title": "向栈道深处走去",
                                "summary": "林远沿着栈道向红树林深处走去。",
                                "involved_characters": ["林远"],
                                "start_frame_characters": ["林远"],
                                "mid_frame_characters": ["林远"],
                                "end_frame_characters": ["林远"],
                                "narration": "",
                                "dialogue_lines": [],
                                "subtitle_lines": [],
                                "sound_effects": ["海风掠过栈道"],
                                "music_direction": "克制青春氛围",
                                "timed_beats": ["0-8秒：林远沿着栈道向红树林深处走去，背影逐渐远去。"],
                                "start_frame_prompt": "林远从栈道入口起步。",
                                "mid_frame_prompt": "林远沿着栈道继续前进。",
                                "end_frame_prompt": "林远的背影逐渐远去，走向红树林深处。",
                                "duration_seconds": 8,
                                "requires_mid_frame": True,
                                "transition_hint": "continue",
                                "shot_state": {
                                    "framing": "中景",
                                    "camera_motion": "缓慢跟拍",
                                    "blocking": "林远沿着栈道前进",
                                    "action_progression": "从起步到继续深入栈道",
                                    "emotion_progression": "从紧张到下定决心",
                                    "prop_continuity": "双手空着",
                                    "screen_direction": "从画面深处向浅处行走，逐渐靠近镜头",
                                    "end_state_lock": "林远的背影逐渐远去，走向红树林深处。",
                                },
                                "continuity_link": {
                                    "previous_segment_id": "",
                                    "transition_mode": "start",
                                    "opening_match": "林远已站在栈道入口准备迈步。",
                                    "carry_over_elements": ["栈道入口", "海风"],
                                    "allowed_changes": "允许林远继续向深处前进。",
                                    "transition_reason": "场景起始段",
                                },
                            }
                        ],
                    }
                ],
                "segments": [],
            }
        )
        plan = plan.model_copy(update={"segments": [plan.scenes[0].segments[0]]})

        with self.assertRaisesRegex(ValueError, "screen_direction 与尾部收束方向冲突"):
            service._validate_segment_plan_output(
                plan,
                novel_package=story_result.novel_package,
                expected_chapter_numbers={1},
            )

    def test_scene_bible_shot_state_and_continuity_context_are_injected_into_scene_and_video_prompts(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService(
            segment_duration_seconds=config.video.segment_duration_seconds,
            aspect_ratio=config.video.aspect_ratio,
            fps=config.video.fps,
            character_image_provider=config.video.character_image_provider,
            scene_image_provider=config.video.scene_image_provider,
            seedance_config=config.seedance,
        )
        scene_bible = SceneBible(
            location="紫藤花廊",
            time_window="傍晚",
            weather="晚风",
            lighting="夕阳暖光",
            dominant_palette=["暖金", "藤紫"],
            background_anchors=["紫藤花架", "花园石径"],
            fixed_props=["毕业纪念册"],
            spatial_layout="紫藤花架在前景，石径向远处延伸",
            character_blocking="林远靠左等待，苏晴从右后方走近",
            continuity_notes="保持花架、石径和角色出入口方向稳定",
        )
        shot_state = ShotState(
            framing="中景双人关系镜头",
            camera_motion="缓慢推进，保持稳定轴线",
            blocking="林远靠左等待，苏晴从右后方走近后停在他面前",
            action_progression="从等待到转身看见对方",
            emotion_progression="从紧张到确认对方到来",
            prop_continuity="毕业纪念册始终握在林远手中",
            screen_direction="苏晴从画面右侧向左接近，林远视线由前方转向右侧",
            end_state_lock="两人在花架下停住并形成稳定对视关系",
        )
        continuity_link = ContinuityLink(
            previous_segment_id="seg-1",
            transition_mode="continue",
            opening_match="开场先承接上一段尾部，两人仍停在花架下的对视前状态",
            carry_over_elements=["角色站位", "视线方向", "毕业纪念册"],
            allowed_changes="苏晴继续向前半步，关系进入直接对视",
            transition_reason="同一场景里的连续推进",
        )
        segment = VideoSegment(
            segment_id="seg-2",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="紫藤花廊",
            scene_summary="毕业前夕的等待与相遇。",
            scene_anchor="紫藤花架 / 傍晚 / 夕阳 / 花园石径",
            title="相遇片段",
            summary="林远在花廊里等苏晴。",
            involved_characters=["林远", "苏晴"],
            narration="林远站在紫藤花架下，等她出现。",
            dialogue_lines=["林远：你终于来了。"],
            subtitle_lines=["你终于来了。"],
            sound_effects=["晚风", "花叶摩擦"],
            music_direction="青春克制",
            timed_beats=["0-5秒：林远转身看向苏晴。"],
            start_frame_prompt="林远站在花架下等待。",
            end_frame_prompt="苏晴走近后，林远转身看向她。",
            duration_seconds=5,
            scene_bible=scene_bible,
            shot_state=shot_state,
            continuity_link=continuity_link,
        )

        frame_prompt = service._stylize_frame_prompt(
            segment.start_frame_prompt,
            ["林远"],
            "首帧",
            involved_characters=segment.involved_characters,
            scene_bible=scene_bible,
            shot_state=shot_state,
            continuity_link=continuity_link,
        )
        video_prompt = service._build_seedance_clip_prompt(segment)

        self.assertIn("图片1是空场景参考图", frame_prompt)
        self.assertIn("图片2是林远角色参考图", frame_prompt)
        self.assertIn("紫藤花架", frame_prompt)
        self.assertNotIn("缓慢推进", frame_prompt)
        self.assertNotIn("苏晴", frame_prompt)
        self.assertIn("开场先承接", frame_prompt)
        self.assertIn("参考图绑定", video_prompt)
        self.assertIn("图片1", video_prompt)
        self.assertIn("图片2", video_prompt)
        self.assertIn("林远站在花架下等待", video_prompt)
        self.assertIn("这一段口播：旁白：林远站在紫藤花架下，等她出现。", video_prompt)
        self.assertIn("这一段口播：对白：林远：你终于来了。", video_prompt)
        self.assertNotIn("场景与基线", video_prompt)
        self.assertNotIn("镜头与动作", video_prompt)
        self.assertNotIn("承接要求", video_prompt)

    def test_repair_scene_bible_backfills_missing_fields_from_scene_context(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "scenes": [
                    {
                        "scene_id": "ch01-sc01",
                        "chapter_number": 1,
                        "title": "紫藤花廊",
                        "summary": "傍晚花廊里的等待与相遇。",
                        "scene_anchor": "紫藤花架 / 傍晚 / 夕阳 / 花园石径",
                        "scene_bible": {},
                        "involved_characters": ["林远", "苏晴"],
                        "segments": [
                            {
                                "segment_id": "ch01-sc01-seg01",
                                "chapter_number": 1,
                                "scene_id": "ch01-sc01",
                                "scene_title": "紫藤花廊",
                                "scene_summary": "傍晚花廊里的等待与相遇。",
                                "scene_anchor": "紫藤花架 / 傍晚 / 夕阳 / 花园石径",
                                "scene_bible": {},
                                "title": "等待",
                                "summary": "林远站在花架下等待苏晴。",
                                "involved_characters": ["林远", "苏晴"],
                                "start_frame_characters": ["林远"],
                                "mid_frame_characters": ["林远", "苏晴"],
                                "end_frame_characters": ["林远", "苏晴"],
                                "narration": "林远在花架下等她。",
                                "dialogue_lines": ["林远：你终于来了。"],
                                "subtitle_lines": ["你终于来了。"],
                                "sound_effects": ["晚风"],
                                "music_direction": "青春克制",
                                "timed_beats": ["0-5秒：林远看向花园小径。"],
                                "start_frame_prompt": "林远站在花架下。",
                                "mid_frame_prompt": "苏晴从石径尽头走近。",
                                "end_frame_prompt": "两人在花架下对视。",
                                "duration_seconds": 5,
                                "requires_mid_frame": True,
                            }
                        ],
                    }
                ]
            }
        )

        repaired = service._repair_scene_bibles(raw_plan, story_result.novel_package)

        self.assertTrue(repaired.scenes[0].scene_bible.location)
        self.assertTrue(repaired.scenes[0].scene_bible.continuity_notes)
        self.assertTrue(repaired.segments[0].scene_bible.background_anchors)

    def test_segment_contract_normalization_backfills_motion_plan(self) -> None:
        plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "scene_title": "松林入口",
                        "scene_summary": "林屿在入口等待苏晚。",
                        "scene_anchor": "松林入口 / 傍晚",
                        "title": "入口等待",
                        "summary": "林屿从低头等待到抬头看见苏晚。",
                        "involved_characters": ["林屿", "苏晚"],
                        "start_frame_characters": ["林屿"],
                        "mid_frame_characters": ["林屿", "苏晚"],
                        "end_frame_characters": ["林屿", "苏晚"],
                        "narration": "",
                        "dialogue_lines": [],
                        "subtitle_lines": [],
                        "timed_beats": [
                            "0-3秒：林屿站在松林入口等待。",
                            "3-6秒：苏晚从小径尽头入画。",
                            "6-8秒：两人在入口处停下对视。",
                        ],
                        "duration_seconds": 8,
                        "requires_mid_frame": True,
                        "start_frame_prompt": "林屿独自站在松林入口。",
                        "mid_frame_prompt": "苏晚从小径尽头入画，林屿抬头看见她。",
                        "end_frame_prompt": "林屿和苏晚在入口处停下对视。",
                        "shot_state": {
                            "camera_motion": "固定机位轻微前推",
                            "blocking": "林屿在入口左侧，苏晚从右侧小径进入。",
                            "action_progression": "从等待到苏晚入画，再到两人对视。",
                        },
                        "continuity_link": {},
                    }
                ]
            }
        )

        segment = plan.segments[0]

        self.assertIn("林屿站在松林入口等待", segment.motion_plan.start_to_mid)
        self.assertIn("苏晚从小径尽头入画", segment.motion_plan.start_to_mid)
        self.assertIn("两人在入口处停下对视", segment.motion_plan.mid_to_end)
        self.assertEqual(segment.motion_plan.camera_path, "固定机位轻微前推")
        self.assertIn("避免突然换景", segment.motion_plan.continuity_guard)

    def test_repair_shot_state_backfills_missing_fields_from_segment_context(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
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
        raw_plan = VideoSegmentPlanSchema.model_validate(
            {
                "segments": [
                    {
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "scene_title": "紫藤花廊",
                        "scene_summary": "傍晚花廊里的等待与相遇。",
                        "scene_anchor": "紫藤花架 / 傍晚 / 夕阳 / 花园石径",
                        "scene_bible": {
                            "location": "紫藤花廊",
                            "time_window": "傍晚",
                        },
                        "shot_state": {},
                        "title": "等待",
                        "summary": "林远站在花架下等待苏晴。",
                        "involved_characters": ["林远", "苏晴"],
                        "start_frame_characters": ["林远"],
                        "mid_frame_characters": ["林远", "苏晴"],
                        "end_frame_characters": ["林远", "苏晴"],
                        "narration": "林远在花架下等她。",
                        "dialogue_lines": ["林远：你终于来了。"],
                        "subtitle_lines": ["你终于来了。"],
                        "sound_effects": ["晚风"],
                        "music_direction": "青春克制",
                        "timed_beats": ["0-5秒：林远看向花园小径。"],
                        "start_frame_prompt": "林远站在花架下。",
                        "mid_frame_prompt": "苏晴从石径尽头走近。",
                        "end_frame_prompt": "两人在花架下对视。",
                        "duration_seconds": 5,
                        "requires_mid_frame": True,
                    }
                ]
            }
        )

        repaired = service._repair_shot_states(raw_plan, story_result.novel_package)

        self.assertTrue(repaired.segments[0].shot_state.framing)
        self.assertTrue(repaired.segments[0].shot_state.blocking)
        self.assertTrue(repaired.segments[0].shot_state.end_state_lock)

    def test_repair_continuity_link_backfills_from_adjacent_segment_context(self) -> None:
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
                        "segment_id": "ch01-sc01-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "scene_title": "雪港巷道",
                        "scene_summary": "林雪逃入巷道并持续前冲。",
                        "scene_anchor": "雪港巷道 / 夜色 / 冷色调 / 持续奔跑",
                        "scene_bible": {
                            "location": "雪港巷道",
                            "time_window": "夜晚",
                            "background_anchors": ["巷道积雪", "远处冷灯"],
                        },
                        "shot_state": {
                            "blocking": "林雪沿巷道向前冲",
                            "screen_direction": "从画面左后向右前推进",
                            "prop_continuity": "围巾始终甩在身后",
                            "end_state_lock": "林雪回头确认追兵位置后继续保持前冲姿态",
                        },
                        "title": "片段一",
                        "summary": "林雪冲进雪港巷道。",
                        "involved_characters": ["林雪"],
                        "narration": "林雪在巷道里逃亡。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["林雪在巷道里逃亡。"],
                        "sound_effects": ["脚步声"],
                        "music_direction": "紧张",
                        "timed_beats": ["0-5秒：林雪冲进巷道。"],
                        "start_frame_prompt": "林雪进入巷道。",
                        "end_frame_prompt": "林雪回头确认追兵位置。",
                        "duration_seconds": 5,
                        "continuity_link": {},
                    },
                    {
                        "segment_id": "ch01-sc01-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc01",
                        "scene_title": "雪港巷道",
                        "scene_summary": "林雪逃入巷道并持续前冲。",
                        "scene_anchor": "雪港巷道 / 夜色 / 冷色调 / 持续奔跑",
                        "scene_bible": {
                            "location": "雪港巷道",
                            "time_window": "夜晚",
                            "background_anchors": ["巷道积雪", "远处冷灯"],
                        },
                        "shot_state": {
                            "end_state_lock": "林雪继续前冲并逼近巷口",
                        },
                        "title": "片段二",
                        "summary": "林雪继续沿着同一条巷道前进。",
                        "involved_characters": ["林雪"],
                        "narration": "她没有停下，只能继续向前。",
                        "dialogue_lines": [],
                        "subtitle_lines": ["她没有停下，只能继续向前。"],
                        "sound_effects": ["急促呼吸"],
                        "music_direction": "紧张",
                        "timed_beats": ["0-5秒：林雪继续前冲。"],
                        "start_frame_prompt": "延续上一镜头，林雪继续奔跑。",
                        "end_frame_prompt": "林雪冲向巷口。",
                        "duration_seconds": 5,
                        "continuity_link": {},
                    },
                ]
            }
        )

        repaired = service._repair_continuity_links(raw_plan)

        self.assertEqual(repaired.segments[0].continuity_link.transition_mode, "start")
        self.assertEqual(repaired.segments[1].continuity_link.transition_mode, "continue")
        self.assertEqual(repaired.segments[1].continuity_link.previous_segment_id, "ch01-sc01-seg01")
        self.assertIn(
            "林雪回头确认追兵位置后继续保持前冲姿态",
            repaired.segments[1].continuity_link.opening_match,
        )
        self.assertIn("上一段尾部动作定格", repaired.segments[1].continuity_link.carry_over_elements)
        self.assertIn("推进到", repaired.segments[1].continuity_link.allowed_changes)
        self.assertIn("林雪继续沿着同一条巷道前进", repaired.segments[1].continuity_link.allowed_changes)

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
                segment_id="ch01-sc01-seg01",
                chapter_number=1,
                scene_id="ch01-sc01",
                scene_title="雪港巷道",
                scene_summary="林雪逃入巷道并持续前冲。",
                scene_anchor="雪港巷道 / 夜色 / 冷色调 / 持续奔跑",
                title="片段一",
                summary="林雪冲进雪港巷道。",
                involved_characters=["林雪"],
                narration="林雪在巷道里逃亡。",
                dialogue_lines=[],
                subtitle_lines=["林雪在巷道里逃亡。"],
                sound_effects=["脚步声"],
                music_direction="紧张",
                timed_beats=["0-5秒：林雪冲进巷道。"],
                start_frame_prompt="林雪进入巷道。",
                end_frame_prompt="林雪回头确认追兵位置。",
                duration_seconds=5,
                transition_hint="auto",
                source_segment_id="ch01-seg01",
            ),
            VideoSegment(
                segment_id="ch01-sc01-seg02",
                chapter_number=1,
                scene_id="ch01-sc01",
                scene_title="雪港巷道",
                scene_summary="林雪逃入巷道并持续前冲。",
                scene_anchor="雪港巷道 / 夜色 / 冷色调 / 持续奔跑",
                title="片段二",
                summary="林雪继续沿着同一条巷道前进。",
                involved_characters=["林雪"],
                narration="她没有停下，只能继续向前。",
                dialogue_lines=[],
                subtitle_lines=["她没有停下，只能继续向前。"],
                sound_effects=["急促呼吸"],
                music_direction="紧张",
                timed_beats=["0-5秒：林雪继续前冲。"],
                start_frame_prompt="延续上一镜头，林雪继续奔跑。",
                end_frame_prompt="林雪冲向巷口。",
                duration_seconds=5,
                transition_hint="auto",
                source_segment_id="ch01-seg02",
            ),
            VideoSegment(
                segment_id="ch01-sc02-seg01",
                chapter_number=1,
                scene_id="ch01-sc02",
                scene_title="哨塔警报",
                scene_summary="镜头切到另一边的哨塔。",
                scene_anchor="哨塔 / 红灯 / 警报杆",
                title="片段三",
                summary="与此同时，另一边的哨塔响起警报。",
                involved_characters=["哨兵"],
                narration="转场到哨塔，警报声突然响起。",
                dialogue_lines=[],
                subtitle_lines=["转场到哨塔，警报声突然响起。"],
                sound_effects=["警报声"],
                music_direction="压迫",
                timed_beats=["0-5秒：哨塔警报。"],
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
                portrait_prompt="测试角色图",
            ),
            CharacterVisualProfile(
                name="哨兵",
                role="守卫",
                gender="男",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            ),
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}
        scenes = service._prepare_scene_master_frames(
            [
                VideoScene(
                    scene_id="ch01-sc01",
                    chapter_number=1,
                    title="雪港巷道",
                    summary="林雪逃入巷道并持续前冲。",
                    scene_anchor="雪港巷道 / 夜色 / 冷色调 / 持续奔跑",
                    involved_characters=["林雪"],
                    covered_event_ids=[],
                    segments=list(segments[:2]),
                ),
                VideoScene(
                    scene_id="ch01-sc02",
                    chapter_number=1,
                    title="哨塔警报",
                    summary="镜头切到另一边的哨塔。",
                    scene_anchor="哨塔 / 红灯 / 警报杆",
                    involved_characters=["哨兵"],
                    covered_event_ids=[],
                    segments=[segments[2]],
                ),
            ],
            str(self.temp_root),
        )

        scene_tasks = service._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertEqual(scene_tasks[0].continuity_source_segment_id, "")
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "ch01-sc01-seg01")
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[2].continuity_source_segment_id, "")
        self.assertFalse(scene_tasks[2].reuse_previous_end_frame)
        self.assertTrue(all(item.scene_master_frame_path.endswith("_master.png") for item in scene_tasks))

    def test_persisted_reuse_flag_for_normal_continuous_segment_still_reuses_previous_end_frame(self) -> None:
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
                segment_id="ch01-sc01-seg01",
                chapter_number=1,
                scene_id="ch01-sc01",
                scene_title="玫瑰园入口",
                scene_summary="陈默等待林薇到来。",
                scene_anchor="玫瑰园入口 / 傍晚 / 金色侧光",
                title="等待",
                summary="陈默独自等待。",
                involved_characters=["陈默"],
                narration="陈默站在入口处等待。",
                dialogue_lines=[],
                subtitle_lines=["陈默站在入口处等待。"],
                sound_effects=["微风"],
                music_direction="温柔",
                timed_beats=["0-5秒：陈默等待。"],
                start_frame_prompt="陈默站在入口处。",
                end_frame_prompt="陈默保持等待姿势，看向前方。",
                duration_seconds=5,
                transition_hint="auto",
                source_segment_id="ch01-sc01-seg01",
                continuity_link=ContinuityLink(
                    previous_segment_id="",
                    transition_mode="start",
                    opening_match="",
                    carry_over_elements=[],
                    allowed_changes="新场景开始",
                    transition_reason="陈默独自等待",
                ),
            ),
            VideoSegment(
                segment_id="ch01-sc01-seg02",
                chapter_number=1,
                scene_id="ch01-sc01",
                scene_title="玫瑰园入口",
                scene_summary="陈默等待林薇到来。",
                scene_anchor="玫瑰园入口 / 傍晚 / 金色侧光",
                title="到来",
                summary="林薇走近，陈默转身看向她。",
                involved_characters=["陈默", "林薇"],
                narration="林薇从另一端走来。",
                dialogue_lines=["陈默！"],
                subtitle_lines=["陈默！"],
                sound_effects=["脚步声"],
                music_direction="温柔",
                timed_beats=["0-5秒：林薇走近。"],
                start_frame_prompt="陈默保持上一段尾部等待姿势。",
                end_frame_prompt="两人面对面站立。",
                duration_seconds=5,
                transition_hint="continue",
                source_segment_id="ch01-sc01-seg02",
                reuse_previous_end_frame=True,
                continuity_link=ContinuityLink(
                    previous_segment_id="ch01-sc01-seg01",
                    transition_mode="continue",
                    opening_match="陈默保持等待姿势，面向前方。",
                    carry_over_elements=["陈默的站姿", "玫瑰园入口背景", "夕阳光线"],
                    allowed_changes="林薇入画，陈默转身看向她。",
                    transition_reason="林薇到来，动作连续推进",
                ),
            ),
        ]
        character_profiles = [
            CharacterVisualProfile(
                name="陈默",
                role="男主",
                gender="男",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            ),
            CharacterVisualProfile(
                name="林薇",
                role="女主",
                gender="女",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            ),
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}
        scenes = service._prepare_scene_master_frames(
            [
                VideoScene(
                    scene_id="ch01-sc01",
                    chapter_number=1,
                    title="玫瑰园入口",
                    summary="陈默等待林薇到来。",
                    scene_anchor="玫瑰园入口 / 傍晚 / 金色侧光",
                    involved_characters=["陈默", "林薇"],
                    covered_event_ids=[],
                    segments=list(segments),
                )
            ],
            str(self.temp_root),
        )

        scene_tasks = service._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertFalse(scene_tasks[0].reuse_previous_end_frame)
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "ch01-sc01-seg01")

    def test_scene_image_tasks_attach_previous_scene_tail_as_transition_anchor(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        service = NovelToVideoService()
        segments = [
            VideoSegment(
                segment_id="ch01-sc01-seg01",
                chapter_number=1,
                scene_id="ch01-sc01",
                scene_title="花廊出口",
                scene_summary="两人从花廊离开。",
                scene_anchor="花廊出口 / 傍晚 / 侧光",
                title="离开花廊",
                summary="陈默和林晚并肩离开花廊。",
                involved_characters=["陈默", "林晚"],
                narration="",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=["0-6秒：两人并肩离开花廊出口。"],
                start_frame_prompt="两人站在花廊出口，正准备迈步离开。",
                end_frame_prompt="两人已经并肩迈步离开花廊，朝镜湖方向前进。",
                duration_seconds=6,
                start_frame_characters=["陈默", "林晚"],
                end_frame_characters=["陈默", "林晚"],
                continuity_link=ContinuityLink(
                    previous_segment_id="",
                    transition_mode="start",
                    opening_match="开场就是两人站在花廊出口。",
                    carry_over_elements=["花廊出口"],
                    allowed_changes="两人并肩离开花廊。",
                    transition_reason="scene 起始",
                ),
            ),
            VideoSegment(
                segment_id="ch01-sc02-seg01",
                chapter_number=1,
                scene_id="ch01-sc02",
                scene_title="镜湖步道",
                scene_summary="两人继续走向镜湖。",
                scene_anchor="镜湖步道 / 傍晚 / 微风",
                title="走入镜湖",
                summary="两人从花廊出口继续走入镜湖步道。",
                involved_characters=["陈默", "林晚"],
                narration="",
                dialogue_lines=[],
                subtitle_lines=[],
                sound_effects=[],
                music_direction="",
                timed_beats=[
                    "0-3秒：先承接两人并肩前行的状态。",
                    "3-6秒：镜湖步道与栏杆逐渐显露出来。",
                ],
                start_frame_prompt="两人保持上一场并肩前行的姿态，刚走入镜湖步道。",
                end_frame_prompt="两人在镜湖步道上放慢脚步，栏杆和湖面稳定入画。",
                duration_seconds=6,
                start_frame_characters=["陈默", "林晚"],
                end_frame_characters=["陈默", "林晚"],
                continuity_link=ContinuityLink(
                    previous_segment_id="",
                    transition_mode="start",
                    opening_match="开场先承接两人并肩前行的状态，再带出镜湖步道。",
                    carry_over_elements=["并肩关系", "向右前方行进"],
                    allowed_changes="从花廊出口过渡到镜湖步道空间。",
                    transition_reason="新 scene 首段继续承接上一场尾部。",
                ),
            ),
        ]
        character_profiles = [
            CharacterVisualProfile(
                name="陈默",
                role="男主",
                gender="男",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            ),
            CharacterVisualProfile(
                name="林晚",
                role="女主",
                gender="女",
                appearance="测试外观",
                outfit="测试服装",
                portrait_prompt="测试角色图",
            ),
        ]
        character_images = service._build_character_image_tasks(character_profiles, str(self.temp_root))
        profile_map = {item.name: item for item in character_profiles}
        scenes = service._prepare_scene_master_frames(
            [
                VideoScene(
                    scene_id="ch01-sc01",
                    chapter_number=1,
                    title="花廊出口",
                    summary="两人离开花廊。",
                    scene_anchor="花廊出口 / 傍晚 / 侧光",
                    involved_characters=["陈默", "林晚"],
                    covered_event_ids=[],
                    segments=[segments[0]],
                ),
                VideoScene(
                    scene_id="ch01-sc02",
                    chapter_number=1,
                    title="镜湖步道",
                    summary="两人走入镜湖步道。",
                    scene_anchor="镜湖步道 / 傍晚 / 微风",
                    involved_characters=["陈默", "林晚"],
                    covered_event_ids=[],
                    segments=[segments[1]],
                    scene_transition_contract=SceneTransitionContract(
                        previous_scene_id="ch01-sc01",
                        transition_mode="adjacent_move",
                        previous_scene_exit_state="两人已经并肩迈步离开花廊，朝镜湖方向前进。",
                        next_scene_entry_match="当前场开头先承接两人并肩前行的状态，再带出镜湖步道。",
                        bridge_action="先跟着两人离开花廊出口，再顺势露出镜湖步道和栏杆。",
                        carry_over_elements=["并肩关系", "向右前方行进"],
                        screen_direction_policy="继续保持向右前方行进。",
                        visual_bridge="先看肩线和脚步，再 reveal 镜湖步道栏杆。",
                        audio_bridge="ambient_bridge",
                        transition_focus_seconds=2,
                    ),
                ),
            ],
            str(self.temp_root),
        )

        scene_tasks = service._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            str(self.temp_root),
        )

        self.assertEqual(scene_tasks[1].scene_transition_source_segment_id, "ch01-sc01-seg01")
        self.assertFalse(scene_tasks[1].reuse_previous_end_frame)

        scene_tasks[0].end_frame_url = "https://example.com/ch01-sc01-seg01-end.png"
        client = SeedreamClient(config.seedream)
        temporal_urls = client._resolve_start_temporal_anchor_urls(
            scene_tasks[1],
            {item.segment_id: item for item in scene_tasks},
        )

        self.assertEqual(temporal_urls, ["https://example.com/ch01-sc01-seg01-end.png"])

    def test_write_continuity_report_flags_weak_opening_match_and_duplicate_adjacent_segment(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        scene_plan_payload = read_json(story_result.scene_plan_path)
        target_scene = next(
            (item for item in scene_plan_payload["scenes"] if len(item.get("segments", [])) >= 2),
            None,
        )
        if target_scene is None:
            target_scene = scene_plan_payload["scenes"][0]
            first_segment = target_scene["segments"][0]
            second_segment = json.loads(json.dumps(first_segment, ensure_ascii=False))
            second_segment["segment_id"] = first_segment["segment_id"] + "-dup"
            second_segment["title"] = first_segment["title"] + "续"
            target_scene["segments"].append(second_segment)
        else:
            first_segment = target_scene["segments"][0]
            second_segment = target_scene["segments"][1]

        first_segment["shot_state"]["end_state_lock"] = "林远停在花架下，右手仍握着信封，没有迈步。"
        second_segment["continuity_link"]["transition_mode"] = "continue"
        second_segment["continuity_link"]["previous_segment_id"] = first_segment["segment_id"]
        second_segment["continuity_link"]["opening_match"] = "承接上一段继续。"
        second_segment["continuity_link"]["allowed_changes"] = "继续保持承接状态。"
        second_segment["summary"] = first_segment["summary"]
        second_segment["shot_state"]["action_progression"] = "林远停在花架下，右手仍握着信封，没有迈步。"
        second_segment["timed_beats"] = list(first_segment["timed_beats"])

        story_result.scene_plan_path.write_text(
            json.dumps(scene_plan_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _, report = write_continuity_report(story_result.output_dir)

        segment_codes = {
            item.code
            for item in report.segment_issues
            if item.segment_id == second_segment["segment_id"]
        }
        self.assertIn("opening_match_weak", segment_codes)
        self.assertIn("action_progression_stalled", segment_codes)
        self.assertIn("adjacent_segment_duplicate", segment_codes)

    def test_write_continuity_report_flags_scene_transition_boundary_risks(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        scene_plan_payload = read_json(story_result.scene_plan_path)
        self.assertGreaterEqual(len(scene_plan_payload["scenes"]), 2)
        previous_scene = scene_plan_payload["scenes"][0]
        target_scene = scene_plan_payload["scenes"][1]
        first_segment = target_scene["segments"][0]

        target_scene["scene_transition_contract"] = {
            "previous_scene_id": previous_scene["scene_id"],
            "transition_mode": "adjacent_move",
            "previous_scene_exit_state": "两人已经走到镜湖边并开始低声说话。",
            "next_scene_entry_match": "继续承接上一场。",
            "bridge_action": "先跟着两人离开花廊出口，再顺势露出镜湖步道和栏杆。",
            "carry_over_elements": ["并肩关系", "向右前方行进"],
            "screen_direction_policy": "继续保持向右前方行进。",
            "visual_bridge": "继续带出新场景。",
            "audio_bridge": "ambient_bridge",
            "transition_focus_seconds": 2,
        }
        first_segment["continuity_link"]["opening_match"] = "继续承接。"
        first_segment["timed_beats"] = [
            "0-4秒：两人已经站在镜湖边，没有继续前进。",
            "4-8秒：两人停在原地对视。",
        ]

        story_result.scene_plan_path.write_text(
            json.dumps(scene_plan_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _, report = write_continuity_report(story_result.output_dir)

        scene_codes = {
            item.code
            for item in report.scene_issues
            if item.scene_id == target_scene["scene_id"]
        }
        self.assertIn("scene_transition_exit_state_drift", scene_codes)
        self.assertIn("scene_transition_entry_weak", scene_codes)
        self.assertIn("scene_transition_bridge_weak", scene_codes)
        self.assertIn("scene_transition_opening_not_consumed", scene_codes)
        self.assertIn("scene_transition_bridge_not_consumed", scene_codes)

    def test_write_continuity_report_flags_timed_beats_under_duration(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        scene_plan_payload = read_json(story_result.scene_plan_path)
        target_scene = scene_plan_payload["scenes"][0]
        target_segment = target_scene["segments"][0]
        target_segment["duration_seconds"] = 11
        target_segment["timed_beats"] = [
            "0-3秒：主角站在原地等待。",
            "3-6秒：主角抬头看向前方。",
            "6-9秒：主角低头整理手中的信封。",
        ]

        story_result.scene_plan_path.write_text(
            json.dumps(scene_plan_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _, report = write_continuity_report(story_result.output_dir)

        target_issue = next(
            (
                item
                for item in report.segment_issues
                if item.segment_id == target_segment["segment_id"]
                and item.code == "timed_beats_under_duration"
            ),
            None,
        )
        self.assertIsNotNone(target_issue)
        self.assertIn("早于当前片段时长 11s", target_issue.message)
        self.assertEqual(target_issue.details["uncovered_seconds"], 2.0)

    def test_validate_segment_continuity_repair_rejects_timed_beats_under_duration(self) -> None:
        service = NovelToVideoService()
        target_segment = VideoSegment(
            segment_id="ch01-sc01-seg01",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="镜湖等待",
            scene_summary="陈默在镜湖边等待。",
            scene_anchor="镜湖长椅 / 傍晚 / 微风",
            title="停在原地",
            summary="陈默在镜湖边等待并整理情绪。",
            involved_characters=["陈默"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[
                "0-3秒：陈默站在镜湖长椅旁等待。",
                "3-6秒：他抬头看向步道方向。",
                "6-9秒：他低头整理手中的信封。",
            ],
            start_frame_prompt="陈默站在镜湖长椅旁等待。",
            end_frame_prompt="陈默仍站在原地，整理信封后再次抬头。",
            duration_seconds=11,
            start_frame_characters=["陈默"],
            end_frame_characters=["陈默"],
            requires_mid_frame=False,
            scene_bible=SceneBible(
                location="镜湖长椅",
                time_window="傍晚",
                weather="微风",
                lighting="柔和侧光",
                dominant_palette=["暖金", "湖蓝"],
                background_anchors=["镜湖", "长椅"],
                spatial_layout="长椅靠湖，步道从右侧延伸",
            ),
            shot_state=ShotState(
                framing="单人中景",
                camera_motion="轻微前推，保持陈默单人入镜",
                blocking="陈默站在长椅旁，没有离开原位",
                action_progression="从等待推进到抬头，再到低头整理信封",
                emotion_progression="紧张等待",
                screen_direction="目光朝向步道前方",
                end_state_lock="陈默整理完信封后仍停在原地，目光重新望向前方",
            ),
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="陈默已经站在镜湖长椅旁，保持等待姿态。",
                carry_over_elements=[],
                allowed_changes="从等待推进到短暂整理信封，再回到等待。",
                transition_reason="当前段起始。",
            ),
        )
        candidate = SegmentContinuityRepairSchema.model_validate(
            {
                "segment_id": "ch01-sc01-seg01",
                "summary": "陈默在镜湖边等待并整理情绪。",
                "narration": "",
                "dialogue_lines": [],
                "subtitle_lines": [],
                "timed_beats": [
                    "0-3秒：陈默站在镜湖长椅旁等待。",
                    "3-6秒：他抬头看向步道方向。",
                    "6-9秒：他低头整理手中的信封。",
                ],
                "start_frame_prompt": "陈默站在镜湖长椅旁等待。",
                "mid_frame_prompt": "",
                "end_frame_prompt": "陈默仍站在原地，整理信封后再次抬头。",
                "duration_seconds": 11,
                "requires_mid_frame": False,
                "start_frame_characters": ["陈默"],
                "mid_frame_characters": [],
                "mid_frame_mode": "continuous",
                "end_frame_characters": ["陈默"],
                "shot_state": {
                    "framing": "单人中景",
                    "camera_motion": "轻微前推，保持陈默单人入镜",
                    "blocking": "陈默站在长椅旁，没有离开原位",
                    "action_progression": "从等待推进到抬头，再到低头整理信封",
                    "emotion_progression": "紧张等待",
                    "screen_direction": "目光朝向步道前方",
                    "end_state_lock": "陈默整理完信封后仍停在原地，目光重新望向前方",
                },
                "continuity_link": {
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": "陈默已经站在镜湖长椅旁，保持等待姿态。",
                    "carry_over_elements": [],
                    "allowed_changes": "从等待推进到短暂整理信封，再回到等待。",
                    "transition_reason": "当前段起始。",
                },
            }
        )

        with self.assertRaisesRegex(ValueError, "尾部约 2s 缺少明确动作或收束节拍"):
            service._validate_segment_continuity_repair(
                candidate,
                target_segment=target_segment,
                previous_segment=None,
            )

    def test_validate_segment_continuity_repair_rejects_flat_keyframe_semantic_distance(self) -> None:
        service = NovelToVideoService()
        target_segment = VideoSegment(
            segment_id="ch01-sc01-seg01",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="镜湖停顿",
            scene_summary="陈默在镜湖边停顿。",
            scene_anchor="镜湖长椅 / 傍晚 / 微风",
            title="停在原地",
            summary="陈默停在镜湖长椅旁，没有明显变化。",
            involved_characters=["陈默"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[
                "0-4秒：陈默停在镜湖长椅旁，保持等待姿态。",
                "4-8秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
            ],
            start_frame_prompt="陈默停在镜湖长椅旁。",
            mid_frame_prompt="陈默仍停在镜湖长椅旁。",
            end_frame_prompt="陈默依旧停在镜湖长椅旁。",
            duration_seconds=8,
            start_frame_characters=["陈默"],
            mid_frame_characters=["陈默"],
            end_frame_characters=["陈默"],
            requires_mid_frame=True,
            scene_bible=SceneBible(
                location="镜湖长椅",
                time_window="傍晚",
                weather="微风",
                lighting="柔和侧光",
                dominant_palette=["暖金", "湖蓝"],
                background_anchors=["镜湖", "长椅"],
                spatial_layout="长椅靠湖，步道从右侧延伸",
            ),
            shot_state=ShotState(
                framing="单人中景",
                camera_motion="轻微前推，保持陈默单人入镜",
                blocking="陈默站在长椅旁，没有离开原位",
                action_progression="保持等待姿态，没有明显变化",
                emotion_progression="紧张等待",
                screen_direction="目光朝向步道前方",
                end_state_lock="陈默仍停在原地，姿态几乎不变",
            ),
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="陈默已经停在镜湖长椅旁，保持等待姿态。",
                carry_over_elements=[],
                allowed_changes="继续保持当前等待状态。",
                transition_reason="当前段起始。",
            ),
        )
        candidate = SegmentContinuityRepairSchema.model_validate(
            {
                "segment_id": "ch01-sc01-seg01",
                "summary": "陈默停在镜湖长椅旁，没有明显变化。",
                "narration": "",
                "dialogue_lines": [],
                "subtitle_lines": [],
                "timed_beats": [
                    "0-4秒：陈默停在镜湖长椅旁，保持等待姿态。",
                    "4-8秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
                ],
                "start_frame_prompt": "陈默停在镜湖长椅旁。",
                "mid_frame_prompt": "陈默仍停在镜湖长椅旁。",
                "end_frame_prompt": "陈默依旧停在镜湖长椅旁。",
                "duration_seconds": 8,
                "requires_mid_frame": True,
                "start_frame_characters": ["陈默"],
                "mid_frame_characters": ["陈默"],
                "mid_frame_mode": "continuous",
                "end_frame_characters": ["陈默"],
                "shot_state": {
                    "framing": "单人中景",
                    "camera_motion": "轻微前推，保持陈默单人入镜",
                    "blocking": "陈默站在长椅旁，没有离开原位",
                    "action_progression": "保持等待姿态，没有明显变化",
                    "emotion_progression": "紧张等待",
                    "screen_direction": "目光朝向步道前方",
                    "end_state_lock": "陈默仍停在原地，姿态几乎不变",
                },
                "continuity_link": {
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": "陈默已经停在镜湖长椅旁，保持等待姿态。",
                    "carry_over_elements": [],
                    "allowed_changes": "继续保持当前等待状态。",
                    "transition_reason": "当前段起始。",
                },
            }
        )

        with self.assertRaisesRegex(ValueError, "关键帧语义距离过近"):
            service._validate_segment_continuity_repair(
                candidate,
                target_segment=target_segment,
                previous_segment=None,
            )

    def test_validate_segment_continuity_repair_rejects_flat_start_end_keyframe_semantic_distance_without_mid(self) -> None:
        service = NovelToVideoService()
        target_segment = VideoSegment(
            segment_id="ch01-sc01-seg01",
            chapter_number=1,
            scene_id="ch01-sc01",
            scene_title="镜湖停顿",
            scene_summary="陈默在镜湖边停顿。",
            scene_anchor="镜湖长椅 / 傍晚 / 微风",
            title="停在原地",
            summary="陈默停在镜湖长椅旁，没有明显变化。",
            involved_characters=["陈默"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[
                "0-3秒：陈默停在镜湖长椅旁，保持等待姿态。",
                "3-6秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
            ],
            start_frame_prompt="陈默停在镜湖长椅旁。",
            end_frame_prompt="陈默依旧停在镜湖长椅旁。",
            duration_seconds=6,
            start_frame_characters=["陈默"],
            end_frame_characters=["陈默"],
            requires_mid_frame=False,
            scene_bible=SceneBible(
                location="镜湖长椅",
                time_window="傍晚",
                weather="微风",
                lighting="柔和侧光",
                dominant_palette=["暖金", "湖蓝"],
                background_anchors=["镜湖", "长椅"],
                spatial_layout="长椅靠湖，步道从右侧延伸",
            ),
            shot_state=ShotState(
                framing="单人中景",
                camera_motion="轻微前推，保持陈默单人入镜",
                blocking="陈默站在长椅旁，没有离开原位",
                action_progression="保持等待姿态，没有明显变化",
                emotion_progression="紧张等待",
                screen_direction="目光朝向步道前方",
                end_state_lock="陈默仍停在原地，姿态几乎不变",
            ),
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="陈默已经停在镜湖长椅旁，保持等待姿态。",
                carry_over_elements=[],
                allowed_changes="继续保持当前等待状态。",
                transition_reason="当前段起始。",
            ),
        )
        candidate = SegmentContinuityRepairSchema.model_validate(
            {
                "segment_id": "ch01-sc01-seg01",
                "summary": "陈默停在镜湖长椅旁，没有明显变化。",
                "narration": "",
                "dialogue_lines": [],
                "subtitle_lines": [],
                "timed_beats": [
                    "0-3秒：陈默停在镜湖长椅旁，保持等待姿态。",
                    "3-6秒：陈默仍停在镜湖长椅旁，保持等待姿态。",
                ],
                "start_frame_prompt": "陈默停在镜湖长椅旁。",
                "mid_frame_prompt": "",
                "end_frame_prompt": "陈默依旧停在镜湖长椅旁。",
                "duration_seconds": 6,
                "requires_mid_frame": False,
                "start_frame_characters": ["陈默"],
                "mid_frame_characters": [],
                "mid_frame_mode": "continuous",
                "end_frame_characters": ["陈默"],
                "shot_state": {
                    "framing": "单人中景",
                    "camera_motion": "轻微前推，保持陈默单人入镜",
                    "blocking": "陈默站在长椅旁，没有离开原位",
                    "action_progression": "保持等待姿态，没有明显变化",
                    "emotion_progression": "紧张等待",
                    "screen_direction": "目光朝向步道前方",
                    "end_state_lock": "陈默仍停在原地，姿态几乎不变",
                },
                "continuity_link": {
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": "陈默已经停在镜湖长椅旁，保持等待姿态。",
                    "carry_over_elements": [],
                    "allowed_changes": "继续保持当前等待状态。",
                    "transition_reason": "当前段起始。",
                },
            }
        )

        with self.assertRaisesRegex(ValueError, "关键帧语义距离过近"):
            service._validate_segment_continuity_repair(
                candidate,
                target_segment=target_segment,
                previous_segment=None,
            )


if __name__ == "__main__":
    unittest.main()
