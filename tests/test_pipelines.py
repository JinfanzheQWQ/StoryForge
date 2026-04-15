from __future__ import annotations

import json
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
from storyforge.core.io import read_json  # noqa: E402
from storyforge.agents.base import DryRunAgentBackend, PromptRequest  # noqa: E402
from storyforge.domains.novel.contracts import CharacterProfile, StoryBrief  # noqa: E402
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
    CharacterRosterSchema,
    StoryArchitectureSchema,
    StoryDraftSetSchema,
)
from storyforge.domains.novel.service import NovelGeneratorService  # noqa: E402
from storyforge.domains.video.contracts import CharacterVisualProfile, VideoSegment  # noqa: E402
from storyforge.domains.video.schemas import CharacterVisualBibleSchema, VideoSegmentPlanSchema  # noqa: E402
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from storyforge.integrations.seedance import SeedanceExecutionReport  # noqa: E402
from storyforge.integrations.seedream import SeedreamExecutionReport  # noqa: E402
from storyforge.pipelines.story_pipeline import run_story_pipeline  # noqa: E402
from storyforge.pipelines.video_pipeline import (  # noqa: E402
    run_scene_image_pipeline,
    run_video_merge_pipeline,
    run_video_pipeline,
    run_video_render_pipeline,
)
from storyforge.pipelines.video_planning import (  # noqa: E402
    build_video_planning_artifacts,
    load_video_planning_artifacts,
)


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._story_backend_patcher = patch(
            "storyforge.pipelines.story_pipeline.build_agent_backend",
            return_value=DryRunAgentBackend(),
        )
        self._video_backend_patcher = patch(
            "storyforge.pipelines.video_planning.build_agent_backend",
            return_value=DryRunAgentBackend(),
        )
        self._story_backend_patcher.start()
        self._video_backend_patcher.start()
        self.addCleanup(self._story_backend_patcher.stop)
        self.addCleanup(self._video_backend_patcher.stop)
        self.temp_root = ROOT / "tests/.tmp"
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)
        self.temp_root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root)

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
        brief = StoryBrief(
            title_hint="站台告白",
            idea="一个女生在列车离站前向喜欢多年的男生告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )

        result = service._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "story-architect"},
            ),
            fallback=service._fallback_architecture(brief),
        )

        self.assertEqual(result.title, "站台告白")
        self.assertEqual(service.backend.calls, 3)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 3)
        self.assertIn("上一次输出未通过结构化校验", service.backend.requests[-1].user_prompt)

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
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        planning = build_video_planning_artifacts(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            use_llm=False,
        )

        self.assertEqual(planning.manifest.title, story_result.novel_package.outline.title)

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
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )

        planning = build_video_planning_artifacts(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            use_llm=False,
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
        brief = StoryBrief(
            title_hint="站台告白",
            idea="一个女生在列车离站前向喜欢多年的男生告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )

        with self.assertRaises(NovelStructuredGenerationError) as ctx:
            service._run_structured_agent(
                schema=StoryArchitectureSchema,
                request=PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "story-architect"},
                ),
                fallback=service._fallback_architecture(brief),
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
        brief = StoryBrief(
            title_hint="站台告白",
            idea="一个女生在列车离站前向喜欢多年的男生告白。",
            genre="都市情感",
            tone="克制、电影感",
            chapter_count=1,
            total_word_target=1200,
        )

        with self.assertRaises(NovelStructuredGenerationError) as ctx:
            service._run_structured_agent(
                schema=StoryArchitectureSchema,
                request=PromptRequest(
                    system_prompt="system",
                    user_prompt="user",
                    metadata={"task": "story-architect"},
                ),
                fallback=service._fallback_architecture(brief),
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
        fallback = CharacterRosterSchema.model_validate(
            {
                "characters": [
                    {
                        "cast_slot_id": "lead_1",
                        "name": "林雾",
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
                        "image_prompt": "林雾，男，站台上的人。",
                    }
                ]
            }
        )

        result = service._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "character-designer"},
            ),
            fallback=fallback,
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
        fallback = CharacterRosterSchema.model_validate(
            {
                "characters": [
                    {
                        "cast_slot_id": "lead_1",
                        "name": "林雾",
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
                        "image_prompt": "林雾，男，站台上的人。",
                    }
                ]
            }
        )

        result = service._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt="system",
                user_prompt="user",
                metadata={"task": "character-designer"},
            ),
            fallback=fallback,
        )

        self.assertEqual(service.backend.calls, 2)
        self.assertEqual([item.cast_slot_id for item in result.characters], ["lead_1", "lead_2"])
        self.assertIn("重复槽位", service.backend.requests[-1].user_prompt)
        self.assertEqual(service.backend.requests[-1].metadata["structured_retry_attempt"], 2)

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
        cast_analysis = service._fallback_cast_analysis(brief, architecture)
        expected_slots = cast_analysis.primary_slots(
            max(1, cast_analysis.recommended_core_cast_count)
        )
        fallback = CharacterRosterSchema.model_validate(
            {
                "characters": [
                    {
                        "cast_slot_id": "lead_1",
                        "name": "林雾",
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
                        "image_prompt": "林雾，男，站台上的人。",
                    }
                ]
            }
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
            fallback=fallback,
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

    def test_story_and_video_pipeline(self) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")

        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        self.assertTrue(story_result.story_source_path.exists())
        self.assertTrue(story_result.novel_package_path.exists())
        self.assertTrue(story_result.novel_audit_path.exists())
        self.assertTrue(story_result.character_bible_path.exists())
        self.assertTrue(story_result.character_images_path.exists())
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
        self.assertIsNone(video_result.full_story_path)
        self.assertGreater(len(video_result.project_package.segments), 0)
        self.assertGreater(len(video_result.project_package.seedance_manifest.clips), 0)
        self.assertEqual(
            {item.chapter_number for item in video_result.project_package.segments},
            {item.number for item in story_result.novel_package.outline.chapters},
        )
        self.assertTrue(
            any(item.dialogue_lines for item in video_result.project_package.segments)
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
            all("统一三视图模板 SF-TURN-01" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("横版 16:9" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("纯白色" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("左栏正面，中栏左侧面，右栏背面" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("画面顶部只允许出现角色中文姓名" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("画面唯一可见文字：" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all(
                "不得写性别、身份、职业、角色定位" in item.prompt
                for item in video_result.project_package.character_images
            )
        )
        self.assertTrue(
            all("同一种美术风格" in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("主配色" not in item.prompt for item in video_result.project_package.character_images)
        )
        self.assertTrue(
            all("2x2 信息格" not in item.prompt for item in video_result.project_package.character_images)
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
        self.assertTrue(
            all("禁止出现任何可见文字" in item.scene_prompt for item in video_result.project_package.scene_images)
        )
        self.assertTrue(
            all("所有对白和硬字幕都只在后续视频阶段添加" in item.start_frame_prompt for item in video_result.project_package.scene_images)
        )
        self.assertTrue(
            all("不要提前画进图片里" in item.end_frame_prompt for item in video_result.project_package.scene_images)
        )
        self.assertFalse(video_result.seedream_execution.submitted)
        self.assertFalse(video_result.seedance_execution.submitted)

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

    def test_fallback_character_roster_only_covers_requested_slots(self) -> None:
        service = NovelGeneratorService()
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

        roster = service._fallback_character_roster(
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

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertIsNone(segment_ids)
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

        def fake_execute_manifest(manifest, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertIsNone(segment_ids)
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

        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=config,
            project_root=ROOT,
            output_root=story_result.output_dir,
            submit_seedance=True,
        )

        self.assertIsNone(video_result.full_story_path)
        self.assertEqual(len(video_result.rendered_clip_paths), len(video_result.manifest.clips))

    @patch("storyforge.pipelines.video_pipeline.concat_manifest_clips")
    def test_run_video_merge_pipeline_concats_rendered_clips_on_demand(
        self,
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
        manifest_payload = read_json(story_result.seedance_manifest_path)
        rendered_dir = story_result.output_dir / "rendered"
        rendered_dir.mkdir(parents=True, exist_ok=True)
        for index, clip in enumerate(manifest_payload["clips"][:2], start=1):
            clip_path = rendered_dir / f"clip-{index}.mp4"
            clip_path.write_bytes(b"clip")
            clip["downloaded_path"] = str(clip_path)
            clip["submit_status"] = "completed"
            clip["remote_status"] = "succeeded"
        story_result.seedance_manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
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

    @patch("storyforge.pipelines.video_pipeline.SeedreamClient.generate_scene_images")
    def test_run_scene_image_pipeline_only_updates_selected_segment(
        self,
        mock_generate_scene_images,
    ) -> None:
        config = AppConfig.load(ROOT / "configs/storyforge.example.toml")
        brief = StoryBrief.from_file(ROOT / "examples/briefs/demo_story.toml")
        story_result = run_story_pipeline(
            brief=brief,
            config=config,
            project_root=ROOT,
            output_root=self.temp_root,
        )
        selected_segment_id = read_json(story_result.segment_plan_path)[0]["segment_id"]

        def fake_generate_scene_images(project_package, force_submit=False, segment_ids=None):
            self.assertTrue(force_submit)
            self.assertEqual(segment_ids, {selected_segment_id})
            for task in project_package.scene_images:
                if task.segment_id != selected_segment_id:
                    continue
                task.start_frame_url = f"https://example.com/{Path(task.start_frame_path).name}"
                task.end_frame_url = f"https://example.com/{Path(task.end_frame_path).name}"
                task.status = "completed"
            for clip in project_package.seedance_manifest.clips:
                if clip.segment_id != selected_segment_id:
                    continue
                clip.start_frame_url = f"https://example.com/{Path(clip.start_frame_path).name}"
                clip.end_frame_url = f"https://example.com/{Path(clip.end_frame_path).name}"
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

    @patch("storyforge.pipelines.video_pipeline.concat_manifest_clips")
    @patch("storyforge.pipelines.video_pipeline.SeedanceClient.execute_manifest")
    def test_run_video_render_pipeline_only_selected_segment_skips_full_concat(
        self,
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
            selected_output_path.parent.mkdir(parents=True, exist_ok=True)
            selected_output_path.write_bytes(b"selected clip")
            clip = next(item for item in manifest.clips if item.segment_id == selected_segment_id)
            clip.downloaded_path = str(selected_output_path)
            clip.submit_status = "completed"
            clip.remote_status = "succeeded"
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

    def test_frame_character_lists_are_inferred_and_preserved_separately(self) -> None:
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
                        "scene_prompt": "花廊中的等待与相遇。",
                        "start_frame_prompt": f"{first_character.name}独自站在花廊入口处等待。",
                        "mid_frame_prompt": f"{first_character.name}看见{second_character.name}从花园小径走来。",
                        "end_frame_prompt": f"{first_character.name}仍独自望向小径方向。",
                        "duration_seconds": 5,
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
                        "scene_prompt": "傍晚时分的大学中心花园。",
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
        self.assertIn("固定索引合同", prompt)
        self.assertIn("characters[0].cast_slot_id", prompt)
        self.assertIn("characters[1].cast_slot_id", prompt)

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
        self.assertIn("按中文自然口播语速估算音频长度", prompt)
        self.assertIn("如果旁白、对白或硬字幕超过当前时长可说完的字数，必须拆成下一个片段", prompt)
        self.assertIn("硬字幕超过当前时长可说完", prompt)
        self.assertIn("requires_mid_frame", prompt)
        self.assertIn("mid_frame_prompt", prompt)
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
        self.assertTrue(all(item.requires_mid_frame for item in normalized.segments))
        self.assertTrue(all(item.mid_frame_prompt for item in normalized.segments))
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
        self.assertTrue(scene_tasks[0].requires_mid_frame)
        self.assertTrue(scene_tasks[0].mid_frame_path.endswith("_mid.png"))
        self.assertTrue(scene_tasks[1].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[1].continuity_source_segment_id, "snowport_01_01")
        self.assertTrue(scene_tasks[1].requires_mid_frame)
        self.assertTrue(scene_tasks[2].reuse_previous_end_frame)
        self.assertEqual(scene_tasks[2].continuity_source_segment_id, "snowport_01_02")
        self.assertTrue(scene_tasks[2].requires_mid_frame)

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
                        "scene_prompt": "雨棚下双人对话。",
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
        self.assertTrue(all(item.requires_mid_frame for item in normalized.segments))
        self.assertTrue(all(item.mid_frame_prompt for item in normalized.segments))
        self.assertEqual(
            [item.source_segment_id for item in normalized.segments],
            ["confession_01"] * len(normalized.segments),
        )
        self.assertTrue(all(item.subtitle_lines for item in normalized.segments))
        self.assertTrue(any(item.dialogue_lines for item in normalized.segments[1:]))

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

        scene_prompt = service._stylize_scene_prompt(
            '雨棚下的告白场景，字幕：我喜欢你很久了，“毕业快乐”。',
            VideoSegment(
                segment_id="seg-1",
                chapter_number=1,
                title="测试片段",
                summary="测试摘要",
                involved_characters=["林远", "苏晴"],
                narration="旁白",
                dialogue_lines=["林远：我喜欢你很久了。"],
                subtitle_lines=["我喜欢你很久了。"],
                sound_effects=["风声"],
                music_direction="青春克制",
                timed_beats=["0-5秒：两人对视。"],
                scene_prompt="原始场景",
                start_frame_prompt="原始首帧",
                end_frame_prompt="原始尾帧",
                duration_seconds=5,
            ),
            "角色锁定要求",
        )
        frame_prompt = service._stylize_frame_prompt(
            '林远说：我喜欢你很久了。屏幕显示：毕业倒计时。',
            ["林远"],
            "首帧",
            "角色锁定要求",
        )

        self.assertIn("禁止出现任何可见文字", scene_prompt)
        self.assertIn("所有对白和硬字幕都只在后续视频阶段添加", frame_prompt)
        self.assertNotIn("我喜欢你很久了", frame_prompt)
        self.assertNotIn("毕业倒计时", frame_prompt)
        self.assertIn("林远正在说话", frame_prompt)

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
