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
    CharacterVisualProfile,
    ContinuityLink,
    SceneBible,
    ShotState,
    StoryMemoryPackage,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.planning import VideoPlanningMixin
from storyforge.domains.video.prompting import VideoPromptingMixin
from storyforge.domains.video.repair import VideoRepairMixin
from storyforge.domains.video.segment_validation import VideoSegmentValidationMixin
from storyforge.domains.video.structure_validation import VideoStructureValidationMixin
from storyforge.domains.video.structured_generation import VideoStructuredGenerationMixin
from storyforge.domains.video.structured_retry_prompts import VideoStructuredRetryPromptMixin
from storyforge.domains.video.schemas import (
    ChapterSceneSchema,
    CharacterVisualBibleSchema,
    SceneContinuityRepairSchema,
    SceneSegmentChunkSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    SegmentContinuityRepairSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
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

    def _build_scene_plan_from_chunk_batches(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        chunk_batches: list[SceneSegmentContractBatchSchema],
    ) -> VideoSegmentPlanSchema:
        segment_contracts = self._merge_scene_chunk_contract_batches(
            scene=scene,
            chunk_batches=chunk_batches,
        )
        scene_segments = self._materialize_scene_segments(
            novel_package=novel_package,
            scene=scene,
            contracts=segment_contracts,
        )
        return VideoSegmentPlanSchema.model_validate(
            {
                "scenes": [
                    {
                        **scene.model_dump(),
                        "segments": [item.model_dump() for item in scene_segments],
                    }
                ]
            }
        )

    def _normalize_scene_chunk_contract_batch(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        contracts: SceneSegmentContractBatchSchema,
        previous_tail_segment: SceneSegmentContractSchema | None,
    ) -> SceneSegmentContractBatchSchema:
        normalized_segments: list[SceneSegmentContractSchema] = []
        for index, segment in enumerate(contracts.segments, start=1):
            previous_segment = normalized_segments[-1] if normalized_segments else previous_tail_segment
            previous_segment_id = previous_segment.segment_id if previous_segment else ""
            continuity_link = self._normalize_scene_chunk_continuity_link(
                segment=segment,
                previous_segment=previous_segment,
                previous_segment_id=previous_segment_id,
            )
            normalized_segments.append(
                segment.model_copy(
                    update={
                        "segment_id": f"{scene.scene_id}-ck{chunk.order_index:02d}-seg{index:02d}",
                        "chapter_number": scene.chapter_number,
                        "scene_id": scene.scene_id,
                        "mid_frame_characters": (
                            list(segment.mid_frame_characters)
                            if segment.requires_mid_frame
                            else []
                        ),
                        "continuity_link": continuity_link,
                    }
                )
            )
        return SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "segments": [item.model_dump() for item in normalized_segments],
            }
        )

    def _normalize_scene_chunk_continuity_link(
        self,
        *,
        segment: SceneSegmentContractSchema,
        previous_segment: SceneSegmentContractSchema | None,
        previous_segment_id: str,
    ):
        continuity_link = segment.continuity_link
        if previous_segment is None:
            return continuity_link.model_copy(
                update={
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": continuity_link.opening_match.strip(),
                    "carry_over_elements": list(continuity_link.carry_over_elements),
                    "allowed_changes": continuity_link.allowed_changes.strip(),
                    "transition_reason": continuity_link.transition_reason.strip(),
                }
            )
        transition_mode = continuity_link.transition_mode.strip().lower()
        if transition_mode not in {"continue", "cut"}:
            raise ValueError(
                f"segment {segment.segment_id} 的 continuity_link.transition_mode 非法："
                f"{continuity_link.transition_mode}"
            )
        return continuity_link.model_copy(
            update={
                "previous_segment_id": previous_segment_id,
                "transition_mode": transition_mode,
                "opening_match": continuity_link.opening_match.strip(),
                "carry_over_elements": list(continuity_link.carry_over_elements),
                "allowed_changes": continuity_link.allowed_changes.strip(),
                "transition_reason": continuity_link.transition_reason.strip(),
            }
        )

    def _build_scene_chunk_exit_state(
        self,
        tail_segment: SceneSegmentContractSchema,
    ) -> dict[str, object]:
        visible_tail_state = (
            tail_segment.shot_state.end_state_lock.strip()
            or tail_segment.shot_state.action_progression.strip()
            or tail_segment.summary.strip()
        )
        carry_over_elements = self._build_scene_chunk_carry_over_elements(tail_segment)
        return {
            "segment_id": tail_segment.segment_id,
            "summary": tail_segment.summary,
            "end_frame_characters": list(tail_segment.end_frame_characters),
            "action_progression": tail_segment.shot_state.action_progression.strip(),
            "blocking": tail_segment.shot_state.blocking.strip(),
            "prop_continuity": tail_segment.shot_state.prop_continuity.strip(),
            "end_state_lock": tail_segment.shot_state.end_state_lock,
            "screen_direction": tail_segment.shot_state.screen_direction,
            "transition_mode": tail_segment.continuity_link.transition_mode,
            "visible_tail_state": visible_tail_state,
            "carry_over_elements": carry_over_elements,
            "opening_match_seed": self._build_scene_chunk_opening_match_seed(
                visible_tail_state=visible_tail_state,
                carry_over_elements=carry_over_elements,
            ),
        }

    def _build_scene_chunk_carry_over_elements(
        self,
        tail_segment: SceneSegmentContractSchema,
    ) -> list[str]:
        raw_elements = [
            f"角色：{'、'.join(tail_segment.end_frame_characters)}"
            if tail_segment.end_frame_characters
            else "",
            f"站位：{tail_segment.shot_state.blocking.strip()}"
            if tail_segment.shot_state.blocking.strip()
            else "",
            f"朝向：{tail_segment.shot_state.screen_direction.strip()}"
            if tail_segment.shot_state.screen_direction.strip()
            else "",
            f"道具：{tail_segment.shot_state.prop_continuity.strip()}"
            if tail_segment.shot_state.prop_continuity.strip()
            else "",
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in raw_elements:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _build_scene_chunk_opening_match_seed(
        self,
        *,
        visible_tail_state: str,
        carry_over_elements: list[str],
    ) -> str:
        if not visible_tail_state:
            return ""
        if not carry_over_elements:
            return visible_tail_state
        compact_carry = "，".join(carry_over_elements[:3])
        return f"{visible_tail_state}；保持{compact_carry}"

    def _merge_scene_chunk_contract_batches(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk_batches: list[SceneSegmentContractBatchSchema],
    ) -> SceneSegmentContractBatchSchema:
        merged_segments: list[SceneSegmentContractSchema] = []
        for chunk_batch in chunk_batches:
            merged_segments.extend(chunk_batch.segments)
        if not merged_segments:
            raise ValueError(f"scene {scene.scene_id} 合并 chunk 后没有任何 segment。")

        renumbered_segments: list[SceneSegmentContractSchema] = []
        for index, segment in enumerate(merged_segments, start=1):
            previous_segment = renumbered_segments[-1] if renumbered_segments else None
            continuity_link = self._normalize_scene_chunk_continuity_link(
                segment=segment,
                previous_segment=previous_segment,
                previous_segment_id=previous_segment.segment_id if previous_segment else "",
            )
            renumbered_segments.append(
                segment.model_copy(
                    update={
                        "segment_id": f"{scene.scene_id}-seg{index:02d}",
                        "chapter_number": scene.chapter_number,
                        "scene_id": scene.scene_id,
                        "continuity_link": continuity_link,
                    }
                )
            )
        return SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "segments": [item.model_dump() for item in renumbered_segments],
            }
        )

    def _materialize_chapter_scene(
        self,
        *,
        raw_scene: ChapterSceneSchema,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> ChapterSceneSchema:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        involved_characters = list(raw_scene.involved_characters)
        if not involved_characters:
            involved_characters = list(chapter_outline.featured_characters)
        if not involved_characters:
            involved_characters = [
                item.name for item in novel_package.outline.characters[:2]
            ]
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=chapter_number,
            scene_title=raw_scene.title,
            scene_summary=raw_scene.summary,
            scene_anchor=raw_scene.scene_anchor,
            scene_bible=raw_scene.scene_bible,
            involved_characters=involved_characters,
        )
        scene_anchor = raw_scene.scene_anchor.strip() or "；".join(
            part
            for part in (
                repaired_scene_bible.location,
                repaired_scene_bible.time_window,
                raw_scene.summary,
            )
            if str(part).strip()
        )[:120]
        return raw_scene.model_copy(
            update={
                "chapter_number": chapter_number,
                "scene_anchor": scene_anchor,
                "involved_characters": involved_characters,
                "scene_bible": repaired_scene_bible,
            }
        )

    def _chapter_story_text(
        self,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> str:
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        if draft is not None and draft.markdown.strip():
            return draft.markdown
        chapter = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        return chapter.summary

    def _materialize_scene_segments(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        contracts: SceneSegmentContractBatchSchema,
    ) -> list[VideoSegmentSchema]:
        segments: list[VideoSegmentSchema] = []
        for contract in contracts.segments:
            materialized = self._materialize_scene_segment(
                novel_package=novel_package,
                scene=scene,
                contract=contract,
            )
            segments.append(materialized)
        return segments

    def _materialize_scene_segment(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        contract: SceneSegmentContractSchema,
    ) -> VideoSegmentSchema:
        involved_characters = list(contract.involved_characters)
        timed_beats = list(contract.timed_beats)
        narration, dialogue_lines, subtitle_lines = self._sanitize_segment_audio_tracks(
            narration=contract.narration,
            dialogue_lines=contract.dialogue_lines,
            subtitle_lines=contract.subtitle_lines,
            summary=contract.summary,
            timed_beats=timed_beats,
            involved_characters=involved_characters,
        )
        subtitle_lines = subtitle_lines or self._build_subtitle_lines(
            narration=narration,
            dialogue_lines=dialogue_lines,
            timed_beats=timed_beats,
        )
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=involved_characters,
            duration_seconds=contract.duration_seconds,
            dialogue_lines=dialogue_lines,
            timed_beats=timed_beats,
            requested=contract.requires_mid_frame,
        )
        start_frame_characters = self._require_contract_frame_characters(
            field_name="start_frame_characters",
            frame_characters=contract.start_frame_characters,
            involved_characters=involved_characters,
        )
        end_frame_characters = self._require_contract_frame_characters(
            field_name="end_frame_characters",
            frame_characters=contract.end_frame_characters,
            involved_characters=involved_characters,
        )
        mid_frame_characters = (
            self._require_contract_frame_characters(
                field_name="mid_frame_characters",
                frame_characters=contract.mid_frame_characters,
                involved_characters=involved_characters,
            )
            if requires_mid_frame
            else []
        )
        mid_frame_mode = self._normalize_mid_frame_mode(contract.mid_frame_mode)
        base_segment = VideoSegmentSchema.model_validate(
            {
                "segment_id": contract.segment_id,
                "chapter_number": contract.chapter_number,
                "scene_id": scene.scene_id,
                "scene_title": scene.title,
                "scene_summary": scene.summary,
                "scene_anchor": scene.scene_anchor,
                "scene_bible": scene.scene_bible.model_dump(),
                "shot_state": contract.shot_state.model_dump(),
                "continuity_link": contract.continuity_link.model_dump(),
                "title": contract.title,
                "summary": contract.summary,
                "involved_characters": involved_characters,
                "start_frame_characters": start_frame_characters,
                "mid_frame_characters": mid_frame_characters,
                "mid_frame_mode": mid_frame_mode if requires_mid_frame else "continuous",
                "end_frame_characters": end_frame_characters,
                "narration": narration,
                "dialogue_lines": dialogue_lines,
                "subtitle_lines": subtitle_lines,
                "timed_beats": timed_beats,
                "sound_effects": self._build_local_sound_effects(scene.scene_bible, timed_beats),
                "music_direction": self._build_local_music_direction(
                    novel_package=novel_package,
                    scene=scene,
                    segment_summary=contract.summary,
                ),
                "start_frame_prompt": "",
                "mid_frame_prompt": "",
                "end_frame_prompt": "",
                "duration_seconds": contract.duration_seconds,
                "requires_mid_frame": requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(contract.transition_hint),
            }
        )
        start_frame_prompt = self._build_local_start_frame_prompt(scene, base_segment)
        end_frame_prompt = self._build_local_end_frame_prompt(scene, base_segment)
        enriched_segment = base_segment.model_copy(
            update={
                "start_frame_prompt": start_frame_prompt,
                "end_frame_prompt": end_frame_prompt,
            }
        )
        mid_frame_prompt = (
            self._build_default_mid_frame_prompt(enriched_segment)
            if requires_mid_frame
            else ""
        )
        return enriched_segment.model_copy(
            update={
                "mid_frame_prompt": mid_frame_prompt,
                "character_voice_notes": [],
            }
        )

    def _require_contract_frame_characters(
        self,
        *,
        field_name: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> list[str]:
        if not involved_characters:
            raise ValueError(f"{field_name} 无法校验，因为 involved_characters 为空。")
        normalized = [
            name for name in frame_characters if name and name in involved_characters
        ]
        if not normalized:
            raise ValueError(f"{field_name} 不能为空，且只能使用 involved_characters 内角色。")
        return normalized

    def _build_local_start_frame_prompt(
        self,
        scene: ChapterSceneSchema,
        segment: VideoSegmentSchema,
    ) -> str:
        beat_descriptions = self._extract_beat_descriptions(segment.timed_beats)
        opening_focus = (
            segment.continuity_link.opening_match.strip()
            or (beat_descriptions[0] if beat_descriptions else "")
            or segment.summary
        )
        characters = "、".join(segment.start_frame_characters) or "环境"
        sanitized_focus = self._sanitize_frame_prompt_text(
            opening_focus,
            segment.start_frame_characters,
            segment.involved_characters,
        ) or "只呈现当前帧真实可见的开场状态"
        return f"首帧，{characters} 开场进入 {scene.title}，{sanitized_focus}。"

    def _build_local_end_frame_prompt(
        self,
        scene: ChapterSceneSchema,
        segment: VideoSegmentSchema,
    ) -> str:
        beat_descriptions = self._extract_beat_descriptions(segment.timed_beats)
        closing_focus = (
            segment.shot_state.end_state_lock.strip()
            or (beat_descriptions[-1] if beat_descriptions else "")
            or segment.summary
        )
        characters = "、".join(segment.end_frame_characters) or "环境"
        sanitized_focus = self._sanitize_frame_prompt_text(
            closing_focus,
            segment.end_frame_characters,
            segment.involved_characters,
        ) or "只呈现当前帧真实可见的收束状态"
        return f"尾帧，{characters} 在 {scene.title} 收束到 {sanitized_focus}。"

    def _build_local_sound_effects(
        self,
        scene_bible,
        timed_beats: list[str],
    ) -> list[str]:
        effects: list[str] = []
        weather = self._scene_bible_value(scene_bible, "weather").strip()
        if weather:
            effects.append(f"{weather}环境声")
        fixed_props = self._scene_bible_environment_fixed_props(scene_bible)
        if fixed_props:
            effects.append(f"{fixed_props[0]}相关细节声")
        beat_text = " ".join(timed_beats)
        if any(keyword in beat_text for keyword in ("走", "跑", "靠近", "停下", "转身", "拥抱")):
            effects.append("脚步与衣料摩擦声")
        sanitized_effects = self._sanitize_segment_sound_effects(
            effects,
            scene_bible=scene_bible,
        )
        if not sanitized_effects:
            sanitized_effects = ["环境底噪"]
        return sanitized_effects[:3]

    def _build_local_music_direction(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        segment_summary: str,
    ) -> str:
        return (
            f"延续 {novel_package.brief.tone} 的整体气质，"
            f"围绕 {scene.title} / {segment_summary} 的情绪推进铺陈，不要压过对白和环境音。"
        )

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

    def _build_character_profiles(
        self,
        visual_bible: CharacterVisualBibleSchema,
    ) -> list[CharacterVisualProfile]:
        return [
            CharacterVisualProfile(
                name=item.name,
                role=item.role,
                gender=item.gender,
                appearance=item.appearance,
                outfit=item.outfit,
                color_palette=item.color_palette,
                portrait_prompt=self._build_character_sheet_prompt(
                    name=item.name,
                    gender=item.gender,
                    appearance=item.appearance,
                    outfit=item.outfit,
                ),
            )
            for item in visual_bible.characters
        ]

    def _build_voice_map(self, novel_package: NovelPackage) -> dict[str, object]:
        return {
            item.name: item.voice_profile
            for item in novel_package.outline.characters
        }

    def _build_runtime_scenes(
        self,
        segments_plan: VideoSegmentPlanSchema,
        output_dir: str,
    ) -> list[VideoScene]:
        scenes = [
            VideoScene.from_dict(item.model_dump())
            for item in segments_plan.scenes
        ]
        return self._prepare_scene_master_frames(scenes, output_dir)

    def _build_runtime_segments(
        self,
        segments_plan: VideoSegmentPlanSchema,
        voice_map: dict[str, object],
    ) -> list[VideoSegment]:
        return [
            VideoSegment(
                segment_id=item.segment_id,
                chapter_number=item.chapter_number,
                scene_id=item.scene_id,
                scene_title=item.scene_title,
                scene_summary=item.scene_summary,
                scene_anchor=item.scene_anchor,
                title=item.title,
                summary=item.summary,
                involved_characters=item.involved_characters,
                start_frame_characters=item.start_frame_characters,
                mid_frame_characters=item.mid_frame_characters,
                end_frame_characters=item.end_frame_characters,
                narration=item.narration,
                dialogue_lines=item.dialogue_lines,
                subtitle_lines=item.subtitle_lines
                or self._build_subtitle_lines(
                    narration=item.narration,
                    dialogue_lines=item.dialogue_lines,
                    timed_beats=item.timed_beats,
                ),
                character_voice_notes=self._build_segment_voice_notes(
                    item.involved_characters,
                    voice_map,
                ),
                sound_effects=self._sanitize_segment_sound_effects(
                    item.sound_effects,
                    scene_bible=item.scene_bible,
                    prop_continuity=item.shot_state.prop_continuity,
                ),
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                start_frame_prompt=item.start_frame_prompt,
                mid_frame_prompt=item.mid_frame_prompt,
                end_frame_prompt=item.end_frame_prompt,
                duration_seconds=item.duration_seconds,
                requires_mid_frame=item.requires_mid_frame,
                transition_hint=item.transition_hint,
                source_segment_id=item.source_segment_id or item.segment_id,
                subsegment_index=item.subsegment_index,
                subsegment_count=item.subsegment_count,
                reuse_previous_end_frame=item.reuse_previous_end_frame,
                scene_bible=SceneBible.from_dict(item.scene_bible.model_dump()),
                shot_state=ShotState.from_dict(item.shot_state.model_dump()),
                continuity_link=ContinuityLink.from_dict(item.continuity_link.model_dump()),
            )
            for item in segments_plan.segments
        ]

    def repair_segment_continuity(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        segment_id: str,
        continuity_issues: list[dict[str, object]],
    ) -> tuple[VideoSegmentSchema, dict[str, object]]:
        target_index = next(
            (index for index, item in enumerate(project_package.segments) if item.segment_id == segment_id),
            -1,
        )
        if target_index < 0:
            raise ValueError(f"Segment {segment_id} not found in current project package.")

        target_segment = project_package.segments[target_index]
        previous_segment = project_package.segments[target_index - 1] if target_index > 0 else None
        next_segment = (
            project_package.segments[target_index + 1]
            if target_index + 1 < len(project_package.segments)
            else None
        )
        target_scene = next(
            (scene for scene in project_package.scenes if scene.scene_id == target_segment.scene_id),
            None,
        )
        if target_scene is None:
            raise ValueError(f"Scene {target_segment.scene_id} not found for segment {segment_id}.")

        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的 Segment Continuity Repair Agent。"
                "你只修复目标 segment 的连续性规划，不重写剧情，不改章节结构，不新增角色。"
                "你的职责是把当前 segment 修成更适合单段重生成的稳定执行合同。"
            ),
            user_prompt=self._build_segment_continuity_repair_user_prompt(
                story_title=project_package.title,
                character_profiles=project_package.character_profiles,
                scene_payload=to_jsonable(target_scene),
                segment_payload=to_jsonable(target_segment),
                previous_segment_payload=to_jsonable(previous_segment) if previous_segment else None,
                next_segment_payload=to_jsonable(next_segment) if next_segment else None,
                continuity_issues=continuity_issues,
                speech_budget_context={
                    "current_duration_seconds": target_segment.duration_seconds,
                    "required_duration_seconds": self._estimate_required_speech_duration(
                        narration=target_segment.narration,
                        dialogue_lines=target_segment.dialogue_lines,
                        subtitle_lines=target_segment.subtitle_lines,
                    ),
                    "max_duration_seconds": self.SEEDANCE_MAX_DURATION_SECONDS,
                    "speech_chars_per_second": self.SPEECH_CHARS_PER_SECOND,
                },
            ),
            metadata={"task": "segment-continuity-repair", "segment_id": segment_id},
        )
        repair_patch = self._run_strict_structured_agent(
            schema=SegmentContinuityRepairSchema,
            request=request,
            validator=lambda candidate: self._validate_segment_continuity_repair(
                candidate,
                target_segment=target_segment,
                previous_segment=previous_segment,
            ),
        )
        repaired_segment = self._materialize_repaired_segment(
            novel_package=novel_package,
            project_package=project_package,
            target_segment=target_segment,
            target_scene=target_scene,
            previous_segment=previous_segment,
            repair_patch=repair_patch,
        )
        repair_report = {
            "segment_id": segment_id,
            "repair_summary": repair_patch.repair_summary.strip(),
            "continuity_issues": continuity_issues,
            "raw_patch": repair_patch.model_dump(),
            "changed_fields": self._collect_segment_changed_fields(target_segment, repaired_segment),
            "before": to_jsonable(target_segment),
            "after": repaired_segment.model_dump(),
        }
        return repaired_segment, repair_report

    def repair_scene_continuity(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        scene_id: str,
        scene_issues: list[dict[str, object]],
        related_segment_issues: list[dict[str, object]],
        target_segment_ids: list[str],
        selection_mode: str,
    ) -> tuple[VideoScene, dict[str, object]]:
        target_scene = next(
            (scene for scene in project_package.scenes if scene.scene_id == scene_id),
            None,
        )
        if target_scene is None:
            raise ValueError(f"Scene {scene_id} not found in current project package.")

        target_segment_set = {item for item in target_segment_ids if item}
        target_segments = [
            segment for segment in target_scene.segments
            if not target_segment_set or segment.segment_id in target_segment_set
        ]
        if not target_segments:
            raise ValueError(f"Scene {scene_id} has no target segments for continuity repair.")

        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的 Scene Continuity Repair Agent。"
                "你只修复目标 scene 的场景连续性基线，不重写剧情，不改章节结构，不新增角色。"
                "你的职责是把当前 scene 修成更适合后续场景母图、关键帧和视频复用的稳定环境合同。"
            ),
            user_prompt=self._build_scene_continuity_repair_user_prompt(
                story_title=project_package.title,
                character_profiles=project_package.character_profiles,
                scene_payload=to_jsonable(target_scene),
                target_segment_payloads=[to_jsonable(item) for item in target_segments],
                scene_issues=scene_issues,
                related_segment_issues=related_segment_issues,
                selection_mode=selection_mode,
            ),
            metadata={"task": "scene-continuity-repair", "scene_id": scene_id},
        )
        repair_patch = self._run_strict_structured_agent(
            schema=SceneContinuityRepairSchema,
            request=request,
            validator=lambda candidate: self._validate_scene_continuity_repair(
                candidate,
                target_scene=target_scene,
            ),
        )
        repaired_scene = self._materialize_repaired_scene(
            novel_package=novel_package,
            target_scene=target_scene,
            repair_patch=repair_patch,
        )
        repair_report = {
            "scene_id": scene_id,
            "repair_summary": repair_patch.repair_summary.strip(),
            "selection_mode": selection_mode,
            "affected_segment_ids": list(target_segment_ids),
            "continuity_issues": scene_issues,
            "related_segment_issues": related_segment_issues,
            "raw_patch": repair_patch.model_dump(),
            "changed_fields": self._collect_scene_changed_fields(target_scene, repaired_scene),
            "before": to_jsonable(target_scene),
            "after": to_jsonable(repaired_scene),
        }
        return repaired_scene, repair_report

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

    def _validate_segment_continuity_repair(
        self,
        candidate: SegmentContinuityRepairSchema,
        *,
        target_segment: VideoSegment,
        previous_segment: VideoSegment | None,
    ) -> SegmentContinuityRepairSchema:
        if candidate.segment_id.strip() != target_segment.segment_id:
            raise ValueError(
                f"segment_id 必须保持为 {target_segment.segment_id}，实际为 {candidate.segment_id!r}。"
            )

        involved_characters = {
            str(name).strip()
            for name in target_segment.involved_characters
            if str(name).strip()
        }
        if not involved_characters:
            raise ValueError("目标 segment 缺少 involved_characters，无法执行修复。")

        for field_name, characters in (
            ("start_frame_characters", candidate.start_frame_characters),
            ("mid_frame_characters", candidate.mid_frame_characters if candidate.requires_mid_frame else []),
            ("end_frame_characters", candidate.end_frame_characters),
        ):
            invalid_names = [
                name for name in characters
                if str(name).strip() and str(name).strip() not in involved_characters
            ]
            if invalid_names:
                raise ValueError(
                    f"{field_name} 只能使用目标片段已有角色，非法角色：{'、'.join(invalid_names)}。"
                )

        if not candidate.start_frame_characters:
            raise ValueError("start_frame_characters 不能为空。")
        if not candidate.end_frame_characters:
            raise ValueError("end_frame_characters 不能为空。")
        if candidate.requires_mid_frame:
            self._validate_mid_frame_anchor_group_continuity(
                segment_id=candidate.segment_id,
                start_frame_characters=candidate.start_frame_characters,
                mid_frame_characters=candidate.mid_frame_characters,
                mid_frame_mode=candidate.mid_frame_mode,
                end_frame_characters=candidate.end_frame_characters,
            )
        self._validate_segment_direction_consistency(
            segment_id=candidate.segment_id,
            screen_direction=candidate.shot_state.screen_direction,
            end_state_lock=candidate.shot_state.end_state_lock,
            end_frame_prompt=candidate.end_frame_prompt,
            timed_beats=candidate.timed_beats,
        )
        self._validate_single_frame_focus_conflict(
            segment_id=candidate.segment_id,
            field_name="start_frame_prompt",
            prompt_text=candidate.start_frame_prompt,
            frame_characters=candidate.start_frame_characters,
            frame_label="start_frame",
        )
        self._validate_single_frame_focus_conflict(
            segment_id=candidate.segment_id,
            field_name="end_frame_prompt",
            prompt_text=candidate.end_frame_prompt,
            frame_characters=candidate.end_frame_characters,
            frame_label="end_frame",
        )
        if candidate.requires_mid_frame:
            if not candidate.mid_frame_prompt.strip():
                raise ValueError("requires_mid_frame=true 时 mid_frame_prompt 不能为空。")
            if not candidate.mid_frame_characters:
                raise ValueError("requires_mid_frame=true 时 mid_frame_characters 不能为空。")
            self._validate_single_frame_focus_conflict(
                segment_id=candidate.segment_id,
                field_name="mid_frame_prompt",
                prompt_text=candidate.mid_frame_prompt,
                frame_characters=candidate.mid_frame_characters,
                frame_label="mid_frame",
            )

        duration_seconds = self._normalize_seedance_duration(candidate.duration_seconds)
        if duration_seconds != candidate.duration_seconds:
            raise ValueError(
                f"duration_seconds 必须在 {self.SEEDANCE_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒之间。"
            )

        subtitle_lines = candidate.subtitle_lines or self._build_subtitle_lines(
            narration=candidate.narration,
            dialogue_lines=candidate.dialogue_lines,
            timed_beats=candidate.timed_beats,
        )
        required_duration = self._estimate_required_speech_duration(
            narration=candidate.narration,
            dialogue_lines=candidate.dialogue_lines,
            subtitle_lines=subtitle_lines,
        )
        duration_seconds = self._fit_duration_to_speech_budget(
            segment_id=candidate.segment_id,
            current_duration_seconds=duration_seconds,
            required_duration_seconds=required_duration,
            allow_split_retry=False,
        )
        if duration_seconds != candidate.duration_seconds:
            candidate = candidate.model_copy(update={"duration_seconds": duration_seconds})

        self._validate_timed_beats_timeline(
            segment_id=candidate.segment_id,
            timed_beats=candidate.timed_beats,
            duration_seconds=duration_seconds,
            require_full_coverage=True,
        )
        self._validate_keyframe_semantic_distance(
            segment_id=candidate.segment_id,
            summary=getattr(candidate, "summary", "") or target_segment.summary,
            timed_beats=candidate.timed_beats,
            start_frame_characters=candidate.start_frame_characters,
            mid_frame_characters=candidate.mid_frame_characters,
            end_frame_characters=candidate.end_frame_characters,
            requires_mid_frame=candidate.requires_mid_frame,
            mid_frame_mode=candidate.mid_frame_mode,
            continuity_link=candidate.continuity_link,
            shot_state=candidate.shot_state,
        )

        transition_mode = candidate.continuity_link.transition_mode.strip().lower()
        if previous_segment is None and transition_mode == "continue":
            raise ValueError("首段或无上一段时，continuity_link.transition_mode 不能为 continue。")
        if (
            previous_segment is not None
            and transition_mode == "continue"
            and candidate.continuity_link.previous_segment_id.strip()
            and candidate.continuity_link.previous_segment_id.strip() != previous_segment.segment_id
        ):
            raise ValueError(
                f"continue 模式下 previous_segment_id 必须是 {previous_segment.segment_id}。"
            )
        return candidate

    def _validate_scene_continuity_repair(
        self,
        candidate: SceneContinuityRepairSchema,
        *,
        target_scene: VideoScene,
    ) -> SceneContinuityRepairSchema:
        if candidate.scene_id.strip() != target_scene.scene_id:
            raise ValueError(
                f"scene_id 必须保持为 {target_scene.scene_id}，实际为 {candidate.scene_id!r}。"
            )
        if not candidate.scene_anchor.strip():
            raise ValueError("scene_anchor 不能为空。")
        scene_bible = candidate.scene_bible
        required_text_fields = {
            "location": scene_bible.location,
            "time_window": scene_bible.time_window,
            "weather": scene_bible.weather,
            "lighting": scene_bible.lighting,
            "spatial_layout": scene_bible.spatial_layout,
            "continuity_notes": scene_bible.continuity_notes,
        }
        missing_fields = [key for key, value in required_text_fields.items() if not str(value or "").strip()]
        if missing_fields:
            raise ValueError("scene_bible 缺少必要字段：" + "、".join(missing_fields))
        if len([item for item in scene_bible.background_anchors if str(item or "").strip()]) < 2:
            raise ValueError("scene_bible.background_anchors 至少需要 2 个。")
        if len([item for item in scene_bible.fixed_props if str(item or "").strip()]) < 1:
            raise ValueError("scene_bible.fixed_props 至少需要 1 个。")
        if len([item for item in scene_bible.dominant_palette if str(item or "").strip()]) < 1:
            raise ValueError("scene_bible.dominant_palette 至少需要 1 个。")
        return candidate

    def _materialize_repaired_segment(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        target_segment: VideoSegment,
        target_scene: VideoScene,
        previous_segment: VideoSegment | None,
        repair_patch: SegmentContinuityRepairSchema,
    ) -> VideoSegmentSchema:
        target_schema = VideoSegmentSchema.model_validate(to_jsonable(target_segment))
        character_visual_bible = CharacterVisualBibleSchema(
            characters=[
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                    "appearance": item.appearance,
                    "outfit": item.outfit,
                    "color_palette": list(item.color_palette),
                    "portrait_prompt": item.portrait_prompt,
                }
                for item in project_package.character_profiles
            ]
        )
        candidate = target_schema.model_copy(
            update={
                "start_frame_prompt": repair_patch.start_frame_prompt.strip(),
                "mid_frame_prompt": repair_patch.mid_frame_prompt.strip(),
                "end_frame_prompt": repair_patch.end_frame_prompt.strip(),
                "start_frame_characters": list(repair_patch.start_frame_characters),
                "mid_frame_characters": list(repair_patch.mid_frame_characters),
                "mid_frame_mode": self._normalize_mid_frame_mode(repair_patch.mid_frame_mode),
                "end_frame_characters": list(repair_patch.end_frame_characters),
                "narration": repair_patch.narration.strip(),
                "dialogue_lines": list(repair_patch.dialogue_lines),
                "subtitle_lines": list(repair_patch.subtitle_lines),
                "timed_beats": list(repair_patch.timed_beats),
                "duration_seconds": repair_patch.duration_seconds,
                "requires_mid_frame": repair_patch.requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(repair_patch.transition_hint),
                "shot_state": repair_patch.shot_state,
                "continuity_link": repair_patch.continuity_link,
            }
        )
        single_plan = self._normalize_segment_characters(
            VideoSegmentPlanSchema.model_validate({"segments": [candidate.model_dump()]}),
            novel_package,
            character_visual_bible,
        )
        normalized_segment = single_plan.segments[0]
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=normalized_segment.involved_characters,
            duration_seconds=normalized_segment.duration_seconds,
            dialogue_lines=normalized_segment.dialogue_lines,
            timed_beats=normalized_segment.timed_beats,
            requested=normalized_segment.requires_mid_frame,
        )
        normalized_segment = normalized_segment.model_copy(
            update={
                "requires_mid_frame": requires_mid_frame,
                "mid_frame_prompt": (
                    normalized_segment.mid_frame_prompt
                    if requires_mid_frame
                    else ""
                ),
                "mid_frame_characters": (
                    normalized_segment.mid_frame_characters
                    if requires_mid_frame
                    else []
                ),
                "mid_frame_mode": (
                    self._normalize_mid_frame_mode(normalized_segment.mid_frame_mode)
                    if requires_mid_frame
                    else "continuous"
                ),
                "subtitle_lines": (
                    normalized_segment.subtitle_lines
                    or self._build_subtitle_lines(
                        narration=normalized_segment.narration,
                        dialogue_lines=normalized_segment.dialogue_lines,
                        timed_beats=normalized_segment.timed_beats,
                    )
                ),
                "source_segment_id": normalized_segment.source_segment_id or normalized_segment.segment_id,
            }
        )
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=normalized_segment.chapter_number,
            scene_title=target_scene.title,
            scene_summary=target_scene.summary,
            scene_anchor=target_scene.scene_anchor,
            scene_bible=normalized_segment.scene_bible,
            involved_characters=normalized_segment.involved_characters,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"scene_bible": repaired_scene_bible}
        )
        repaired_shot_state = self._repair_shot_state(
            novel_package=novel_package,
            segment=normalized_segment,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"shot_state": repaired_shot_state}
        )
        previous_schema = (
            VideoSegmentSchema.model_validate(to_jsonable(previous_segment))
            if previous_segment is not None
            else None
        )
        repaired_continuity_link = self._repair_continuity_link(
            segment=normalized_segment,
            previous_segment=previous_schema,
        )
        return normalized_segment.model_copy(
            update={
                "continuity_link": repaired_continuity_link,
                "transition_hint": self._normalize_transition_hint(normalized_segment.transition_hint),
                "reuse_previous_end_frame": bool(
                    previous_schema is not None
                    and repaired_continuity_link.transition_mode == "continue"
                    and repaired_continuity_link.previous_segment_id == previous_schema.segment_id
                ),
            }
        )

    def _collect_segment_changed_fields(
        self,
        original_segment: VideoSegment,
        repaired_segment: VideoSegmentSchema,
    ) -> list[str]:
        original_payload = to_jsonable(original_segment)
        repaired_payload = repaired_segment.model_dump()
        tracked_fields = [
            "start_frame_prompt",
            "mid_frame_prompt",
            "end_frame_prompt",
            "start_frame_characters",
            "mid_frame_characters",
            "mid_frame_mode",
            "end_frame_characters",
            "narration",
            "dialogue_lines",
            "subtitle_lines",
            "timed_beats",
            "duration_seconds",
            "requires_mid_frame",
            "transition_hint",
            "shot_state",
            "continuity_link",
        ]
        changed_fields: list[str] = []
        for field_name in tracked_fields:
            if original_payload.get(field_name) != repaired_payload.get(field_name):
                changed_fields.append(field_name)
        return changed_fields

    def _materialize_repaired_scene(
        self,
        *,
        novel_package: NovelPackage,
        target_scene: VideoScene,
        repair_patch: SceneContinuityRepairSchema,
    ) -> VideoScene:
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=target_scene.chapter_number,
            scene_title=target_scene.title,
            scene_summary=target_scene.summary,
            scene_anchor=repair_patch.scene_anchor.strip() or target_scene.scene_anchor,
            scene_bible=repair_patch.scene_bible,
            involved_characters=target_scene.involved_characters,
        )
        candidate_scene = VideoScene.from_dict(
            {
                **to_jsonable(target_scene),
                "scene_anchor": repair_patch.scene_anchor.strip() or target_scene.scene_anchor,
                "scene_bible": repaired_scene_bible.model_dump(),
                "scene_master_frame_url": "",
                "scene_master_frame_status": "planned",
                "scene_master_frame_error": "",
            }
        )
        return self._prepare_scene_master_frame(candidate_scene, "")

    def _collect_scene_changed_fields(
        self,
        original_scene: VideoScene,
        repaired_scene: VideoScene,
    ) -> list[str]:
        original_payload = to_jsonable(original_scene)
        repaired_payload = to_jsonable(repaired_scene)
        tracked_fields = [
            "scene_anchor",
            "scene_bible",
            "scene_master_frame_prompt",
            "scene_master_frame_status",
        ]
        return [
            field_name
            for field_name in tracked_fields
            if original_payload.get(field_name) != repaired_payload.get(field_name)
        ]
