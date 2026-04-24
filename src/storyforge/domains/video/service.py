from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackend,
    PromptRequest,
    UnavailableAgentBackend,
)
from storyforge.core.io import to_jsonable
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.chapter_event_validation import VideoChapterEventValidationMixin
from storyforge.domains.video.chapter_orchestration import VideoChapterOrchestrationMixin
from storyforge.domains.video.chunk_orchestration import VideoSceneChunkOrchestrationMixin
from storyforge.domains.video.contracts import (
    StoryMemoryPackage,
    VideoProjectPackage,
)
from storyforge.domains.video.enrichment import VideoEnrichmentMixin
from storyforge.domains.video.materialization import VideoMaterializationMixin
from storyforge.domains.video.planning import VideoPlanningMixin
from storyforge.domains.video.prompting import VideoPromptingMixin
from storyforge.domains.video.repair import VideoRepairMixin
from storyforge.domains.video.segment_validation import VideoSegmentValidationMixin
from storyforge.domains.video.structure_validation import VideoStructureValidationMixin
from storyforge.domains.video.structured_generation import VideoStructuredGenerationMixin
from storyforge.domains.video.structured_retry_prompts import VideoStructuredRetryPromptMixin
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    VideoSegmentPlanSchema,
)

StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
class NovelToVideoService(
    VideoStructuredRetryPromptMixin,
    VideoStructuredGenerationMixin,
    VideoChapterEventValidationMixin,
    VideoSegmentValidationMixin,
    VideoStructureValidationMixin,
    VideoChapterOrchestrationMixin,
    VideoSceneChunkOrchestrationMixin,
    VideoPromptingMixin,
    VideoRepairMixin,
    VideoEnrichmentMixin,
    VideoMaterializationMixin,
    VideoPlanningMixin,
):
    CHAPTER_EVENT_END_COVERAGE_MIN_RATIO = 0.72
    CHAPTER_EVENT_END_COVERAGE_MEDIUM_RATIO = 0.64
    CHAPTER_EVENT_END_COVERAGE_SHORT_RATIO = 0.58
    CHAPTER_EVENT_END_COVERAGE_MEDIUM_MIN_CHARS = 360
    CHAPTER_EVENT_END_COVERAGE_SHORT_MIN_CHARS = 120
    PLANNER_MIN_DURATION_SECONDS = 5
    SEEDANCE_MIN_DURATION_SECONDS = 2
    SEEDANCE_MAX_DURATION_SECONDS = 12
    TIMED_BEAT_COVERAGE_TOLERANCE_SECONDS = 0.75
    SPEECH_CHARS_PER_SECOND = 3
    SCENE_SEGMENT_CHUNK_MAX_SEGMENTS = 4
    SCENE_MAX_EXPECTED_SEGMENTS = 8
    CHAPTER_EVENT_MAX_PROGRESS_NODES = 2
    CHAPTER_EVENT_EDGE_MAX_PROGRESS_NODES = 3
    SEGMENT_ACTION_NODE_BUDGET_SHORT = 2
    SEGMENT_ACTION_NODE_BUDGET_LONG = 3

    def __init__(
        self,
        backend: AgentBackend | None = None,
        segment_duration_seconds: int = 5,
        aspect_ratio: str = "16:9",
        fps: int = 24,
        character_image_provider: str = "prompt-only",
        scene_image_provider: str = "prompt-only",
        seedance_config: SeedanceConfig | None = None,
        structured_retry_attempts: int = 3,
    ) -> None:
        self.backend = backend or UnavailableAgentBackend(
            "NovelToVideoService requires a live LLM backend."
        )
        self.segment_duration_seconds = segment_duration_seconds
        self.aspect_ratio = aspect_ratio
        self.fps = fps
        self.character_image_provider = character_image_provider
        self.scene_image_provider = scene_image_provider
        self.seedance_config = seedance_config or SeedanceConfig()
        self.structured_retry_attempts = max(1, structured_retry_attempts)
        self._planner_warnings: list[str] = []

    def _record_planner_warning(self, message: str) -> None:
        normalized = " ".join(str(message or "").split()).strip()
        if normalized and normalized not in self._planner_warnings:
            self._planner_warnings.append(normalized)

    def _flush_planner_warnings_to_story_memory(
        self,
        story_memory: StoryMemoryPackage,
    ) -> StoryMemoryPackage:
        if not self._planner_warnings:
            return story_memory
        existing = [
            " ".join(str(item or "").split()).strip()
            for item in story_memory.generation_notes.planner_warnings
            if " ".join(str(item or "").split()).strip()
        ]
        for warning in self._planner_warnings:
            if warning not in existing:
                existing.append(warning)
        story_memory.generation_notes.planner_warnings = existing[-40:]
        self._planner_warnings = []
        return story_memory

    def build_video_project(self, novel_package: NovelPackage, output_dir: str) -> VideoProjectPackage:
        visual_bible = self._run_structured_agent(
            schema=CharacterVisualBibleSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是影视角色视觉设计 Agent。"
                    "请把小说角色转换成稳定、可复用的角色视觉设定。"
                    "输出要偏风格化概念设计，不要写成真人摄影或现实人物描述。"
                ),
                user_prompt=self._build_visual_bible_user_prompt(novel_package),
                metadata={"task": "video-character-bible"},
            ),
            validator=lambda value: self._validate_character_visual_bible_output(
                value,
                novel_package=novel_package,
            ),
        )
        visual_bible = self._repair_character_visual_bible(visual_bible, novel_package)

        story_memory = self._build_story_memory(
            novel_package,
            visual_bible,
            output_dir,
        )
        segments_plan, story_memory = self._build_segment_plan_by_chapter(
            novel_package,
            visual_bible,
            story_memory,
        )

        character_profiles = self._build_character_profiles(visual_bible)
        profile_map = {item.name: item for item in character_profiles}
        voice_map = self._build_voice_map(novel_package)
        character_images = self._build_character_image_tasks(character_profiles, output_dir)
        scenes = self._build_runtime_scenes(segments_plan, output_dir)
        segments = self._build_runtime_segments(segments_plan, voice_map)
        scene_images = self._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            output_dir,
        )
        manifest = self._build_seedance_manifest(
            novel_package.outline.title,
            scenes,
            segments,
            scene_images,
            output_dir,
        )

        return VideoProjectPackage(
            title=novel_package.outline.title,
            character_profiles=character_profiles,
            character_images=character_images,
            scenes=scenes,
            segments=segments,
            scene_images=scene_images,
            seedance_manifest=manifest,
            story_memory=story_memory,
            workflow_trace={
                "character_visual_bible": visual_bible.model_dump(),
                "story_memory": to_jsonable(story_memory),
                "scene_plan": segments_plan.model_dump(),
                "segment_plan": [
                    item.model_dump()
                    for item in segments_plan.segments
                ],
            },
        )

    def _build_segment_plan_by_chapter(
        self,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
        story_memory,
    ):
        chapter_plans: list[VideoSegmentPlanSchema] = []
        for chapter in sorted(novel_package.outline.chapters, key=lambda item: item.number):
            scene_structure = self._plan_chapter_scene_structure(
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter.number,
            )
            chapter_plan = self._build_chapter_plan_from_scene_structure(
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter.number,
                scene_structure=scene_structure,
            )
            chapter_plan = self._post_process_segment_plan(
                chapter_plan,
                novel_package=novel_package,
                visual_bible=visual_bible,
                normalize_for_seedance=True,
                repair_continuity=True,
            )
            story_memory = self._update_story_memory_after_chapter(
                story_memory,
                novel_package=novel_package,
                chapter_plan=chapter_plan,
                chapter_number=chapter.number,
            )
            story_memory = self._flush_planner_warnings_to_story_memory(story_memory)
            chapter_plans.append(chapter_plan)

        merged_plan = self._merge_chapter_segment_plans(chapter_plans)
        merged_plan = self._post_process_segment_plan(
            merged_plan,
            novel_package=novel_package,
            visual_bible=visual_bible,
            normalize_for_seedance=False,
            repair_continuity=True,
        )
        merged_plan = self._validate_segment_plan_output(
            merged_plan,
            novel_package=novel_package,
        )
        story_memory = self._sync_story_memory_with_plan(
            story_memory,
            novel_package=novel_package,
            plan=merged_plan,
        )
        story_memory = self._flush_planner_warnings_to_story_memory(story_memory)
        return merged_plan, story_memory










    def _post_process_segment_plan(
        self,
        plan: VideoSegmentPlanSchema,
        *,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
        normalize_for_seedance: bool,
        repair_continuity: bool,
    ) -> VideoSegmentPlanSchema:
        plan = self._repair_segment_plan(plan, novel_package, visual_bible)
        plan = self._normalize_segment_characters(plan, novel_package, visual_bible)
        plan = self._repair_scene_bibles(plan, novel_package)
        plan = self._repair_shot_states(plan, novel_package)
        if normalize_for_seedance:
            plan = self._normalize_segments_for_seedance(plan)
            plan = self._repair_scene_bibles(plan, novel_package)
            plan = self._repair_shot_states(plan, novel_package)
        if repair_continuity:
            plan = self._repair_continuity_links(plan)
        return plan







    def _validate_character_visual_bible_output(
        self,
        visual_bible: CharacterVisualBibleSchema,
        *,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        canonical_names = [item.name for item in novel_package.outline.characters]
        canonical_genders = {
            item.name: item.gender
            for item in novel_package.outline.characters
        }
        actual_names = [item.name.strip() for item in visual_bible.characters]
        if len(actual_names) != len(canonical_names):
            raise ValueError(
                "CharacterVisualBibleSchema 角色数量必须与小说角色表一致。"
                f"期望 {len(canonical_names)}，实际 {len(actual_names)}。"
            )
        if set(actual_names) != set(canonical_names):
            raise ValueError(
                "CharacterVisualBibleSchema 角色名必须与小说角色表完全一致。"
                f"期望：{canonical_names}；实际：{actual_names}。"
            )
        for item in visual_bible.characters:
            if not item.appearance.strip() or not item.outfit.strip() or not item.portrait_prompt.strip():
                raise ValueError(
                    f"角色 {item.name} 缺少 appearance / outfit / portrait_prompt。"
                )
            expected_gender = canonical_genders.get(item.name.strip(), "").strip()
            if expected_gender and item.gender.strip() != expected_gender:
                raise ValueError(
                    f"角色 {item.name} 的 gender 必须继承小说角色卡。"
                    f"期望 {expected_gender}，实际 {item.gender!r}。"
                )
        return visual_bible

    def _validate_segment_plan_output(
        self,
        plan: VideoSegmentPlanSchema,
        *,
        novel_package: NovelPackage,
        expected_chapter_numbers: set[int] | None = None,
    ) -> VideoSegmentPlanSchema:
        chapter_numbers = expected_chapter_numbers or {
            item.number for item in novel_package.outline.chapters
        }
        chapter_coverage: dict[int, int] = {
            number: 0 for number in chapter_numbers
        }
        forbidden_meta_phrases = (
            "当前片段聚焦",
            "结尾要保留",
            "当前小段聚焦",
        )
        if not plan.scenes:
            raise ValueError("VideoSegmentPlanSchema.scenes 不能为空。")
        for scene in plan.scenes:
            if scene.chapter_number not in chapter_numbers:
                raise ValueError(
                    f"scene {scene.scene_id} 引用了不存在的 chapter_number={scene.chapter_number}。"
                )
            if not scene.title.strip() or not scene.summary.strip():
                raise ValueError(f"scene {scene.scene_id} 缺少 title 或 summary。")
            if not scene.segments:
                raise ValueError(f"scene {scene.scene_id} 至少需要 1 个 segment。")
        for segment in plan.segments:
            if segment.chapter_number not in chapter_numbers:
                raise ValueError(
                    f"segment {segment.segment_id} 引用了不存在的 chapter_number={segment.chapter_number}。"
                )
            chapter_coverage[segment.chapter_number] = chapter_coverage.get(segment.chapter_number, 0) + 1
            if not segment.involved_characters:
                raise ValueError(f"segment {segment.segment_id} 缺少 involved_characters。")
            if not segment.start_frame_characters:
                raise ValueError(f"segment {segment.segment_id} 缺少 start_frame_characters。")
            if not segment.end_frame_characters:
                raise ValueError(f"segment {segment.segment_id} 缺少 end_frame_characters。")
            if segment.requires_mid_frame and not segment.mid_frame_characters:
                raise ValueError(
                    f"segment {segment.segment_id} requires_mid_frame=true 时缺少 mid_frame_characters。"
                )
            self._validate_segment_direction_consistency(
                segment_id=segment.segment_id,
                screen_direction=segment.shot_state.screen_direction,
                end_state_lock=segment.shot_state.end_state_lock,
                end_frame_prompt=segment.end_frame_prompt,
                timed_beats=segment.timed_beats,
            )
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="start_frame_prompt",
                prompt_text=segment.start_frame_prompt,
                frame_characters=segment.start_frame_characters,
                frame_label="start_frame",
            )
            if segment.requires_mid_frame:
                self._validate_single_frame_focus_conflict(
                    segment_id=segment.segment_id,
                    field_name="mid_frame_prompt",
                    prompt_text=segment.mid_frame_prompt,
                    frame_characters=segment.mid_frame_characters,
                    frame_label="mid_frame",
                )
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="end_frame_prompt",
                prompt_text=segment.end_frame_prompt,
                frame_characters=segment.end_frame_characters,
                frame_label="end_frame",
            )
            fields_to_check = [
                segment.summary,
                segment.narration,
                segment.start_frame_prompt,
                segment.mid_frame_prompt,
                segment.end_frame_prompt,
                *segment.dialogue_lines,
                *segment.subtitle_lines,
                *segment.timed_beats,
            ]
            joined = "\n".join(item for item in fields_to_check if item).strip()
            if not joined:
                raise ValueError(f"segment {segment.segment_id} 缺少有效分镜内容。")
            matched_phrase = next(
                (phrase for phrase in forbidden_meta_phrases if phrase in joined),
                "",
            )
            if matched_phrase:
                raise ValueError(
                    f"segment {segment.segment_id} 包含分析模板话术“{matched_phrase}”，"
                    "说明模型没有输出可直接执行的正式分镜。"
                )
        missing_chapters = [
            number for number, count in sorted(chapter_coverage.items()) if count <= 0
        ]
        if missing_chapters:
            raise ValueError(
                "视频分镜没有覆盖全部章节，缺失章节："
                + "、".join(str(item) for item in missing_chapters)
            )
        return plan

    def _validate_single_frame_focus_conflict(
        self,
        *,
        segment_id: str,
        field_name: str,
        prompt_text: str,
        frame_characters: list[str],
        frame_label: str,
    ) -> None:
        if not self._has_multi_character_single_subject_focus(
            prompt_text,
            frame_characters,
        ):
            return
        frame_names = "、".join(
            str(name).strip()
            for name in frame_characters
            if str(name).strip()
        ) or "未知角色"
        raise ValueError(
            f"segment {segment_id} 的 {field_name} 在 {frame_label} "
            f"({frame_names}) 多人同帧时仍要求单人特写，"
            "这会导致同一角色在单帧里重复出现。"
        )


