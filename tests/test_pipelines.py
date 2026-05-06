from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from storyforge.core.config import AppConfig  # noqa: E402
from storyforge.core.io import read_json, to_jsonable, write_json  # noqa: E402
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
from storyforge.domains.video.contracts import ContinuityLink, MotionPlan, SceneBible, SceneImageTask, SceneTransitionContract, SeedanceClipTask, SeedanceManifest, ShotState, StoryMemoryPackage, VideoScene, VideoSegment  # noqa: E402
from storyforge.domains.video.errors import SegmentActionSplitRequiredError, SegmentSpeechSplitRequiredError, VideoStructuredGenerationError  # noqa: E402
from storyforge.domains.video.schemas import (  # noqa: E402
    ChapterCoveragePlanSchema,
    ChapterCoverageEventSplitPlanSchema,
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    CharacterVisualBibleSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentChunkSchema,
    SceneSegmentContractBatchSchema,
    VideoSegmentPlanSchema,
)  # noqa: E402
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from storyforge.integrations.seedance import SeedanceExecutionReport  # noqa: E402
from storyforge.integrations.gpt_image import GPTImageResult  # noqa: E402
from storyforge.integrations.seedream import SeedreamExecutionReport  # noqa: E402
from storyforge.pipelines.continuity import write_continuity_report  # noqa: E402
from storyforge.pipelines.story_pipeline import (  # noqa: E402
    run_story_generation_pipeline,
    run_story_scene_structure_pipeline,
    run_story_segment_contracts_pipeline,
)
from storyforge.pipelines.storyboard_grid import run_storyboard_grid_pipeline  # noqa: E402
from storyforge.pipelines.story_files import clear_story_derived_artifacts  # noqa: E402
from storyforge.pipelines.video_pipeline import (  # noqa: E402
    _merge_seedance_manifest_for_write,
    reset_scene_execution_contracts_for_repair,
    run_character_image_pipeline,
    run_scene_continuity_repair_pipeline,
    run_scene_image_pipeline,
    run_video_merge_pipeline,
    run_video_render_pipeline,
    _sync_v2_seedance_references,
    _sync_seedance_tail_frame_handoffs,
)
from storyforge.pipelines.video_planning import (  # noqa: E402
    build_video_planning_artifacts,
    load_segment_contract_progress,
    load_video_planning_artifacts,
)
from storyforge.pipelines.video_support import should_skip_seedance_after_seedream, validate_manifest_ready_for_video  # noqa: E402
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
            output_root=self.temp_root / "structure-source",
        )

        split_scene_structure = run_story_scene_structure_pipeline(
            story_source=generation.story_source,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root / "structure-split",
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

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_character_images")
    @patch("storyforge.pipelines.video_pipeline.GPTImageClient.generate_single_image")
    def test_character_image_pipeline_uses_selected_gpt_model(
        self,
        mock_generate_gpt_image,
        mock_generate_seedream_characters,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        def fake_generate_single_image(*, output_path, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"gpt-character")
            return GPTImageResult(
                submitted=True,
                image_url="https://gpt.example/character.png",
                output_path=str(output_path),
                request_info={"provider": "kie", "payload": {"prompt": kwargs["prompt"]}},
                note="GPT Image 2 generation completed.",
            )

        mock_generate_gpt_image.side_effect = fake_generate_single_image

        character_result = run_character_image_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_characters=True,
            image_model=config.gpt_image.model,
            image_size="1K",
            image_aspect_ratio="1:1",
        )

        mock_generate_seedream_characters.assert_not_called()
        self.assertTrue(mock_generate_gpt_image.called)
        manifest = read_json(character_result.character_images_path)
        self.assertTrue(manifest)
        self.assertTrue(all(item["provider"] == config.gpt_image.model for item in manifest))
        self.assertTrue(all(item["generated_url"].startswith("https://gpt.example/") for item in manifest))
        self.assertTrue(all(Path(item["output_path"]).suffix == ".png" for item in manifest))

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_master_frames")
    @patch("storyforge.pipelines.video_pipeline.GPTImageClient.generate_single_image")
    def test_scene_image_pipeline_uses_selected_gpt_model(
        self,
        mock_generate_gpt_image,
        mock_generate_seedream_scenes,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        def fake_generate_single_image(*, output_path, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"gpt-scene")
            return GPTImageResult(
                submitted=True,
                image_url="https://gpt.example/scene.png",
                output_path=str(output_path),
                request_info={"provider": "kie", "payload": {"prompt": kwargs["prompt"]}},
                note="GPT Image 2 generation completed.",
            )

        mock_generate_gpt_image.side_effect = fake_generate_single_image

        scene_result = run_scene_image_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_scenes=True,
            image_model=config.gpt_image.model,
            image_size="1K",
            image_aspect_ratio="1:1",
        )

        mock_generate_seedream_scenes.assert_not_called()
        self.assertTrue(mock_generate_gpt_image.called)
        scene_manifest = read_json(scene_result.scene_images_path)
        scene_plan = read_json(scene_result.scene_plan_path)["scenes"]
        self.assertTrue(scene_manifest)
        self.assertTrue(all(item["provider"] == config.gpt_image.model for item in scene_manifest))
        self.assertTrue(all(item["scene_master_frame_url"].startswith("https://gpt.example/") for item in scene_manifest))
        self.assertTrue(all(item["scene_master_frame_url"].startswith("https://gpt.example/") for item in scene_plan))

    @patch("storyforge.pipelines.storyboard_grid.SeedreamClient.generate_single_image")
    def test_storyboard_grid_prompt_is_persisted_before_image_generation(
        self,
        mock_generate_single_image,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = self._run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        mark_scene_images_completed(story_result)
        character_manifest = read_json(story_result.character_images_path)
        for item in character_manifest:
            item["status"] = "completed"
            item["generated_url"] = f"https://example.com/{Path(item['output_path']).name}"
        write_json(story_result.character_images_path, character_manifest)
        segment_id = str(read_json(story_result.segment_plan_path)[0]["segment_id"])

        def fake_generate_single_image(**kwargs):
            storyboard_manifest = read_json(story_result.output_dir / "storyboard_grid_manifest.json")
            self.assertEqual(len(storyboard_manifest), 1)
            self.assertEqual(storyboard_manifest[0]["segment_id"], segment_id)
            self.assertEqual(storyboard_manifest[0]["status"], "running")
            self.assertIn("九宫格分镜图", storyboard_manifest[0]["prompt"])
            seedance_manifest = read_json(story_result.seedance_manifest_path)
            clip = next(item for item in seedance_manifest["clips"] if item["segment_id"] == segment_id)
            self.assertEqual(clip["video_mode"], "grid_storyboard")
            self.assertEqual(clip["storyboard_grid_status"], "running")
            self.assertIn("九宫格分镜图", clip["storyboard_grid_prompt"])
            return SimpleNamespace(
                image_url="https://example.com/storyboard.png",
                request_info={"provider": "seedream", "payload": {"prompt": kwargs["prompt"]}},
            )

        mock_generate_single_image.side_effect = fake_generate_single_image

        result = run_storyboard_grid_pipeline(
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            segment_id=segment_id,
            image_model=config.seedream.model,
            image_size="2K",
            aspect_ratio="16:9",
        )

        self.assertEqual(result.generated_count, 1)
        completed_manifest = read_json(result.storyboard_manifest_path)
        self.assertEqual(completed_manifest[0]["status"], "completed")
        self.assertIn("九宫格分镜图", completed_manifest[0]["prompt"])

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

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_master_frames")
    def test_run_scene_image_pipeline_only_updates_selected_segment(
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
        selected_segment_id = read_json(story_result.segment_plan_path)[0]["segment_id"]

        expected_scene_ids = {
            item["scene_id"]
            for item in read_json(story_result.scene_plan_path)["scenes"]
        }

        def fake_generate_scene_master_frames(project_package, force_submit=False, scene_ids=None, force_regenerate=False):
            self.assertTrue(force_submit)
            self.assertEqual(scene_ids, expected_scene_ids)
            self.assertFalse(force_regenerate)
            mark_runtime_scene_images_completed(
                project_package,
                segment_ids={selected_segment_id},
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
            segment_id=selected_segment_id,
        )

        scene_manifest = read_json(scene_result.scene_images_path)
        selected_task = next(item for item in scene_manifest if item["segment_id"] == selected_segment_id)
        untouched_tasks = [item for item in scene_manifest if item["segment_id"] != selected_segment_id]
        self.assertTrue(selected_task["scene_master_frame_url"])
        self.assertTrue(all(not item.get("scene_master_frame_url") for item in untouched_tasks))

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_master_frames")
    def test_run_scene_image_pipeline_preserves_newer_disk_state_for_other_segments(
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
        ensure_secondary_segment_execution_contract(story_result)
        segment_payload = read_json(story_result.segment_plan_path)
        selected_segment_id = str(segment_payload[0]["segment_id"])
        preserved_segment_id = str(segment_payload[1]["segment_id"])

        expected_scene_ids = {
            item["scene_id"]
            for item in read_json(story_result.scene_plan_path)["scenes"]
        }

        def fake_generate_scene_master_frames(project_package, force_submit=False, scene_ids=None, force_regenerate=False):
            self.assertTrue(force_submit)
            self.assertEqual(scene_ids, expected_scene_ids)
            self.assertFalse(force_regenerate)

            scene_manifest_payload = read_json(story_result.scene_images_path)
            for item in scene_manifest_payload:
                if item["segment_id"] != preserved_segment_id:
                    continue
                item["status"] = "completed"
                item["scene_master_frame_url"] = "https://disk.example/preserved_scene_master.png"
                item["scene_master_frame_status"] = "completed"
                break
            story_result.scene_images_path.write_text(
                json.dumps(scene_manifest_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            manifest_payload = read_json(story_result.seedance_manifest_path)
            for clip in manifest_payload["clips"]:
                if clip["segment_id"] != preserved_segment_id:
                    continue
                clip["scene_master_url"] = "https://disk.example/preserved_scene_master.png"
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

        mock_generate_scene_master_frames.side_effect = fake_generate_scene_master_frames

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
            preserved_task["scene_master_frame_url"],
            "https://disk.example/preserved_scene_master.png",
        )

        persisted_seedance_manifest = read_json(scene_result.manifest_path)
        preserved_clip = next(
            item for item in persisted_seedance_manifest["clips"] if item["segment_id"] == preserved_segment_id
        )
        self.assertEqual(
            preserved_clip["scene_master_url"],
            "https://disk.example/preserved_scene_master.png",
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

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_master_frames")
    def test_run_scene_image_pipeline_only_updates_selected_scene_segments(
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

        def fake_generate_scene_master_frames(project_package, force_submit=False, scene_ids=None, force_regenerate=False):
            self.assertTrue(force_submit)
            self.assertEqual(scene_ids, {selected_scene_id})
            self.assertFalse(force_regenerate)
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
        )

        scene_manifest = read_json(scene_result.scene_images_path)
        selected_tasks = [
            item for item in scene_manifest if item["scene_id"] == selected_scene_id
        ]
        untouched_tasks = [
            item for item in scene_manifest if item["scene_id"] != selected_scene_id
        ]
        self.assertTrue(selected_tasks)
        self.assertTrue(all(item["scene_master_frame_url"] for item in selected_tasks))
        self.assertTrue(all(not item.get("scene_master_frame_url") for item in untouched_tasks))

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
        self.assertTrue(all(not item.get("scene_master_frame_url") for item in selected_tasks))
        self.assertTrue(
            all(item["scene_id"] == selected_scene_id for item in selected_tasks)
        )
        self.assertTrue(all(item["status"] == "completed" for item in untouched_tasks))
        self.assertTrue(all(item["scene_master_frame_url"] for item in untouched_tasks))

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
        manifest_payload["clips"][0]["scene_master_url"] = "https://example.com/scene-master.png"
        manifest_payload["clips"][0]["character_image_urls"] = ["https://example.com/character.png"]
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        character_payload = read_json(story_result.character_images_path)
        for item in character_payload:
            item["generated_url"] = f"https://example.com/{Path(item['output_path']).name}"
            item["status"] = "completed"
        story_result.character_images_path.write_text(
            json.dumps(character_payload, ensure_ascii=False, indent=2),
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
    def test_run_video_render_pipeline_backfills_scene_master_from_scene_plan_before_validation(
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
        manifest_payload = read_json(story_result.seedance_manifest_path)
        selected_segment_id = manifest_payload["clips"][0]["segment_id"]
        scene_id = manifest_payload["clips"][0]["scene_id"]
        manifest_payload["clips"][0]["scene_master_url"] = ""
        manifest_payload["clips"][0]["character_image_urls"] = ["https://example.com/character.png"]
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        scene_manifest = read_json(story_result.scene_images_path)
        for item in scene_manifest:
            if item["scene_id"] == scene_id:
                item["scene_master_frame_url"] = ""
                item["scene_master_frame_status"] = "planned"
        story_result.scene_images_path.write_text(
            json.dumps(scene_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        scene_plan = read_json(story_result.scene_plan_path)
        for scene in scene_plan["scenes"]:
            if scene["scene_id"] == scene_id:
                scene["scene_master_frame_url"] = "https://example.com/scene-plan-master.png"
                scene["scene_master_frame_status"] = "completed"
        story_result.scene_plan_path.write_text(
            json.dumps(scene_plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})
            clip = next(item for item in manifest.clips if item.segment_id == selected_segment_id)
            self.assertEqual(clip.scene_master_url, "https://example.com/scene-plan-master.png")
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
        self.assertEqual(selected_clip["scene_master_url"], "https://example.com/scene-plan-master.png")

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
            clip["scene_master_url"] = "https://runtime.example/selected_scene_master.png"
            clip["character_image_urls"] = ["https://runtime.example/selected_character.png"]
            break
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        character_payload = read_json(story_result.character_images_path)
        for item in character_payload:
            item["generated_url"] = f"https://runtime.example/{Path(item['output_path']).name}"
            item["status"] = "completed"
        story_result.character_images_path.write_text(
            json.dumps(character_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})

            latest_manifest_payload = read_json(story_result.seedance_manifest_path)
            for clip in latest_manifest_payload["clips"]:
                if clip["segment_id"] != preserved_segment_id:
                    continue
                clip["scene_master_url"] = "https://disk.example/preserved_scene_master.png"
                clip["character_image_urls"] = ["https://disk.example/preserved_character.png"]
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
            preserved_clip["scene_master_url"],
            "https://disk.example/preserved_scene_master.png",
        )

    def test_seedance_tail_frame_handoff_syncs_planned_next_segment(self) -> None:
        previous_clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg01",
            scene_id="ch01-sc01",
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
            output_path="rendered/ch01-sc01-seg01.mp4",
            video_url="https://example.com/seg01.mp4",
            last_frame_url="https://example.com/seg01-last.png",
            submit_status="completed",
            remote_status="succeeded",
        )
        next_clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg02",
            scene_id="ch01-sc01",
            title="下一段",
            prompt="下一段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc01-seg02.mp4",
            previous_clip_segment_id="ch01-sc01-seg01",
        )
        manifest = SeedanceManifest(
            title="尾帧同步测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[previous_clip, next_clip],
        )

        _sync_seedance_tail_frame_handoffs(manifest)

        self.assertEqual(next_clip.first_frame_url, "https://example.com/seg01-last.png")
        self.assertEqual(next_clip.previous_clip_video_url, "https://example.com/seg01.mp4")

    def test_seedance_tail_frame_handoff_crosses_same_space_scene_boundary(self) -> None:
        previous_clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg02",
            scene_id="ch01-sc01",
            title="上一场尾段",
            prompt="上一场尾段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc01-seg02.mp4",
            video_url="https://example.com/sc01-seg02.mp4",
            last_frame_url="https://example.com/sc01-seg02-last.png",
            submit_status="completed",
            remote_status="succeeded",
        )
        next_scene_clip = SeedanceClipTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            title="同空间下一场首段",
            prompt="同空间下一场首段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc02-seg01.mp4",
        )
        manifest = SeedanceManifest(
            title="跨 scene 尾帧承接测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[previous_clip, next_scene_clip],
        )
        scenes = [
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="上一场",
                summary="上一场",
                scene_anchor="花田",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="花田"),
            ),
            VideoScene(
                scene_id="ch01-sc02",
                chapter_number=1,
                title="同空间下一场",
                summary="同空间下一场",
                scene_anchor="花田",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="花田"),
                scene_transition_contract=SceneTransitionContract(
                    previous_scene_id="ch01-sc01",
                    transition_mode="direct_continue",
                    scene_spatial_continuity_mode="same_space_progression",
                ),
            ),
        ]

        _sync_seedance_tail_frame_handoffs(manifest, scenes)

        self.assertEqual(next_scene_clip.previous_clip_segment_id, "ch01-sc01-seg02")
        self.assertEqual(next_scene_clip.previous_clip_video_url, "https://example.com/sc01-seg02.mp4")
        self.assertEqual(next_scene_clip.first_frame_url, "https://example.com/sc01-seg02-last.png")

    def test_seedance_tail_frame_handoff_does_not_cross_hard_cut_scene_boundary(self) -> None:
        previous_clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg02",
            scene_id="ch01-sc01",
            title="上一场尾段",
            prompt="上一场尾段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc01-seg02.mp4",
            video_url="https://example.com/sc01-seg02.mp4",
            last_frame_url="https://example.com/sc01-seg02-last.png",
        )
        hard_cut_clip = SeedanceClipTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            title="新地点首段",
            prompt="新地点首段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc02-seg01.mp4",
        )
        manifest = SeedanceManifest(
            title="硬切不承接尾帧测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[previous_clip, hard_cut_clip],
        )
        scenes = [
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="上一场",
                summary="上一场",
                scene_anchor="花田",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="花田"),
            ),
            VideoScene(
                scene_id="ch01-sc02",
                chapter_number=1,
                title="新地点",
                summary="新地点",
                scene_anchor="图书馆",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="图书馆"),
                scene_transition_contract=SceneTransitionContract(
                    previous_scene_id="ch01-sc01",
                    transition_mode="hard_cut",
                    scene_spatial_continuity_mode="hard_cut_new_location",
                ),
            ),
        ]

        _sync_seedance_tail_frame_handoffs(manifest, scenes)

        self.assertEqual(hard_cut_clip.previous_clip_segment_id, "")
        self.assertEqual(hard_cut_clip.first_frame_url, "")

    def test_seedance_tail_frame_handoff_does_not_cross_adjacent_uncertain_scene_boundary(self) -> None:
        previous_clip = SeedanceClipTask(
            segment_id="ch01-sc01-seg02",
            scene_id="ch01-sc01",
            title="上一场尾段",
            prompt="上一场尾段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc01-seg02.mp4",
            video_url="https://example.com/sc01-seg02.mp4",
            last_frame_url="https://example.com/sc01-seg02-last.png",
        )
        adjacent_clip = SeedanceClipTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            title="相邻但未确认同空间首段",
            prompt="相邻但未确认同空间首段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            aspect_ratio="16:9",
            with_audio=True,
            output_path="rendered/ch01-sc02-seg01.mp4",
        )
        manifest = SeedanceManifest(
            title="相邻未知空间不承接尾帧测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[previous_clip, adjacent_clip],
        )
        scenes = [
            VideoScene(
                scene_id="ch01-sc01",
                chapter_number=1,
                title="上一场",
                summary="上一场",
                scene_anchor="花田",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="花田"),
            ),
            VideoScene(
                scene_id="ch01-sc02",
                chapter_number=1,
                title="相邻但未确认同空间",
                summary="相邻但未确认同空间",
                scene_anchor="教学楼",
                involved_characters=[],
                covered_event_ids=[],
                covered_event_summaries=[],
                segments=[],
                scene_bible=SceneBible(location="教学楼"),
                scene_transition_contract=SceneTransitionContract(
                    previous_scene_id="ch01-sc01",
                    transition_mode="adjacent_move",
                    scene_spatial_continuity_mode="uncertain",
                ),
            ),
        ]

        _sync_seedance_tail_frame_handoffs(manifest, scenes)

        self.assertEqual(adjacent_clip.previous_clip_segment_id, "")
        self.assertEqual(adjacent_clip.first_frame_url, "")

    def test_build_seedance_manifest_links_same_space_scene_first_clip_to_previous_tail(self) -> None:
        service = NovelToVideoService()
        previous_scene = VideoScene(
            scene_id="ch01-sc01",
            chapter_number=1,
            title="上一场",
            summary="上一场",
            scene_anchor="花田",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="花田"),
        )
        next_scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="同空间下一场",
            summary="同空间下一场",
            scene_anchor="花田",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="花田"),
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="direct_continue",
                scene_spatial_continuity_mode="same_space_progression",
            ),
        )
        previous_segment = VideoSegment(
            segment_id="ch01-sc01-seg01",
            scene_id="ch01-sc01",
            title="上一场尾段",
            summary="上一场尾段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            involved_characters=[],
            scene_title="上一场",
            scene_summary="上一场",
            scene_anchor="花田",
            chapter_number=1,
            scene_bible=SceneBible(location="花田"),
        )
        next_segment = VideoSegment(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            title="同空间下一场首段",
            summary="同空间下一场首段",
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=[],
            duration_seconds=8,
            involved_characters=[],
            scene_title="同空间下一场",
            scene_summary="同空间下一场",
            scene_anchor="花田",
            chapter_number=1,
            scene_bible=SceneBible(location="花田"),
        )
        scene_images = [
            SceneImageTask(
                segment_id="ch01-sc01-seg01",
                scene_id="ch01-sc01",
                scene_title="上一场",
                scene_master_frame_prompt="上一场母图",
                scene_master_frame_path="rendered/ch01-sc01_master.png",
                reference_images=[],
                provider="seedream",
            ),
            SceneImageTask(
                segment_id="ch01-sc02-seg01",
                scene_id="ch01-sc02",
                scene_title="同空间下一场",
                scene_master_frame_prompt="下一场母图",
                scene_master_frame_path="rendered/ch01-sc02_master.png",
                reference_images=[],
                provider="seedream",
            ),
        ]

        manifest = service._build_seedance_manifest(
            "测试",
            [previous_scene, next_scene],
            [previous_segment, next_segment],
            scene_images,
            [],
            "outputs/test",
        )

        next_clip = manifest.clips[1]
        self.assertEqual(next_clip.previous_clip_segment_id, "ch01-sc01-seg01")

    def test_seedance_reference_sync_shares_scene_master_across_same_scene_segments(self) -> None:
        source_task = SceneImageTask(
            segment_id="ch01-sc02-seg00",
            scene_id="ch01-sc02",
            scene_title="长椅对话",
            scene_master_frame_prompt="长椅旁空场景",
            scene_master_frame_path="rendered/ch01-sc02_master.png",
            reference_images=[],
            provider="seedream",
            status="completed",
            scene_master_frame_status="completed",
            scene_master_frame_url="https://example.com/shared-scene-master.png",
        )
        target_task = SceneImageTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            scene_title="长椅对话",
            scene_master_frame_prompt="长椅旁空场景",
            scene_master_frame_path="rendered/ch01-sc02_master.png",
            reference_images=[],
            provider="seedream",
        )
        manifest = SeedanceManifest(
            title="同 scene 共用母图测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc02-seg01",
                    scene_id="ch01-sc02",
                    title="不能生成视频的当前段",
                    prompt="当前段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc02-seg01.mp4",
                )
            ],
        )
        project_package = SimpleNamespace(scene_images=[source_task, target_task], character_images=[])

        _sync_v2_seedance_references(manifest, project_package)

        target_clip = next(clip for clip in manifest.clips if clip.segment_id == "ch01-sc02-seg01")
        self.assertEqual(target_task.scene_master_frame_url, "https://example.com/shared-scene-master.png")
        self.assertEqual(target_clip.scene_master_url, "https://example.com/shared-scene-master.png")
        validate_manifest_ready_for_video(manifest, {"ch01-sc02-seg01"})

    def test_seedance_reference_sync_uses_scene_contract_master_when_task_is_empty(self) -> None:
        scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="长椅对话",
            summary="两人对话。",
            scene_anchor="长椅旁",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="长椅旁"),
            scene_master_frame_path="rendered/ch01-sc02_master.png",
            scene_master_frame_url="https://example.com/scene-contract-master.png",
            scene_master_frame_status="completed",
        )
        scene_task = SceneImageTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            scene_title="长椅对话",
            scene_master_frame_prompt="长椅旁空场景",
            scene_master_frame_path="",
            reference_images=[],
            provider="seedream",
        )
        manifest = SeedanceManifest(
            title="scene 主记录回填测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc02-seg01",
                    scene_id="ch01-sc02",
                    title="当前段",
                    prompt="当前段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc02-seg01.mp4",
                )
            ],
        )
        project_package = SimpleNamespace(
            scenes=[scene],
            scene_images=[scene_task],
            character_images=[],
        )

        _sync_v2_seedance_references(manifest, project_package)

        clip = manifest.clips[0]
        self.assertEqual(clip.scene_master_url, "https://example.com/scene-contract-master.png")
        validate_manifest_ready_for_video(manifest, {"ch01-sc02-seg01"})

    def test_seedance_reference_sync_does_not_copy_previous_master_across_same_space_scene(self) -> None:
        previous_scene = VideoScene(
            scene_id="ch01-sc01",
            chapter_number=1,
            title="郁金香花田",
            summary="第一场。",
            scene_anchor="郁金香花田",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="郁金香花田"),
            scene_master_frame_path="rendered/ch01-sc01_master.png",
            scene_master_frame_url="https://example.com/sc01-master.png",
            scene_master_frame_status="completed",
        )
        current_scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="同一花田继续",
            summary="第二场继续在同一地点。",
            scene_anchor="郁金香花田",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="郁金香花田"),
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="direct_continue",
                scene_spatial_continuity_mode="same_space_progression",
            ),
            scene_master_frame_path="rendered/ch01-sc02_master.png",
        )
        current_task = SceneImageTask(
            segment_id="ch01-sc02-seg01",
            scene_id="ch01-sc02",
            scene_title="同一花田继续",
            scene_master_frame_prompt="同一花田空场景",
            scene_master_frame_path="rendered/ch01-sc02_master.png",
            reference_images=[],
            provider="seedream",
        )
        manifest = SeedanceManifest(
            title="跨 scene 复用母图测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc02-seg01",
                    scene_id="ch01-sc02",
                    title="第二场第一段",
                    prompt="第二场第一段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc02-seg01.mp4",
                )
            ],
        )
        project_package = SimpleNamespace(
            scenes=[previous_scene, current_scene],
            scene_images=[current_task],
            character_images=[],
        )

        _sync_v2_seedance_references(manifest, project_package)

        self.assertEqual(current_scene.scene_master_frame_url, "")
        self.assertEqual(current_task.scene_master_frame_url, "")
        self.assertEqual(manifest.clips[0].scene_master_url, "")

    def test_seedance_reference_sync_does_not_reuse_previous_master_for_adjacent_uncertain_scene(self) -> None:
        previous_scene = VideoScene(
            scene_id="ch01-sc01",
            chapter_number=1,
            title="郁金香花田",
            summary="第一场。",
            scene_anchor="郁金香花田",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="郁金香花田"),
            scene_master_frame_path="rendered/ch01-sc01_master.png",
            scene_master_frame_url="https://example.com/sc01-master.png",
            scene_master_frame_status="completed",
        )
        current_scene = VideoScene(
            scene_id="ch01-sc03",
            chapter_number=1,
            title="教学楼走廊",
            summary="第三场在教学楼走廊。",
            scene_anchor="教学楼走廊",
            involved_characters=[],
            covered_event_ids=[],
            covered_event_summaries=[],
            segments=[],
            scene_bible=SceneBible(location="教学楼走廊"),
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="adjacent_move",
                scene_spatial_continuity_mode="uncertain",
            ),
            scene_master_frame_path="rendered/ch01-sc03_master.png",
        )
        current_task = SceneImageTask(
            segment_id="ch01-sc03-seg01",
            scene_id="ch01-sc03",
            scene_title="教学楼走廊",
            scene_master_frame_prompt="教学楼走廊空场景",
            scene_master_frame_path="rendered/ch01-sc03_master.png",
            reference_images=[],
            provider="seedream",
        )
        manifest = SeedanceManifest(
            title="未知空间不复用母图测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc03-seg01",
                    scene_id="ch01-sc03",
                    title="第三场第一段",
                    prompt="第三场第一段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc03-seg01.mp4",
                )
            ],
        )
        project_package = SimpleNamespace(
            scenes=[previous_scene, current_scene],
            scene_images=[current_task],
            character_images=[],
        )

        _sync_v2_seedance_references(manifest, project_package)

        self.assertEqual(current_scene.scene_master_frame_url, "")
        self.assertEqual(current_task.scene_master_frame_url, "")
        self.assertEqual(manifest.clips[0].scene_master_url, "")

    def test_seedance_manifest_merge_preserves_tail_frame_handoff_fields(self) -> None:
        manifest_path = self.temp_root / "seedance_manifest.json"
        latest_manifest = SeedanceManifest(
            title="尾帧 merge 测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc01-seg01",
                    scene_id="ch01-sc01",
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
                    output_path="rendered/ch01-sc01-seg01.mp4",
                    video_url="https://example.com/seg01.mp4",
                    last_frame_url="https://example.com/seg01-last.png",
                    submit_status="completed",
                    remote_status="succeeded",
                ),
                SeedanceClipTask(
                    segment_id="ch01-sc01-seg02",
                    scene_id="ch01-sc01",
                    title="下一段",
                    prompt="下一段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc01-seg02.mp4",
                    previous_clip_segment_id="ch01-sc01-seg01",
                ),
            ],
        )
        manifest_path.write_text(
            json.dumps(to_jsonable(latest_manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        current_manifest = SeedanceManifest(
            title="尾帧 merge 测试",
            model="doubao-seedance-2-0-260128",
            base_url="",
            clips=[
                SeedanceClipTask(
                    segment_id="ch01-sc01-seg02",
                    scene_id="ch01-sc01",
                    title="下一段",
                    prompt="下一段",
                    narration="",
                    dialogue_lines=[],
                    subtitle_lines=[],
                    sound_effects=[],
                    music_direction="",
                    timed_beats=[],
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    with_audio=True,
                    output_path="rendered/ch01-sc01-seg02.mp4",
                    previous_clip_segment_id="ch01-sc01-seg01",
                    first_frame_url="https://example.com/seg01-last.png",
                    previous_clip_video_url="https://example.com/seg01.mp4",
                )
            ],
        )

        merged = _merge_seedance_manifest_for_write(
            current_manifest,
            manifest_path,
            selected_segment_ids={"ch01-sc01-seg02"},
        )
        merged_clip = next(item for item in merged.clips if item.segment_id == "ch01-sc01-seg02")

        self.assertEqual(merged_clip.first_frame_url, "https://example.com/seg01-last.png")
        self.assertEqual(merged_clip.previous_clip_video_url, "https://example.com/seg01.mp4")

    def test_overflow_repair_chains_to_timeline_repair_for_tail_gap(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "初次对话",
                "summary": "两人在长椅旁完成第一轮对话。",
                "scene_anchor": "郁金香花园长椅",
                "involved_characters": ["林叙", "苏晚"],
                "covered_event_ids": ["ch01-ev02"],
                "scene_bible": {
                    "location": "郁金香花园长椅",
                    "background_anchors": ["长椅", "郁金香花丛"],
                    "spatial_layout": "长椅位于花丛旁",
                    "character_blocking": "两人在长椅旁面对面站立",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc02-chunk01",
                "order_index": 1,
                "title": "第一轮对话",
                "summary": "林叙和苏晚开始对话。",
                "must_cover": ["林叙开口", "苏晚回应"],
                "transition_goal": "两人完成第一轮对话。",
                "expected_segment_count": 2,
            }
        )
        failed_contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc02-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc02",
                        "title": "对话停顿",
                        "summary": "林叙说完后苏晚短暂停顿。",
                        "involved_characters": ["林叙", "苏晚"],
                        "timed_beats": ["0-6秒：林叙说完后苏晚短暂停顿。"],
                        "duration_seconds": 10,
                        "transition_hint": "start",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "固定镜头",
                            "blocking": "两人面对面站立",
                            "action_progression": "林叙说完，苏晚停顿",
                            "emotion_progression": "紧张到安静",
                            "prop_continuity": "无特殊持物",
                            "screen_direction": "保持面对面轴线",
                            "end_state_lock": "两人完成第一轮对话。",
                        },
                        "continuity_link": {
                            "transition_mode": "start",
                            "opening_match": "两人在长椅旁面对面站立。",
                            "carry_over_elements": ["长椅", "郁金香花丛"],
                            "allowed_changes": "林叙开口，苏晚回应。",
                            "transition_reason": "chunk 起始。",
                        },
                        "motion_plan": {
                            "scene_motion": "两人在长椅旁完成对话。",
                            "beat_progression": "0-6秒林叙说完后苏晚停顿。",
                            "camera_path": "固定镜头。",
                            "character_motion": "两人保持面对面。",
                            "continuity_guard": "保持同一长椅空间。",
                        },
                    }
                ],
            }
        )
        split_error = SegmentSpeechSplitRequiredError(
            segment_id="ch01-sc02-seg02",
            required_duration_seconds=14,
            current_duration_seconds=10,
            max_duration_seconds=12,
            required_segment_count=2,
        )
        timeline_error = ValueError(
            "segment ch01-sc02-seg02 的 timed_beats 最后结束时间 6s "
            "早于当前片段时长 10s，尾部约 4s 缺少明确动作或收束节拍。"
        )
        structured_error = RuntimeError(
            "Structured repair failed for task=video-scene-segment-overflow-repair "
            "schema=SceneSegmentContractBatchSchema after 3 attempts: "
            f"{timeline_error}"
        )

        def fake_strict_agent(*, schema, request, validator, attempts):  # noqa: ANN001
            try:
                validator(failed_contracts)
            except Exception:
                pass
            raise structured_error

        with (
            patch.object(service, "_run_strict_structured_agent", side_effect=fake_strict_agent),
            patch.object(service, "_repair_scene_chunk_contract_batch_after_timeline_failure", return_value=failed_contracts) as timeline_repair,
        ):
            repaired = service._repair_scene_chunk_contract_batch_after_split_failure(
                novel_package=SimpleNamespace(outline=SimpleNamespace(title="测试", characters=[])),
                story_memory=StoryMemoryPackage(),
                chapter_number=1,
                scene=scene,
                chunk=chunk,
                previous_chunk_exit_state=None,
                previous_tail_segment=None,
                failed_contracts=failed_contracts,
                split_error=split_error,
                effective_expected_segment_count=2,
            )

        self.assertIs(repaired, failed_contracts)
        timeline_repair.assert_called_once()

    def test_overflow_repair_chains_to_split_repair_for_nested_speech_overflow(self) -> None:
        service = NovelToVideoService()
        scene, chunk, failed_contracts = self._build_overflow_repair_chain_fixture()
        initial_split_error = SegmentSpeechSplitRequiredError(
            segment_id="ch01-sc02-seg02",
            required_duration_seconds=13,
            current_duration_seconds=8,
            max_duration_seconds=12,
            required_segment_count=2,
        )
        structured_error = RuntimeError(
            "Structured repair failed for task=video-scene-segment-overflow-repair "
            "schema=SceneSegmentContractBatchSchema after 3 attempts: "
            "segment ch01-sc02-seg02 的对白/字幕至少需要 13 秒，"
            "但单段上限只有 12 秒，当前 chunk 必须至少拆成 2 个 segment。"
        )

        strict_calls = 0

        def fake_strict_agent(*, schema, request, validator, attempts):  # noqa: ANN001
            nonlocal strict_calls
            strict_calls += 1
            if strict_calls == 1:
                raise structured_error
            return failed_contracts

        with patch.object(service, "_run_strict_structured_agent", side_effect=fake_strict_agent):
            repaired = service._repair_scene_chunk_contract_batch_after_split_failure(
                novel_package=SimpleNamespace(outline=SimpleNamespace(title="测试", characters=[])),
                story_memory=StoryMemoryPackage(),
                chapter_number=1,
                scene=scene,
                chunk=chunk,
                previous_chunk_exit_state=None,
                previous_tail_segment=None,
                failed_contracts=failed_contracts,
                split_error=initial_split_error,
                effective_expected_segment_count=1,
            )

        self.assertIs(repaired, failed_contracts)
        self.assertEqual(strict_calls, 2)

    def test_overflow_repair_chains_to_focus_repair_for_nested_single_closeup(self) -> None:
        service = NovelToVideoService()
        scene, chunk, failed_contracts = self._build_overflow_repair_chain_fixture()
        initial_split_error = SegmentSpeechSplitRequiredError(
            segment_id="ch01-sc02-seg02",
            required_duration_seconds=13,
            current_duration_seconds=8,
            max_duration_seconds=12,
            required_segment_count=2,
        )
        structured_error = RuntimeError(
            "Structured repair failed for task=video-scene-segment-overflow-repair "
            "schema=SceneSegmentContractBatchSchema after 3 attempts: "
            "segment ch01-sc02-seg02 的 shot_state.framing 在 segment "
            "(林屿、苏晚) 多人同帧时仍要求单人特写，这会导致同一角色在画面里重复出现。"
        )

        def fake_strict_agent(*, schema, request, validator, attempts):  # noqa: ANN001
            raise structured_error

        with (
            patch.object(service, "_run_strict_structured_agent", side_effect=fake_strict_agent),
            patch.object(service, "_repair_scene_chunk_contract_batch_after_focus_conflict_failure", return_value=failed_contracts) as focus_repair,
        ):
            repaired = service._repair_scene_chunk_contract_batch_after_split_failure(
                novel_package=SimpleNamespace(outline=SimpleNamespace(title="测试", characters=[])),
                story_memory=StoryMemoryPackage(),
                chapter_number=1,
                scene=scene,
                chunk=chunk,
                previous_chunk_exit_state=None,
                previous_tail_segment=None,
                failed_contracts=failed_contracts,
                split_error=initial_split_error,
                effective_expected_segment_count=2,
            )

        self.assertIs(repaired, failed_contracts)
        focus_repair.assert_called_once()

    def _build_overflow_repair_chain_fixture(
        self,
    ) -> tuple[ChapterSceneSchema, SceneSegmentChunkSchema, SceneSegmentContractBatchSchema]:
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "title": "初次对话",
                "summary": "两人在长椅旁完成第一轮对话。",
                "scene_anchor": "郁金香花园长椅",
                "involved_characters": ["林屿", "苏晚"],
                "covered_event_ids": ["ch01-ev02"],
                "scene_bible": {
                    "location": "郁金香花园长椅",
                    "background_anchors": ["长椅", "郁金香花丛"],
                    "spatial_layout": "长椅位于花丛旁",
                    "character_blocking": "两人在长椅旁面对面站立",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc02-chunk01",
                "order_index": 1,
                "title": "第一轮对话",
                "summary": "林屿和苏晚开始对话。",
                "must_cover": ["林屿开口", "苏晚回应"],
                "transition_goal": "两人完成第一轮对话。",
                "expected_segment_count": 2,
            }
        )
        failed_contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc02",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc02-seg02",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc02",
                        "title": "对话停顿",
                        "summary": "林屿说完后苏晚短暂停顿。",
                        "involved_characters": ["林屿", "苏晚"],
                        "timed_beats": ["0-8秒：两人面对面完成第一轮对话。"],
                        "duration_seconds": 8,
                        "transition_hint": "start",
                        "shot_state": {
                            "framing": "双人中景",
                            "camera_motion": "固定镜头",
                            "blocking": "两人面对面站立",
                            "action_progression": "林屿开口，苏晚回应",
                            "emotion_progression": "紧张到安静",
                            "prop_continuity": "无特殊持物",
                            "screen_direction": "保持面对面轴线",
                            "end_state_lock": "两人完成第一轮对话。",
                        },
                        "continuity_link": {
                            "transition_mode": "start",
                            "opening_match": "两人在长椅旁面对面站立。",
                            "carry_over_elements": ["长椅", "郁金香花丛"],
                            "allowed_changes": "林屿开口，苏晚回应。",
                            "transition_reason": "chunk 起始。",
                        },
                        "motion_plan": {
                            "scene_motion": "两人在长椅旁完成对话。",
                            "beat_progression": "0-8秒两人面对面完成第一轮对话。",
                            "camera_path": "固定镜头。",
                            "character_motion": "两人保持面对面。",
                            "continuity_guard": "保持同一长椅空间。",
                        },
                    }
                ],
            }
        )
        return scene, chunk, failed_contracts

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

    def test_resume_from_progress_rejects_checkpoint_without_chunks(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief(
            title_hint="缺少 chunk 的进度拒绝恢复",
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
            output_root=self.temp_root / "incomplete-progress-source",
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
                    "error": "missing chunk checkpoint",
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
                            "error": "missing chunk checkpoint" if index == 0 else "",
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

    def test_chapter_scene_transition_entry_with_weak_overlap_is_backfilled(self) -> None:
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc03",
                "chapter_number": 1,
                "title": "图书馆旁花田",
                "summary": "两人沿着花田边缘来到图书馆旁。",
                "scene_anchor": "图书馆旁花田 / 傍晚",
                "involved_characters": ["陈默", "林晚"],
                "covered_event_ids": ["ch01-ev03"],
                "scene_transition_contract": {
                    "previous_scene_id": "ch01-sc02",
                    "transition_mode": "adjacent_move",
                    "previous_scene_exit_state": "两人离开镜湖步道。",
                    "next_scene_entry_match": "继续沿着路往前走，气氛仍然安静。",
                    "bridge_action": "两人沿路继续前行，转入图书馆旁花田。",
                    "carry_over_elements": ["并肩关系", "安静情绪"],
                    "screen_direction_policy": "保持向前行进。",
                    "visual_bridge": "从步道边缘带出花田和图书馆外立面。",
                    "transition_focus_seconds": 2,
                },
                "scene_bible": {
                    "location": "图书馆旁花田",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "夕阳侧光",
                    "background_anchors": ["图书馆外立面", "红色郁金香", "石板路"],
                    "fixed_props": ["花田围栏"],
                    "spatial_layout": "石板路穿过花田，远处是图书馆外立面",
                    "character_blocking": "两人并肩停在花田边缘看向图书馆方向",
                    "continuity_notes": "保持花田、石板路和图书馆外立面的空间关系稳定",
                },
            }
        )

        entry_match = scene.scene_transition_contract.next_scene_entry_match

        self.assertIn("图书馆旁花田", entry_match)
        self.assertIn("两人并肩停在花田边缘看向图书馆方向", entry_match)
        self.assertIn("图书馆外立面", entry_match)
        self.assertIn("继续沿着路往前走", entry_match)

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

    def test_focus_repair_validator_warns_instead_of_failing_on_chunk_goal_landing(self) -> None:
        service = NovelToVideoService()
        scene = ChapterSceneSchema.model_validate(
            {
                "scene_id": "ch01-sc03",
                "chapter_number": 1,
                "title": "长廊相遇",
                "summary": "林屿和苏晚在长廊边相遇，准备进入对话。",
                "scene_anchor": "长廊出口与花圃交界处",
                "involved_characters": ["林屿", "苏晚"],
                "scene_bible": {
                    "location": "长廊出口与花圃交界处",
                    "time_window": "傍晚",
                    "weather": "微风",
                    "lighting": "夕阳低角度暖光",
                    "background_anchors": ["长廊", "花圃"],
                    "fixed_props": ["石板路"],
                    "spatial_layout": "长廊出口连接花圃边缘",
                    "character_blocking": "两人同框站在长廊出口附近",
                    "continuity_notes": "保持长廊与花圃关系稳定",
                },
            }
        )
        chunk = SceneSegmentChunkSchema.model_validate(
            {
                "chunk_id": "ch01-sc03-chunk1",
                "order_index": 1,
                "title": "准备说话",
                "summary": "两人相遇后停下，准备进入对话。",
                "must_cover": ["两人相遇", "停下"],
                "transition_goal": "两人进入对话。",
                "expected_segment_count": 1,
            }
        )
        contracts = SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": "ch01-sc03",
                "chapter_number": 1,
                "segments": [
                    {
                        "segment_id": "ch01-sc03-seg01",
                        "chapter_number": 1,
                        "scene_id": "ch01-sc03",
                        "title": "同框停下",
                        "summary": "林屿和苏晚在长廊出口附近同框停下。",
                        "involved_characters": ["林屿", "苏晚"],
                        "timed_beats": [
                            "0-3秒：林屿和苏晚在长廊出口附近同框停下。",
                            "3-6秒：两人保持沉默，尚未进入对话。",
                        ],
                        "duration_seconds": 6,
                        "transition_hint": "start",
                        "shot_state": {
                            "framing": "双人中景，林屿和苏晚保持同框。",
                            "camera_motion": "固定镜头轻微呼吸感，保持两人同框。",
                            "blocking": "两人站在长廊出口附近。",
                            "action_progression": "两人相遇后停下，仍停在开口前的一刻。",
                            "emotion_progression": "安静、犹豫。",
                            "prop_continuity": "无特殊持物。",
                            "screen_direction": "两人面对面。",
                            "end_state_lock": "两人停在开口前的一刻。",
                        },
                        "continuity_link": {
                            "transition_mode": "start",
                            "opening_match": "长廊出口与花圃交界处，两人同框。",
                            "carry_over_elements": ["长廊", "花圃"],
                            "allowed_changes": "两人停下。",
                            "transition_reason": "scene 起始段。",
                        },
                        "motion_plan": {
                            "scene_motion": "两人在场景母图空间中停下。",
                            "beat_progression": "0-3秒同框停下；3-6秒保持沉默。",
                            "camera_path": "固定镜头。",
                            "character_motion": "两人停步。",
                            "continuity_guard": "保持长廊和花圃空间稳定。",
                        },
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "没有真正落到当前 chunk 的结果"):
            service._validate_scene_chunk_contract_output(
                contracts,
                scene=scene,
                chunk=chunk,
                effective_expected_segment_count=1,
            )

        warnings: list[str] = []
        validated = service._validate_scene_chunk_contract_output(
            contracts,
            scene=scene,
            chunk=chunk,
            effective_expected_segment_count=1,
            landing_strict=False,
            warning_sink=warnings,
        )

        self.assertEqual(validated.scene_id, "ch01-sc03")
        self.assertTrue(any("没有真正落到当前 chunk 的结果" in item for item in warnings))

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

    def test_scene_master_frame_prompt_filters_human_actions_from_spatial_transition(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc02",
                chapter_number=1,
                title="长廊出口",
                summary="苏晚从长廊方向走近林序。",
                scene_anchor="郁金香花园花圃边缘，长廊出口与花丛交界处",
                involved_characters=["林序", "苏晚"],
                covered_event_ids=[],
                segments=[],
                scene_transition_contract=SceneTransitionContract(
                    previous_scene_id="ch01-sc01",
                    scene_spatial_continuity_mode="same_space_progression",
                    shared_environment_anchors=["红色郁金香花丛", "夕阳琥珀色光线", "操场广播声"],
                    spatial_relation_to_previous="同一花圃，视线从林序转向长廊方向，苏晚进入画面",
                    camera_handoff="从林序面部特写拉远，摇向长廊方向，跟随苏晚走近",
                    allowed_environment_changes="苏晚进入场景，长廊出口纳入画面",
                    forbidden_drift="不得改变花圃布局、夕阳光线角度或林序手中花的位置",
                ),
                scene_bible=SceneBible(
                    location="教学楼后的郁金香花园，第三排红色郁金香旁",
                    time_window="傍晚六点零七分",
                    weather="晴朗，有微风",
                    lighting="夕阳琥珀色光线，低角度暖光",
                    dominant_palette=["琥珀色", "红色", "白色"],
                    background_anchors=["操场广播方向", "红色郁金香花丛", "远处长廊入口", "教学楼轮廓"],
                    fixed_props=["红色郁金香花丛", "白色郁金香花茎", "花圃边缘地面"],
                    spatial_layout="郁金香花园第三排红色郁金香旁；郁金香花园攥着白色郁金香；长廊入口",
                    continuity_notes="保持花圃和长廊出口的空间关系稳定。",
                ),
            )
        )

        self.assertIn("长廊入口", prompt)
        self.assertIn("红色郁金香花丛", prompt)
        self.assertIn("单图输入、单图输出的场景母图编辑任务", prompt)
        self.assertIn("图片1 是上一场场景母图，必须作为视觉母版使用", prompt)
        self.assertIn("美术风格、线条粗细、上色方式、镜头焦段、透视关系、空间尺度", prompt)
        self.assertIn("固定道具相对位置不变", prompt)
        self.assertIn("背景锚点应能看出属于同一地点", prompt)
        self.assertNotIn("攥着", prompt)
        self.assertNotIn("手中花", prompt)
        self.assertNotIn("苏晚", prompt)
        self.assertNotIn("林序", prompt)
        self.assertNotIn("面部特写", prompt)
        self.assertNotIn("进入画面", prompt)

    def test_scene_master_frame_prompt_uses_previous_master_as_spatial_template_on_time_jump(self) -> None:
        service = NovelToVideoService()

        prompt = service._build_scene_master_frame_prompt(
            VideoScene(
                scene_id="ch01-sc03",
                chapter_number=1,
                title="雨后的同一花园",
                summary="同一花园在雨后进入下一场。",
                scene_anchor="图书馆旁花园，雨后傍晚",
                involved_characters=["林屿", "苏晚"],
                covered_event_ids=[],
                segments=[],
                scene_transition_contract=SceneTransitionContract(
                    previous_scene_id="ch01-sc02",
                    scene_spatial_continuity_mode="time_jump_same_location",
                    shared_environment_anchors=["图书馆外立面", "石板路", "银杏树"],
                    spatial_relation_to_previous="同一花园，雨后同地点",
                    allowed_environment_changes="雨后地面反光，光线更冷",
                    forbidden_drift="不得改变石板路与银杏树的位置关系",
                ),
                scene_bible=SceneBible(
                    location="图书馆旁花园",
                    time_window="雨后傍晚",
                    weather="小雨刚停",
                    lighting="冷金色天光与湿润反光",
                    dominant_palette=["冷金色", "绿色", "灰蓝色"],
                    background_anchors=["图书馆外立面", "石板路", "银杏树"],
                    fixed_props=["石板路", "银杏树干", "花田围栏"],
                    spatial_layout="银杏树在花园尽头，石板路从花田中穿过。",
                    continuity_notes="保持图书馆、石板路和银杏树的空间关系稳定。",
                ),
            )
        )

        self.assertIn("单图输入、单图输出的同地点时间变化编辑任务", prompt)
        self.assertIn("图片1 是同一地点的上一场母图，必须作为空间母版使用", prompt)
        self.assertIn("保持图片1的透视关系、空间尺度、地面材质", prompt)
        self.assertIn("固定道具位置关系不变", prompt)
        self.assertIn("只允许时间、天气、光线强度和色温按本场基线变化", prompt)
        self.assertIn("图书馆外立面", prompt)
        self.assertNotIn("林屿", prompt)
        self.assertNotIn("苏晚", prompt)

    def test_same_space_scene_uses_previous_master_as_reference_without_reusing_url(self) -> None:
        service = NovelToVideoService()
        previous_scene = VideoScene(
            scene_id="ch01-sc01",
            chapter_number=1,
            title="花丛中央",
            summary="林叙站在花丛中央等待。",
            scene_anchor="郁金香花园花丛中央",
            involved_characters=["林叙"],
            covered_event_ids=[],
            segments=[],
            scene_bible=SceneBible(location="郁金香花园花丛中央"),
            scene_master_frame_path="/tmp/ch01-sc01_master.png",
            scene_master_frame_url="https://example.com/ch01-sc01-master.png",
            scene_master_frame_status="completed",
        )
        next_scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="入口出现",
            summary="苏晚从同一花园入口出现。",
            scene_anchor="同一郁金香花园入口",
            involved_characters=["林叙", "苏晚"],
            covered_event_ids=[],
            segments=[],
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="direct_continue",
                scene_spatial_continuity_mode="same_space_progression",
                shared_environment_anchors=["郁金香花丛", "夕阳天际线"],
            ),
            scene_bible=SceneBible(location="郁金香花园入口处"),
            scene_master_frame_path="/tmp/ch01-sc02_master.png",
            scene_master_frame_status="planned",
        )
        segment = VideoSegment(
            segment_id="ch01-sc02-seg01",
            chapter_number=1,
            scene_id="ch01-sc02",
            scene_title="入口出现",
            scene_summary="苏晚从同一花园入口出现。",
            scene_anchor="同一郁金香花园入口",
            title="入口出现",
            summary="苏晚出现。",
            involved_characters=["林叙", "苏晚"],
            narration="",
            dialogue_lines=[],
            subtitle_lines=[],
            sound_effects=[],
            music_direction="",
            timed_beats=["0-6秒：苏晚出现。"],
            duration_seconds=6,
            scene_bible=next_scene.scene_bible,
            shot_state=ShotState(),
            continuity_link=ContinuityLink(),
            motion_plan=MotionPlan(),
        )

        tasks = service._build_scene_image_tasks(
            [previous_scene, next_scene],
            [segment],
            [],
            {},
            str(self.temp_root),
        )

        self.assertEqual(tasks[0].scene_master_frame_url, "")
        self.assertEqual(tasks[0].scene_master_frame_path, "/tmp/ch01-sc02_master.png")
        self.assertEqual(tasks[0].scene_master_frame_status, "planned")
        self.assertEqual(tasks[0].reference_images, ["https://example.com/ch01-sc01-master.png"])
        self.assertEqual(next_scene.scene_master_frame_url, "")
        self.assertEqual(next_scene.scene_master_reference_images, ["https://example.com/ch01-sc01-master.png"])
        self.assertEqual(next_scene.scene_master_request_info, {})

    def test_scene_master_reference_images_do_not_fallback_to_local_previous_path(self) -> None:
        service = NovelToVideoService()
        previous_scene = VideoScene(
            scene_id="ch01-sc01",
            chapter_number=1,
            title="上一场",
            summary="上一场",
            scene_anchor="上一场",
            involved_characters=[],
            covered_event_ids=[],
            segments=[],
            scene_master_frame_path="/tmp/local-only-master.png",
            scene_master_frame_url="",
        )
        next_scene = VideoScene(
            scene_id="ch01-sc02",
            chapter_number=1,
            title="下一场",
            summary="下一场",
            scene_anchor="下一场",
            involved_characters=[],
            covered_event_ids=[],
            segments=[],
            scene_transition_contract=SceneTransitionContract(
                previous_scene_id="ch01-sc01",
                transition_mode="direct_continue",
                scene_spatial_continuity_mode="same_space_progression",
            ),
        )

        self.assertEqual(service._scene_master_reference_images(next_scene, previous_scene), [])

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
            duration_seconds=6,
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
            motion_plan=MotionPlan(
                scene_motion="林远独自站在栈道入口，先保持等待姿态，再轻微抬眼望向前方。",
                beat_progression="0-3秒建立栈道入口等待状态，3-6秒视线抬起后在原地收束。",
                camera_path="固定镜头轻微呼吸感。",
                character_motion="林远只有视线和呼吸节奏变化，身体不明显位移。",
                continuity_guard="保持同一栈道入口空间，不要换景或新增角色。",
            ),
        )

        prompt = service._build_seedance_clip_prompt(segment)

        self.assertIn("本段无对白、无旁白、无字幕", prompt)
        self.assertIn("字幕约束：本段没有可烧录字幕", prompt)
        self.assertNotIn("参考图绑定：", prompt)
        self.assertNotIn("提交阶段会绑定当前 scene 的场景母图", prompt)
        self.assertNotIn("图片2 及之后是实际出镜角色定妆图", prompt)
        self.assertIn("画面推进 0-3秒：先在场景母图锁定的空间里建立开场状态", prompt)
        self.assertIn("画面推进 3-6秒：最后在同一场景空间里自然收束到", prompt)
        self.assertIn("这一段拍出“林远在栈道入口停住，望向前方”", prompt)
        self.assertNotIn("片段标题：", prompt)
        self.assertNotIn("参考图片时间轴：", prompt)
        self.assertNotIn("硬字幕文案：", prompt)
        self.assertNotIn("请把上述字幕直接烧录到画面底部", prompt)
        self.assertNotIn("手机相关细节声", prompt)

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
            duration_seconds=6,
            continuity_link=ContinuityLink(
                previous_segment_id="",
                transition_mode="start",
                opening_match="开场先承接两人并肩前行的状态，再带出镜湖步道。",
                carry_over_elements=["并肩关系", "向右前方行进"],
                allowed_changes="从花廊出口过渡到镜湖步道空间。",
                transition_reason="新 scene 首段继续承接上一场尾部。",
            ),
            motion_plan=MotionPlan(
                scene_motion="两人保持并肩前行，从花廊出口自然走入镜湖步道。",
                beat_progression="先承接并肩前行，再显露镜湖步道与栏杆，最后放慢脚步。",
                camera_path="跟随两人脚步轻微横移并顺势 reveal 湖面栏杆。",
                character_motion="陈默和林晚保持并肩关系向右前方行进。",
                continuity_guard="保持上一场方向和并肩关系，不要突然反向或换景。",
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

if __name__ == "__main__":
    unittest.main()
