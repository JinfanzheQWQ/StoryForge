from __future__ import annotations

from math import ceil
import re
from typing import Callable, TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackend,
    AgentBackendUnavailableError,
    PromptRequest,
    UnavailableAgentBackend,
    attach_prompt_metrics,
)
from storyforge.core.io import to_jsonable
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.chapter_orchestration import VideoChapterOrchestrationMixin
from storyforge.domains.video.chunk_orchestration import VideoSceneChunkOrchestrationMixin
from storyforge.domains.video.errors import (
    SegmentActionSplitRequiredError,
    SegmentSpeechSplitRequiredError,
    VideoStructuredGenerationError,
)
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
from storyforge.domains.video.structure_validation import VideoStructureValidationMixin
from storyforge.domains.video.schemas import (
    ChapterCoverageEventSchema,
    ChapterCoverageEventSplitPlanSchema,
    ChapterCoveragePlanSchema,
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
from storyforge.domains.video.text_rules import (
    ACTION_STEP_SPLIT_PATTERN,
    DIRECTION_APPROACH_PATTERNS,
    DIRECTION_RETREAT_PATTERNS,
    GENERIC_OPENING_MATCH_PHRASES,
    TIMED_BEAT_PREFIX_PATTERN,
    estimate_progression_node_count_from_texts as _estimate_progression_node_count_from_texts,
    extract_progression_signal_terms as _extract_progression_signal_terms,
    normalize_similarity_text as _normalize_similarity_text,
    progress_text_too_generic as _progress_text_too_generic,
    text_explicitly_stalled as _text_explicitly_stalled,
    text_new_signal_count as _text_new_signal_count,
    text_overlap_ratio as _text_overlap_ratio,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
TIMED_BEAT_PATTERN = re.compile(r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")
class NovelToVideoService(
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

    def _chapter_event_end_coverage_min_ratio(
        self,
        chapter_text_length: int,
    ) -> float:
        if chapter_text_length >= 800:
            return self.CHAPTER_EVENT_END_COVERAGE_MIN_RATIO
        if chapter_text_length >= self.CHAPTER_EVENT_END_COVERAGE_MEDIUM_MIN_CHARS:
            return self.CHAPTER_EVENT_END_COVERAGE_MEDIUM_RATIO
        if chapter_text_length >= self.CHAPTER_EVENT_END_COVERAGE_SHORT_MIN_CHARS:
            return self.CHAPTER_EVENT_END_COVERAGE_SHORT_RATIO
        return 0.0

    def _normalize_event_evidence_text(self, text: str) -> str:
        return "".join(str(text or "").split())

    def _event_evidence_position(
        self,
        evidence: str,
        normalized_chapter_text: str,
    ) -> int:
        normalized_evidence = self._normalize_event_evidence_text(evidence)
        if len(normalized_evidence) < 2:
            return -1
        return normalized_chapter_text.find(normalized_evidence)

    def _supported_event_positions(
        self,
        evidence_tokens: list[str],
        normalized_chapter_text: str,
    ) -> list[int]:
        supported_positions: list[int] = []
        for token in evidence_tokens:
            position = self._event_evidence_position(token, normalized_chapter_text)
            if position >= 0:
                supported_positions.append(position)
        return supported_positions

    def _validate_chapter_event_coverage_output(
        self,
        chapter_event_plan: ChapterCoveragePlanSchema,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        action_capacity_event_ids: set[str] | None = None,
    ) -> ChapterCoveragePlanSchema:
        if chapter_event_plan.chapter_number not in (0, chapter_number):
            raise ValueError(
                f"ChapterCoveragePlanSchema.chapter_number 必须为 {chapter_number}。"
            )
        if not chapter_event_plan.events:
            raise ValueError("ChapterCoveragePlanSchema.events 不能为空。")

        allowed_names = {
            item.name.strip()
            for item in novel_package.outline.characters
            if item.name.strip()
        }
        normalized_chapter_text = self._normalize_event_evidence_text(
            self._chapter_story_text(
                novel_package=novel_package,
                chapter_number=chapter_number,
            )
        )
        if not normalized_chapter_text:
            raise ValueError("当前章节正文为空，无法验证关键事件覆盖。")

        expected_prefix = f"ch{chapter_number:02d}-ev"
        seen_event_ids: set[str] = set()
        previous_position = -1
        last_position = -1
        for index, event in enumerate(chapter_event_plan.events, start=1):
            expected_event_id = f"{expected_prefix}{index:02d}"
            if event.event_id.strip() != expected_event_id:
                raise ValueError(
                    f"关键事件顺序必须使用连续 event_id。期望 {expected_event_id}，实际为 {event.event_id!r}。"
                )
            if event.event_id in seen_event_ids:
                raise ValueError(f"关键事件 event_id 重复：{event.event_id}")
            seen_event_ids.add(event.event_id)
            if not event.summary.strip():
                raise ValueError(f"关键事件 {event.event_id} 缺少 summary。")
            evidence_tokens = [
                item.strip()
                for item in event.source_evidence
                if item.strip()
            ]
            if not evidence_tokens:
                raise ValueError(f"关键事件 {event.event_id} 缺少 source_evidence。")
            supported_positions = self._supported_event_positions(
                evidence_tokens,
                normalized_chapter_text,
            )
            if not supported_positions:
                raise ValueError(
                    f"关键事件 {event.event_id} 的 source_evidence 无法在当前章节正文中定位。"
                )
            event_position = min(supported_positions)
            if event_position < previous_position:
                raise ValueError(
                    f"关键事件 {event.event_id} 的正文位置早于上一事件，顺序与正文不一致。"
                )
            previous_position = event_position
            last_position = max(last_position, max(supported_positions))
            invalid_names = [
                name
                for name in event.involved_characters
                if name.strip() and name.strip() not in allowed_names
            ]
            if invalid_names:
                raise ValueError(
                    f"关键事件 {event.event_id} 使用了不存在的角色名："
                    + "、".join(invalid_names)
                )
            if action_capacity_event_ids is None or event.event_id in action_capacity_event_ids:
                self._validate_chapter_event_action_capacity(
                    event,
                    event_index=index,
                    total_events=len(chapter_event_plan.events),
                )

        minimum_end_ratio = self._chapter_event_end_coverage_min_ratio(
            len(normalized_chapter_text)
        )
        if (
            minimum_end_ratio > 0
            and last_position < int(len(normalized_chapter_text) * minimum_end_ratio)
        ):
            raise ValueError(
                "章节关键事件没有覆盖到章节尾部的真实收束；最后一个 must-cover event 结束得过早。"
            )

        return chapter_event_plan.model_copy(update={"chapter_number": chapter_number})

    def _validate_chapter_event_split_plan(
        self,
        split_plan: ChapterCoverageEventSplitPlanSchema,
        *,
        chapter_event_plan: ChapterCoveragePlanSchema,
        novel_package: NovelPackage,
        chapter_number: int,
        offending_event_index: int,
    ) -> ChapterCoverageEventSplitPlanSchema:
        if len(split_plan.events) < 2:
            raise ValueError("定向拆分粗事件时，replacement events 至少需要 2 条。")
        if len(split_plan.events) > 4:
            raise ValueError("定向拆分粗事件时，replacement events 最多允许 4 条。")
        allowed_names = {
            item.name.strip()
            for item in novel_package.outline.characters
            if item.name.strip()
        }
        for index, event in enumerate(split_plan.events, start=1):
            if not event.summary.strip():
                raise ValueError(f"replacement event #{index} 缺少 summary。")
            if not [item.strip() for item in event.source_evidence if item.strip()]:
                raise ValueError(f"replacement event #{index} 缺少 source_evidence。")
            invalid_names = [
                name
                for name in event.involved_characters
                if name.strip() and name.strip() not in allowed_names
            ]
            if invalid_names:
                raise ValueError(
                    "replacement event 使用了不存在的角色名：" + "、".join(invalid_names)
                )
        merged_plan = self._merge_chapter_event_split_plan(
            chapter_event_plan=chapter_event_plan,
            split_plan=split_plan,
            chapter_number=chapter_number,
            offending_event_index=offending_event_index,
        )
        replacement_event_ids = {
            item.event_id
            for item in merged_plan.events[
                offending_event_index:offending_event_index + len(split_plan.events)
            ]
        }
        self._validate_chapter_event_coverage_output(
            merged_plan,
            novel_package=novel_package,
            chapter_number=chapter_number,
            action_capacity_event_ids=replacement_event_ids,
        )
        return split_plan

    def _merge_chapter_event_split_plan(
        self,
        *,
        chapter_event_plan: ChapterCoveragePlanSchema,
        split_plan: ChapterCoverageEventSplitPlanSchema,
        chapter_number: int,
        offending_event_index: int,
    ) -> ChapterCoveragePlanSchema:
        merged_events: list[ChapterCoverageEventSchema] = []
        prefix = f"ch{chapter_number:02d}-ev"
        for index, event in enumerate(chapter_event_plan.events):
            if index != offending_event_index:
                merged_events.append(
                    ChapterCoverageEventSchema(
                        event_id="",
                        summary=event.summary,
                        source_evidence=list(event.source_evidence),
                        involved_characters=list(event.involved_characters),
                    )
                )
                continue
            for replacement in split_plan.events:
                merged_events.append(
                    ChapterCoverageEventSchema(
                        event_id="",
                        summary=replacement.summary,
                        source_evidence=list(replacement.source_evidence),
                        involved_characters=list(replacement.involved_characters),
                    )
                )
        for index, event in enumerate(merged_events, start=1):
            event.event_id = f"{prefix}{index:02d}"
        return ChapterCoveragePlanSchema(
            chapter_number=chapter_number,
            events=merged_events,
        )

    def _validate_chapter_event_action_capacity(
        self,
        event: ChapterCoverageEventSchema,
        *,
        event_index: int,
        total_events: int,
    ) -> None:
        event_node_count = self._estimate_chapter_event_node_count(event)
        max_progress_nodes = self._chapter_event_progress_node_budget(
            event_index=event_index,
            total_events=total_events,
        )
        if event_node_count <= max_progress_nodes:
            return
        raise ValueError(
            f"关键事件 {event.event_id} 过于粗："
            f"当前至少包含 {event_node_count} 个推进点。"
            "请拆成更细的相邻 event，不要把多轮动作、对白和关系结果合并成同一个关键事件。"
        )

    def _chapter_event_progress_node_budget(
        self,
        *,
        event_index: int,
        total_events: int,
    ) -> int:
        if total_events <= 1:
            return self.CHAPTER_EVENT_MAX_PROGRESS_NODES
        if event_index in {1, total_events}:
            return self.CHAPTER_EVENT_EDGE_MAX_PROGRESS_NODES
        return self.CHAPTER_EVENT_MAX_PROGRESS_NODES

    def _estimate_chapter_event_node_count(
        self,
        event: ChapterCoverageEventSchema,
    ) -> int:
        summary_text = str(event.summary or "").strip()
        if summary_text:
            summary_count = _estimate_progression_node_count_from_texts([summary_text])
            if summary_count >= 2:
                return summary_count

        evidence_texts = [
            str(item or "").strip()
            for item in list(event.source_evidence or [])
            if str(item or "").strip()
        ]
        if not summary_text:
            return _estimate_progression_node_count_from_texts(evidence_texts)

        summary_signals = _extract_progression_signal_terms(summary_text)
        evidence_signals = _extract_progression_signal_terms(" ".join(evidence_texts))
        extra_evidence_signals = evidence_signals - summary_signals
        if len(extra_evidence_signals) >= 2:
            return _estimate_progression_node_count_from_texts(evidence_texts)

        return _estimate_progression_node_count_from_texts([summary_text])

    def _fit_duration_to_speech_budget(
        self,
        *,
        segment_id: str,
        current_duration_seconds: int,
        required_duration_seconds: int,
        allow_split_retry: bool,
    ) -> int:
        if required_duration_seconds <= current_duration_seconds:
            return current_duration_seconds
        if required_duration_seconds > self.SEEDANCE_MAX_DURATION_SECONDS:
            if allow_split_retry:
                raise SegmentSpeechSplitRequiredError(
                    segment_id=segment_id,
                    required_duration_seconds=required_duration_seconds,
                    current_duration_seconds=current_duration_seconds,
                    max_duration_seconds=self.SEEDANCE_MAX_DURATION_SECONDS,
                    required_segment_count=min(
                        self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                        max(
                            2,
                            ceil(required_duration_seconds / self.SEEDANCE_MAX_DURATION_SECONDS),
                        ),
                    ),
                )
            raise ValueError(
                f"当前对白/字幕至少需要 {required_duration_seconds} 秒，"
                f"但输出时长只有 {current_duration_seconds} 秒。"
            )
        return required_duration_seconds

    def _validate_timed_beats_timeline(
        self,
        *,
        segment_id: str,
        timed_beats: list[str],
        duration_seconds: int,
        require_full_coverage: bool,
    ) -> None:
        if not timed_beats:
            raise ValueError(f"segment {segment_id} 缺少 timed_beats。")

        max_end_seconds = 0.0
        parsed_any = False
        for beat in timed_beats:
            match = TIMED_BEAT_PATTERN.search(str(beat))
            if match is None:
                continue
            parsed_any = True
            start_seconds = float(match.group("start"))
            end_seconds = float(match.group("end"))
            if start_seconds >= end_seconds:
                raise ValueError(f"timed_beats 存在无效时间范围：{beat}")
            max_end_seconds = max(max_end_seconds, end_seconds)

        if parsed_any and max_end_seconds > duration_seconds + 0.2:
            raise ValueError(
                f"segment {segment_id} 的 timed_beats 最后结束时间 {max_end_seconds:g}s "
                f"超过当前片段时长 {duration_seconds}s。"
            )
        if (
            require_full_coverage
            and parsed_any
            and max_end_seconds < duration_seconds - self.TIMED_BEAT_COVERAGE_TOLERANCE_SECONDS
        ):
            uncovered_seconds = round(duration_seconds - max_end_seconds, 2)
            raise ValueError(
                f"segment {segment_id} 的 timed_beats 最后结束时间 {max_end_seconds:g}s "
                f"早于当前片段时长 {duration_seconds}s，"
                f"尾部约 {uncovered_seconds:g}s 缺少明确动作或收束节拍。"
            )

    def _validate_segment_action_capacity(
        self,
        *,
        segment_id: str,
        timed_beats: list[str],
        duration_seconds: int,
        allow_split_retry: bool,
    ) -> None:
        action_node_count = self._estimate_segment_action_node_count(timed_beats)
        max_action_nodes = self._segment_action_node_budget(duration_seconds)
        if action_node_count <= max_action_nodes:
            return
        required_segment_count = min(
            self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
            max(2, ceil(action_node_count / max_action_nodes)),
        )
        if allow_split_retry:
            raise SegmentActionSplitRequiredError(
                segment_id=segment_id,
                action_node_count=action_node_count,
                current_duration_seconds=duration_seconds,
                max_action_nodes=max_action_nodes,
                required_segment_count=required_segment_count,
            )
        raise ValueError(
            f"segment {segment_id} 的动作容量过载："
            f"当前约有 {action_node_count} 个推进点，"
            f"但 {duration_seconds} 秒片段最多只允许 {max_action_nodes} 个。"
        )

    def _estimate_segment_action_node_count(
        self,
        timed_beats: list[str],
    ) -> int:
        total_nodes = 0
        for beat in timed_beats:
            description = TIMED_BEAT_PREFIX_PATTERN.sub("", str(beat or "").strip())
            if not description:
                continue
            clause_count = 0
            for raw_clause in ACTION_STEP_SPLIT_PATTERN.split(description):
                clause = str(raw_clause or "").strip(" ，。；;")
                if not clause:
                    continue
                normalized = _normalize_similarity_text(clause)
                if len(normalized) < 4:
                    continue
                if _progress_text_too_generic(clause) and not _extract_progression_signal_terms(clause):
                    continue
                clause_count += 1
            total_nodes += max(1, clause_count)
        return max(1, total_nodes)

    def _segment_action_node_budget(
        self,
        duration_seconds: int,
    ) -> int:
        if duration_seconds <= 7:
            return self.SEGMENT_ACTION_NODE_BUDGET_SHORT
        return self.SEGMENT_ACTION_NODE_BUDGET_LONG

    def _validate_keyframe_semantic_distance(
        self,
        *,
        segment_id: str,
        summary: str,
        timed_beats: list[str],
        start_frame_characters: list[str],
        mid_frame_characters: list[str],
        end_frame_characters: list[str],
        requires_mid_frame: bool,
        mid_frame_mode: str,
        continuity_link,
        shot_state,
    ) -> None:
        anchor_specs = [
            (
                "start_frame",
                self._normalize_anchor_characters(start_frame_characters),
                self._build_start_anchor_state_text(
                    summary=summary,
                    timed_beats=timed_beats,
                    continuity_link=continuity_link,
                    shot_state=shot_state,
                ),
            ),
        ]
        if requires_mid_frame:
            if self._normalize_mid_frame_mode(mid_frame_mode) == "insert_cut":
                return
            anchor_specs.append(
                (
                    "mid_frame",
                    self._normalize_anchor_characters(mid_frame_characters),
                    self._build_mid_anchor_state_text(
                        summary=summary,
                        timed_beats=timed_beats,
                        shot_state=shot_state,
                    ),
                )
            )
        anchor_specs.append(
            (
                "end_frame",
                self._normalize_anchor_characters(end_frame_characters),
                self._build_end_anchor_state_text(
                    summary=summary,
                    timed_beats=timed_beats,
                    shot_state=shot_state,
                ),
            )
        )

        for (left_label, left_chars, left_state), (right_label, right_chars, right_state) in zip(
            anchor_specs,
            anchor_specs[1:],
        ):
            if not left_chars or left_chars != right_chars:
                continue
            if not left_state or not right_state:
                continue
            if (
                not requires_mid_frame
                and left_label == "start_frame"
                and right_label == "end_frame"
            ):
                if not self._start_end_keyframes_too_static(
                    left_state=left_state,
                    right_state=right_state,
                    allowed_changes=str(continuity_link.allowed_changes or "").strip(),
                ):
                    continue
            elif not self._keyframe_states_too_similar(left_state, right_state):
                continue
            anchor_names = "、".join(left_chars)
            raise ValueError(
                f"segment {segment_id} 的 {left_label} 与 {right_label} 关键帧语义距离过近。"
                f"当前同组角色为 {anchor_names}，但两帧都在描述几乎相同的可见状态。"
                "首中尾锚点必须体现可见的动作推进、站位变化、表情变化或收束差异，"
                "不要只把同一句状态换个说法重复三遍。"
            )

    def _normalize_anchor_characters(self, characters: list[str]) -> list[str]:
        return [
            str(name).strip()
            for name in characters
            if str(name).strip()
        ]

    def _build_start_anchor_state_text(
        self,
        *,
        summary: str,
        timed_beats: list[str],
        continuity_link,
        shot_state,
    ) -> str:
        return self._first_nonempty_anchor_text(
            str(continuity_link.opening_match or "").strip(),
            self._first_timed_beat_text(timed_beats),
            str(shot_state.blocking or "").strip(),
            str(summary or "").strip(),
        )

    def _build_mid_anchor_state_text(
        self,
        *,
        summary: str,
        timed_beats: list[str],
        shot_state,
    ) -> str:
        return self._first_nonempty_anchor_text(
            self._middle_timed_beat_text(timed_beats),
            str(shot_state.blocking or "").strip(),
            str(shot_state.action_progression or "").strip(),
            str(summary or "").strip(),
        )

    def _build_end_anchor_state_text(
        self,
        *,
        summary: str,
        timed_beats: list[str],
        shot_state,
    ) -> str:
        return self._first_nonempty_anchor_text(
            str(shot_state.end_state_lock or "").strip(),
            self._last_timed_beat_text(timed_beats),
            str(shot_state.action_progression or "").strip(),
            str(summary or "").strip(),
        )

    def _first_timed_beat_text(self, timed_beats: list[str]) -> str:
        return str(timed_beats[0] or "").strip() if timed_beats else ""

    def _middle_timed_beat_text(self, timed_beats: list[str]) -> str:
        if not timed_beats:
            return ""
        return str(timed_beats[len(timed_beats) // 2] or "").strip()

    def _last_timed_beat_text(self, timed_beats: list[str]) -> str:
        return str(timed_beats[-1] or "").strip() if timed_beats else ""

    def _first_nonempty_anchor_text(self, *values: str) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _keyframe_states_too_similar(self, left_state: str, right_state: str) -> bool:
        normalized_left = self._normalize_anchor_state_for_similarity(left_state)
        normalized_right = self._normalize_anchor_state_for_similarity(right_state)
        overlap = _text_overlap_ratio(normalized_left, normalized_right)
        if overlap < 0.82:
            stalled_overlap = (
                overlap >= 0.72
                and (
                    _text_explicitly_stalled(normalized_left)
                    or _text_explicitly_stalled(normalized_right)
                )
            )
            if not stalled_overlap:
                return False
        new_signal_count = _text_new_signal_count(normalized_left, normalized_right)
        left_terms = _extract_progression_signal_terms(normalized_left)
        right_terms = _extract_progression_signal_terms(normalized_right)
        if right_terms - left_terms:
            return False
        if (
            overlap >= 0.72
            and (
                _text_explicitly_stalled(normalized_left)
                or _text_explicitly_stalled(normalized_right)
            )
        ):
            return True
        if new_signal_count > 2:
            return False
        if _progress_text_too_generic(normalized_right):
            return True
        return overlap >= 0.88 and new_signal_count <= 1

    def _start_end_keyframes_too_static(
        self,
        *,
        left_state: str,
        right_state: str,
        allowed_changes: str,
    ) -> bool:
        normalized_left = self._normalize_anchor_state_for_similarity(left_state)
        normalized_right = self._normalize_anchor_state_for_similarity(right_state)
        normalized_allowed = self._normalize_anchor_state_for_similarity(allowed_changes)
        if (
            _text_explicitly_stalled(normalized_left)
            and _text_explicitly_stalled(normalized_right)
            and (
                not normalized_allowed
                or _text_explicitly_stalled(normalized_allowed)
                or _progress_text_too_generic(normalized_allowed)
            )
        ):
            return True
        overlap = _text_overlap_ratio(normalized_left, normalized_right)
        if overlap < 0.7:
            return False
        new_signal_count = _text_new_signal_count(normalized_left, normalized_right)
        if new_signal_count > 2:
            return False
        if (
            _text_explicitly_stalled(normalized_left)
            or _text_explicitly_stalled(normalized_right)
        ):
            return True
        if not normalized_allowed or _progress_text_too_generic(normalized_allowed):
            return overlap >= 0.76
        return _text_overlap_ratio(normalized_left, normalized_allowed) >= 0.74

    def _normalize_anchor_state_for_similarity(self, text: str) -> str:
        normalized = str(text or "").strip()
        normalized = re.sub(r"^\d+(?:\.\d+)?\s*[-~到]\s*\d+(?:\.\d+)?\s*秒[:：]\s*", "", normalized)
        return normalized.strip()

    def _validate_scene_segment_contract_output(
        self,
        contracts: SceneSegmentContractBatchSchema,
        *,
        scene: ChapterSceneSchema,
        allow_nonstart_first_segment: bool = False,
        creative_strict: bool = True,
        warning_sink: list[str] | None = None,
    ) -> SceneSegmentContractBatchSchema:
        if not contracts.segments:
            raise ValueError(f"scene {scene.scene_id} 没有产出任何 segment。")
        seen_segment_ids: set[str] = set()
        normalized_segments: list[SceneSegmentContractSchema] = []
        previous_segment: SceneSegmentContractSchema | None = None
        for index, segment in enumerate(contracts.segments, start=1):
            if segment.chapter_number != scene.chapter_number:
                raise ValueError(
                    f"segment {segment.segment_id} 的 chapter_number 必须为 {scene.chapter_number}。"
                )
            if segment.scene_id != scene.scene_id:
                raise ValueError(
                    f"segment {segment.segment_id} 的 scene_id 必须为 {scene.scene_id}。"
                )
            if segment.segment_id in seen_segment_ids:
                raise ValueError(f"segment_id 重复：{segment.segment_id}")
            seen_segment_ids.add(segment.segment_id)
            if not segment.title.strip() or not segment.summary.strip():
                raise ValueError(f"segment {segment.segment_id} 缺少 title 或 summary。")
            if not segment.involved_characters:
                raise ValueError(f"segment {segment.segment_id} 缺少 involved_characters。")
            if not (self.PLANNER_MIN_DURATION_SECONDS <= segment.duration_seconds <= self.SEEDANCE_MAX_DURATION_SECONDS):
                raise ValueError(
                    f"segment {segment.segment_id} 的 duration_seconds 必须在 "
                    f"{self.PLANNER_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒之间。"
                )
            narration, dialogue_lines, subtitle_lines = self._sanitize_segment_audio_tracks(
                narration=segment.narration,
                dialogue_lines=segment.dialogue_lines,
                subtitle_lines=segment.subtitle_lines,
                summary=segment.summary,
                timed_beats=segment.timed_beats,
                involved_characters=segment.involved_characters,
            )
            if (
                narration != segment.narration
                or dialogue_lines != list(segment.dialogue_lines)
                or subtitle_lines != list(segment.subtitle_lines)
            ):
                segment = segment.model_copy(
                    update={
                        "narration": narration,
                        "dialogue_lines": dialogue_lines,
                        "subtitle_lines": subtitle_lines,
                    }
                )
            required_duration = self._estimate_required_speech_duration(
                narration=segment.narration,
                dialogue_lines=segment.dialogue_lines,
                subtitle_lines=segment.subtitle_lines,
            )
            fitted_duration = self._fit_duration_to_speech_budget(
                segment_id=segment.segment_id,
                current_duration_seconds=segment.duration_seconds,
                required_duration_seconds=required_duration,
                allow_split_retry=True,
            )
            if fitted_duration != segment.duration_seconds:
                segment = segment.model_copy(
                    update={"duration_seconds": fitted_duration}
                )
            self._validate_timed_beats_timeline(
                segment_id=segment.segment_id,
                timed_beats=segment.timed_beats,
                duration_seconds=segment.duration_seconds,
                require_full_coverage=True,
            )
            if not segment.start_frame_characters:
                raise ValueError(f"segment {segment.segment_id} 的 start_frame_characters 不能为空。")
            if not segment.end_frame_characters:
                raise ValueError(f"segment {segment.segment_id} 的 end_frame_characters 不能为空。")
            transition_mode = segment.continuity_link.transition_mode.strip().lower()
            if index == 1:
                if allow_nonstart_first_segment:
                    if transition_mode not in {"continue", "cut"}:
                        raise ValueError(
                            f"segment {segment.segment_id} 作为非起始 chunk 首段时，"
                            "continuity_link.transition_mode 只能是 continue 或 cut。"
                        )
                elif transition_mode != "start":
                    raise ValueError(
                        f"segment {segment.segment_id} 作为当前 chunk 首段时，"
                        "continuity_link.transition_mode 必须为 start。"
                    )
            elif transition_mode not in {"continue", "cut"}:
                raise ValueError(
                    f"segment {segment.segment_id} 作为非首段时，"
                    "continuity_link.transition_mode 只能是 continue 或 cut。"
                )
            effective_requires_mid_frame = self._should_require_mid_frame(
                involved_characters=segment.involved_characters,
                duration_seconds=segment.duration_seconds,
                dialogue_lines=segment.dialogue_lines,
                timed_beats=segment.timed_beats,
                requested=segment.requires_mid_frame,
            )
            mid_frame_requirement_reasons = self._mid_frame_requirement_reasons(
                involved_characters=segment.involved_characters,
                duration_seconds=segment.duration_seconds,
                dialogue_lines=segment.dialogue_lines,
                timed_beats=segment.timed_beats,
            )
            if effective_requires_mid_frame and not segment.requires_mid_frame:
                reason_suffix = (
                    " 触发条件："
                    + "；".join(mid_frame_requirement_reasons)
                    + "。"
                    if mid_frame_requirement_reasons
                    else ""
                )
                raise ValueError(
                    f"segment {segment.segment_id} 满足中段锚点帧条件时，"
                    "requires_mid_frame 必须为 true，且必须显式给出 mid_frame_characters。"
                    + reason_suffix
                )
            if effective_requires_mid_frame and not segment.mid_frame_characters:
                reason_suffix = (
                    " 当前这段之所以必须有中段锚点帧，是因为："
                    + "；".join(mid_frame_requirement_reasons)
                    + "。"
                    if mid_frame_requirement_reasons
                    else ""
                )
                raise ValueError(
                    f"segment {segment.segment_id} 的 mid_frame_characters 不能为空，"
                    "且只能使用 involved_characters 内角色。"
                    + reason_suffix
                )
            for field_name, characters in (
                ("start_frame_characters", segment.start_frame_characters),
                (
                    "mid_frame_characters",
                    segment.mid_frame_characters if effective_requires_mid_frame else [],
                ),
                ("end_frame_characters", segment.end_frame_characters),
            ):
                invalid_names = [
                    name for name in characters
                    if name not in segment.involved_characters
                ]
                if invalid_names:
                    raise ValueError(
                        f"{segment.segment_id} 的 {field_name} 只能使用 involved_characters 内角色："
                        + "、".join(invalid_names)
                    )
            if effective_requires_mid_frame:
                self._validate_mid_frame_anchor_group_continuity(
                    segment_id=segment.segment_id,
                    start_frame_characters=segment.start_frame_characters,
                    mid_frame_characters=segment.mid_frame_characters,
                    mid_frame_mode=segment.mid_frame_mode,
                    end_frame_characters=segment.end_frame_characters,
                )
            if creative_strict:
                self._validate_keyframe_semantic_distance(
                    segment_id=segment.segment_id,
                    summary=segment.summary,
                    timed_beats=segment.timed_beats,
                    start_frame_characters=segment.start_frame_characters,
                    mid_frame_characters=segment.mid_frame_characters,
                    end_frame_characters=segment.end_frame_characters,
                    requires_mid_frame=effective_requires_mid_frame,
                    mid_frame_mode=segment.mid_frame_mode,
                    continuity_link=segment.continuity_link,
                    shot_state=segment.shot_state,
                )
            else:
                try:
                    self._validate_keyframe_semantic_distance(
                        segment_id=segment.segment_id,
                        summary=segment.summary,
                        timed_beats=segment.timed_beats,
                        start_frame_characters=segment.start_frame_characters,
                        mid_frame_characters=segment.mid_frame_characters,
                        end_frame_characters=segment.end_frame_characters,
                        requires_mid_frame=effective_requires_mid_frame,
                        mid_frame_mode=segment.mid_frame_mode,
                        continuity_link=segment.continuity_link,
                        shot_state=segment.shot_state,
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="shot_state.framing",
                prompt_text=segment.shot_state.framing,
                frame_characters=segment.start_frame_characters,
                frame_label="start_frame",
            )
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="shot_state.camera_motion",
                prompt_text=segment.shot_state.camera_motion,
                frame_characters=segment.start_frame_characters,
                frame_label="start_frame",
            )
            if effective_requires_mid_frame:
                self._validate_single_frame_focus_conflict(
                    segment_id=segment.segment_id,
                    field_name="shot_state.framing",
                    prompt_text=segment.shot_state.framing,
                    frame_characters=segment.mid_frame_characters,
                    frame_label="mid_frame",
                )
                self._validate_single_frame_focus_conflict(
                    segment_id=segment.segment_id,
                    field_name="shot_state.camera_motion",
                    prompt_text=segment.shot_state.camera_motion,
                    frame_characters=segment.mid_frame_characters,
                    frame_label="mid_frame",
                )
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="shot_state.framing",
                prompt_text=segment.shot_state.framing,
                frame_characters=segment.end_frame_characters,
                frame_label="end_frame",
            )
            self._validate_single_frame_focus_conflict(
                segment_id=segment.segment_id,
                field_name="shot_state.camera_motion",
                prompt_text=segment.shot_state.camera_motion,
                frame_characters=segment.end_frame_characters,
                frame_label="end_frame",
            )
            self._validate_segment_action_capacity(
                segment_id=segment.segment_id,
                timed_beats=segment.timed_beats,
                duration_seconds=segment.duration_seconds,
                allow_split_retry=True,
            )
            if not segment.continuity_link.opening_match.strip():
                warning_message = f"segment {segment.segment_id} 缺少 continuity_link.opening_match。"
                if creative_strict:
                    raise ValueError(warning_message)
                if warning_sink is not None:
                    warning_sink.append(warning_message)
            opening_match = segment.continuity_link.opening_match.strip()
            if any(phrase in opening_match for phrase in GENERIC_OPENING_MATCH_PHRASES):
                warning_message = (
                    f"segment {segment.segment_id} 的 continuity_link.opening_match 过于空泛，"
                    "必须写出可拍到的开场状态。"
                )
                if creative_strict:
                    raise ValueError(warning_message)
                if warning_sink is not None:
                    warning_sink.append(warning_message)
            allow_scene_boundary_carry_over = (
                index == 1
                and bool(str(scene.scene_transition_contract.previous_scene_id or "").strip())
            )
            if (
                transition_mode == "start"
                and "承接上一段" in opening_match
                and not allow_scene_boundary_carry_over
            ):
                warning_message = (
                    f"segment {segment.segment_id} 作为起始段时，"
                    "continuity_link.opening_match 不能写成上一段承接话术。"
                )
                if creative_strict:
                    raise ValueError(warning_message)
                if warning_sink is not None:
                    warning_sink.append(warning_message)
            if not segment.continuity_link.allowed_changes.strip():
                raise ValueError(f"segment {segment.segment_id} 缺少 continuity_link.allowed_changes。")
            if not segment.continuity_link.transition_reason.strip():
                raise ValueError(f"segment {segment.segment_id} 缺少 continuity_link.transition_reason。")
            if previous_segment is not None and transition_mode == "continue":
                previous_end_state = (
                    previous_segment.shot_state.end_state_lock.strip()
                    or previous_segment.shot_state.action_progression.strip()
                    or previous_segment.summary.strip()
                )
                opening_overlap = _text_overlap_ratio(
                    segment.continuity_link.opening_match.strip(),
                    previous_end_state,
                )
                if opening_overlap < 0.22:
                    warning_message = (
                        f"segment {segment.segment_id} 的 continuity_link.opening_match "
                        "没有明确承接上一段尾部状态。"
                    )
                    if creative_strict:
                        raise ValueError(warning_message)
                    if warning_sink is not None:
                        warning_sink.append(warning_message)
            normalized_segments.append(segment)
            previous_segment = segment
        return contracts.model_copy(update={"segments": normalized_segments})

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

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT] | None = None,
    ) -> StructuredModelT:
        attempts = self.structured_retry_attempts
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=attempts,
            validator=validator,
            request_builder=self._build_retry_request,
            response_coercer=self._coerce_structured_response,
            failure_builder=lambda last_error: VideoStructuredGenerationError(
                task=str(request.metadata.get("task", "structured-agent")),
                schema_name=schema.__name__,
                attempts=attempts,
                cause=last_error or RuntimeError("unknown structured generation failure"),
                metadata=dict(request.metadata),
            ),
        )

    def _run_strict_structured_agent(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT],
        attempts: int = 3,
    ) -> StructuredModelT:
        total_attempts = max(1, attempts)
        task_name = str(request.metadata.get("task", "structured-repair"))
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=total_attempts,
            validator=validator,
            request_builder=self._build_repair_retry_request,
            response_coercer=self._validate_structured_response,
            failure_builder=lambda last_error: RuntimeError(
                f"Structured repair failed for task={task_name} schema={schema.__name__} "
                f"after {total_attempts} attempts: {last_error or 'unknown error'}"
            ),
        )

    def _build_repair_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        task_name = str(request.metadata.get("task", "") or "").strip()
        normalized_error = " ".join(str(last_error or "").split()).strip()
        if task_name == "video-chapter-event-repair" and "关键事件" in normalized_error and "过于粗" in normalized_error:
            offending_event_id = ""
            match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", normalized_error)
            if match is not None:
                offending_event_id = match.group(1).strip()
            metadata = dict(request.metadata)
            if offending_event_id:
                metadata["offending_event_id"] = offending_event_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_event_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_event_id}` 及其后续编号，"
                    "不要回头大改前面已经合理的 event。"
                )
            retry_prompt += (
                " 如果当前失败项不是章节首尾 event，就必须压到 1-2 个推进点；"
                "如果压不住，就直接拆成两个连续 event，并把后续 event_id 顺延。"
                " 中间 event 不要再把问句、回答、动作结果三连塞在一起。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-chapter-event-split-repair" and "关键事件" in normalized_error and "过于粗" in normalized_error:
            offending_event_id = ""
            match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", normalized_error)
            if match is not None:
                offending_event_id = match.group(1).strip()
            metadata = dict(request.metadata)
            if offending_event_id:
                metadata["offending_event_id"] = offending_event_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次拆分输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            retry_prompt += (
                " 这次任务不是重写整章，而是只把当前粗事件拆开。"
                " replacement events 至少输出 2 条，通常 2-3 条即可。"
                " 每条 replacement event 只保留更窄的一拍推进，不要再把问句、回答、动作结果或关系落点重新合并回同一条。"
                " 不要输出 event_id，不要改写相邻 event，不要解释，不要输出 Markdown 代码块。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-chunk-repair" and "chunk" in normalized_error and "动作容量过载" in normalized_error:
            offending_chunk_id = ""
            required_segment_count = 0
            chunk_match = re.search(r"chunk\s+(\S+)\s+动作容量过载", normalized_error)
            if chunk_match is not None:
                offending_chunk_id = str(chunk_match.group(1) or "").strip()
            required_match = re.search(r"expected_segment_count 至少应为\s+(\d+)", normalized_error)
            if required_match is not None:
                required_segment_count = int(required_match.group(1))
            metadata = dict(request.metadata)
            if offending_chunk_id:
                metadata["offending_chunk_id"] = offending_chunk_id
            if required_segment_count > 0:
                metadata["required_segment_count"] = required_segment_count
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_chunk_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_chunk_id}`，不要回头大改前面已经合理的 chunk。"
                )
            if required_segment_count > 0:
                retry_prompt += (
                    f" 当前失败项如果继续保留为单个 chunk，`expected_segment_count` 至少要改成 {required_segment_count}；"
                    "如果你不想提高它，就必须把当前 chunk 拆成两个连续 chunk。"
                )
            retry_prompt += (
                " 不要再把 4 个及以上推进点继续塞在同一个 chunk。"
                " `must_cover` 与 `transition_goal` 只保留当前 chunk 自己负责的那一小段推进。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-timeline-repair" and "timed_beats" in normalized_error:
            offending_segment_id = ""
            segment_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+timed_beats",
                normalized_error,
            )
            if segment_match is not None:
                offending_segment_id = str(segment_match.group("segment_id") or "").strip()
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}` 的 timed_beats，"
                    "不要回头大改已经合理的其他 segment。"
                )
            retry_prompt += (
                " 末尾 beat 必须补到接近该段 duration_seconds 结束，"
                "明确写出尾部可拍到的反应、停顿、走位收束或镜头停点。"
                " 如果只是尾部少了 1-3 秒，不要新造剧情结果，优先在现有结果上补完整收束。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-action-repair" and "动作容量过载" in normalized_error:
            offending_segment_id = ""
            required_segment_count = 0
            segment_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+动作容量过载",
                normalized_error,
            )
            if segment_match is not None:
                offending_segment_id = str(segment_match.group("segment_id") or "").strip()
            required_match = re.search(
                r"当前 chunk 必须至少拆成\s+(?P<count>\d+)\s+个 segment",
                normalized_error,
            )
            if required_match is not None:
                required_segment_count = int(required_match.group("count"))
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            if required_segment_count > 0:
                metadata["required_segment_count"] = required_segment_count
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}`，"
                    "不要回头大改已经合理的其他 segment。"
                )
            if required_segment_count > 0:
                retry_prompt += (
                    f" 当前 chunk 至少要拆成 {required_segment_count} 个 segment；"
                    "不要继续把多个动作结果硬塞回单段。"
                )
            retry_prompt += (
                " 你必须按动作结果、对白轮次、入画变化或关系推进点把过载片段拆开，"
                "让每一段只承担更窄的一拍推进。"
                " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            )
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        if task_name == "video-scene-segment-focus-repair" and "多人同帧时仍要求单人特写" in normalized_error:
            parsed = self._parse_scene_segment_focus_conflict_failure(normalized_error)
            offending_segment_id = str(parsed.get("segment_id", "") or "").strip()
            field_name = str(parsed.get("field_name", "") or "").strip()
            frame_label = str(parsed.get("frame_label", "") or "").strip()
            frame_characters = list(parsed.get("frame_characters", []) or [])
            frame_names = "、".join(frame_characters) or "未知角色"
            focus_name = frame_characters[0] if frame_characters else "主角"
            metadata = dict(request.metadata)
            if offending_segment_id:
                metadata["offending_segment_id"] = offending_segment_id
            if field_name:
                metadata["field_name"] = field_name
            if frame_label:
                metadata["frame_label"] = frame_label
            retry_prompt = request.user_prompt
            retry_prompt += (
                f"\n\n上一次修复输出未通过结构化校验。这是第 {attempt} 次尝试。"
                f" 失败原因：{normalized_error}。"
            )
            if offending_segment_id:
                retry_prompt += (
                    f" 本次只优先修 `{offending_segment_id}`，"
                    "不要回头大改已经合理的其他 segment。"
                )
            retry_prompt += (
                f" 当前冲突帧是 `{frame_label or 'unknown_frame'}`，角色组是 `{frame_names}`。"
                f" 只要这一帧仍保持 `{frame_names}` 同框，就必须把 `shot_state.framing` 和 `shot_state.camera_motion` 一起改成共享镜头语言，"
                f"例如“轻微前推，保持 {frame_names} 同框，只通过站位和表情差异突出 {focus_name} 情绪变化”。"
                " 不要再保留任何“单人近景”“侧脸特写”“聚焦某人脸部”这类单人特写话术。"
            )
            if frame_label == "mid_frame":
                retry_prompt += (
                    " 如果你坚持把中段写成单人反应镜头，必须显式改成 `mid_frame_mode=insert_cut`，"
                    "并把 `mid_frame_characters`、`timed_beats` 与 shared shot 的来回切换一起改对。"
                )
            else:
                retry_prompt += (
                    f" 当前报错不是 `mid_frame`，不要把 `{frame_label}` 主锚点偷偷改成单人特写来规避校验。"
                )
            retry_prompt += " 不要解释，不要输出 Markdown 代码块，不要漏字段。"
            return PromptRequest(
                system_prompt=request.system_prompt,
                user_prompt=retry_prompt,
                metadata=metadata,
            )
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次修复输出未通过结构化校验。",
            retry_suffix="不要解释，不要输出 Markdown 代码块，不要缺字段，不要改目标 segment_id。",
        )

    def _build_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次输出未通过结构化校验。",
            retry_suffix=(
                "不要解释，不要输出 Markdown 代码块，不要遗漏字段，"
                "不要把分析备注写成正式分镜内容。"
            ),
        )

    def _build_structured_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
        retry_prefix: str,
        retry_suffix: str,
    ) -> PromptRequest:
        if attempt <= 1:
            return request

        normalized_error = " ".join(str(last_error or "").split()).strip()
        retry_note = f"\n\n{retry_prefix}这是第 {attempt} 次尝试。"
        if normalized_error:
            retry_note += f" 失败原因：{normalized_error}。"
        if "finish_reason='length'" in normalized_error or 'finish_reason="length"' in normalized_error:
            retry_note += (
                " 这次失败说明上一次输出过长被截断。"
                "请显著压缩输出：scene_bible 只保留短句和少量列表项，"
                "segment 不要重复父级 scene 的 scene_title/scene_summary/scene_anchor/scene_bible，"
                "title、summary、narration、shot_state、continuity_link 字段都尽量只写 1 句短描述。"
                "timed_beats 通常控制在 1-3 条，不要用长段散文。"
            )
        if "当前对白/字幕至少需要" in normalized_error:
            retry_note += (
                " 这次失败说明对白、旁白或字幕仍然过长。"
                "本次必须显著压缩 narration、dialogue_lines、subtitle_lines 的总字数，"
                "确保 required_duration 不超过 duration_seconds。"
                "如果 12 秒内说不完，就删减文本，不要保留原长对白。"
            )
        if isinstance(last_error, SegmentSpeechSplitRequiredError):
            retry_note += (
                f" 这次失败说明某个 segment 的对白预算约 {last_error.required_duration_seconds} 秒，"
                f"已经超过单段 {last_error.max_duration_seconds} 秒上限。"
                f" 本次必须把当前 chunk 至少拆成 {last_error.required_segment_count} 个 segment，"
                "按对白轮次、句意边界或动作结果落点重排，"
                "不要再尝试把整段对白压成单段。"
            )
        if isinstance(last_error, SegmentActionSplitRequiredError):
            retry_note += (
                f" 这次失败说明某个 segment 的动作容量约有 {last_error.action_node_count} 个推进点，"
                f"但当前 {last_error.current_duration_seconds} 秒片段最多只允许 {last_error.max_action_nodes} 个。"
                f" 本次必须把当前 chunk 至少拆成 {last_error.required_segment_count} 个 segment，"
                "按动作结果、对白轮次、入画变化或关系推进点拆开，"
                "不要把“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”继续硬塞在同一段里。"
            )
        if "动作容量过载" in normalized_error and "expected_segment_count 至少应为" in normalized_error:
            retry_note += (
                " 这次失败说明某个 chunk 自己就塞了太多推进点。"
                "请在 chunk 层先拆开事件，或把 `expected_segment_count` 提高到足够覆盖这些推进点。"
                "如果 `must_cover + transition_goal` 已经包含多轮动作结果，不要还写成 1 个 segment。"
            )
        if (
            "缺少 timed_beats" in normalized_error
            or "timed_beats 不能为空" in normalized_error
            or (
                "timed_beats" in normalized_error
                and ("Field required" in normalized_error or "missing" in normalized_error.lower())
            )
        ):
            retry_note += (
                " 这次失败说明有片段漏掉了必填的 timed_beats。"
                "本次输出时，每个 segment 都必须显式带非空 timed_beats 列表，"
                "即使是纯动作段也不能省略。"
                "每条 timed_beats 都要写成“0-2秒：发生了什么”的具体秒数格式，"
                "并覆盖该段的开场、推进和收束。"
            )
        if "尾部约" in normalized_error and "缺少明确动作或收束节拍" in normalized_error:
            retry_note += (
                " 这次失败说明 timed_beats 虽然存在，但最后几秒没有覆盖完整时长。"
                "本次必须把最后一条 beat 或新增一条收束 beat 补到接近 duration_seconds 结束，"
                "明确写出尾部的反应、停顿、走位收束或镜头停点。"
                "不要再让片段在最后 1-3 秒处于没有合同约束的空白状态。"
            )
        if "关键帧语义距离过近" in normalized_error:
            retry_note += (
                " 这次失败说明首帧、中段帧、尾帧里至少有两帧在描述几乎相同的状态。"
                "本次必须把关键帧写成真正不同的可见停点："
                "start 负责开场建立状态，mid 负责中途推进或关系变化，end 负责尾部收束。"
                "如果是同组角色的连续主镜头，就不要把三帧都写成同一站位、同一表情、同一动作的近义改写；"
                "至少要明确其中一项变化：动作推进、站位变化、朝向变化、距离变化、表情变化或收束结果。"
            )
        if "mid_frame_characters 不能为空" in normalized_error or "只能使用 involved_characters 内角色" in normalized_error:
            retry_note += (
                " 这次失败说明中段出镜角色写错了。"
                "mid_frame_characters 必须严格跟随片段中间那一拍真实出镜的人物，"
                "不要直接照搬整个 scene cast，也不要把只在尾帧才出现的人提前写进中段帧。"
            )
        if "不能只保留首尾同组角色的一部分" in normalized_error:
            retry_note += (
                " 这次失败说明中段锚点把同一组多人角色写丢了。"
                "如果首帧和尾帧是同一组双人或多人，而中段只是其中一人的反应特写或动作插入镜头，"
                "就必须把 `mid_frame_mode` 明确设成 `insert_cut`，"
                "并把 `timed_beats`、`mid_frame_prompt`、`shot_state.camera_motion` 都写成"
                "“从双人主镜头切入单人特写，再切回双人主镜头”的完整运镜。"
                "如果不是插入镜头，就继续保留整组角色；"
                "不要出现没有声明 insert_cut 的“首尾两人，中段只剩其中一人”。"
            )
            anchor_group_match = re.search(
                r"首尾帧固定角色组为\s*(?P<anchors>[^，。]+)\s*，但中段写成了\s*(?P<mid>[^。]+)",
                normalized_error,
            )
            if anchor_group_match:
                anchor_names = str(anchor_group_match.group("anchors") or "").strip()
                mid_names = str(anchor_group_match.group("mid") or "").strip()
                if anchor_names and mid_names:
                    retry_note += (
                        f" 本次按二选一修正即可："
                        f"如果中段仍是连续主镜头，就把 `mid_frame_characters` 改回 `{anchor_names}`，"
                        "并写 `mid_frame_mode=continuous`；"
                        f"如果中段确实只拍 `{mid_names}` 的插入特写，"
                        "就保留该中段角色，但必须写 `mid_frame_mode=insert_cut`，"
                        f"并让 `timed_beats` 明确成“先 {anchor_names} 同框 -> 再切 {mid_names} 单人 -> 最后回到 {anchor_names} 同框”。"
                        "不要再输出“首尾整组、中段只剩一人、但 mid_frame_mode 仍是 continuous”的半对半错结构。"
                    )
        if "多人同帧时仍要求单人特写" in normalized_error or "单帧里重复出现" in normalized_error:
            retry_note += (
                " 这次失败说明某一帧的人物构图自相矛盾。"
                "如果某一帧是双人或多人同框，就不要再写“某角色侧脸特写 / 大特写 / 单人近景”。"
                "尤其 `shot_state.framing` 和 `shot_state.camera_motion` 是整个 segment 共享的镜头约束，"
                "只要 start/mid/end 任一帧会出现双人，就不要在这两个字段里写指向某一个角色的特写动作。"
                "同一帧里同一角色只能出现一次；需要单人特写时，就把该帧的 frame_characters 改成单人，"
                "或者改写成双人同构图下的自然表情表现。"
                "例如：如果 start_frame 是 `苏晴、林远`，就不要写“推向苏晴侧脸特写”；"
                "应改成“轻微前推，保持两人同框并捕捉苏晴表情变化”。"
            )
            multi_focus_match = re.search(
                r"segment\s+(?P<segment_id>\S+)\s+的\s+(?P<field_name>[^\s]+)\s+在\s+"
                r"(?P<frame_label>start_frame|mid_frame|end_frame)\s*"
                r"\((?P<frame_names>[^)]+)\)\s*多人同帧时仍要求单人特写",
                normalized_error,
            )
            if multi_focus_match:
                field_name = str(multi_focus_match.group("field_name") or "").strip()
                frame_label = str(multi_focus_match.group("frame_label") or "").strip()
                frame_names = str(multi_focus_match.group("frame_names") or "").strip()
                if field_name and frame_label and frame_names:
                    focus_name = frame_names.split("、", 1)[0].strip() or frame_names
                    retry_note += (
                        f" 本次直接按这条修：当前报错的是 `{field_name}` 在 `{frame_label}`，"
                        f"该帧角色是 `{frame_names}`。"
                        f"如果 `{frame_label}` 仍要求 `{frame_names}` 同框，"
                        f"就把 `{field_name}` 改写成共享镜头语言，"
                        f"例如“轻微前推，保持 {frame_names} 同框，只通过站位和表情差异突出 {focus_name} 情绪变化”；"
                        f"不要再写“推向 {focus_name} 侧脸特写”“聚焦到 {focus_name} 脸部”这类单人特写句。"
                    )
        if "缺少 continuity_link.opening_match" in normalized_error or "opening_match 过于空泛" in normalized_error:
            retry_note += (
                " 这次失败说明 opening_match 不合格。"
                "无论是 start 还是 continue，opening_match 都必须写成可拍到的开场状态，"
                "不要留空，也不要写“承接上一段继续”“场景开始”这类空话。"
            )
        if "首段 opening_match 没有明确承接上一 chunk 尾部状态" in normalized_error:
            retry_note += (
                " 这次失败说明跨 chunk 首段没有把上一 chunk 的尾部状态真正复现到开场画面里。"
                "请直接复用 `上一 chunk 退出状态 JSON` 里的 `visible_tail_state`、"
                "`opening_match_seed` 和 `carry_over_elements`，"
                "把当前首段的 continuity_link.opening_match 改写成可拍到的承接句。"
                "优先写清角色仍保持的站位、朝向、道具和动作停点，"
                "例如“承接上一 chunk 尾部，陈默仍停在长椅旁微微回头，保持刚听见脚步声后停住的姿态”。"
                "不要只写“继续推进到会面”“承接上一段尾部”这类抽象总结。"
            )
        if (
            "scene_transition_contract" in normalized_error
            or "首个 chunk 没有消费 scene_transition_contract" in normalized_error
            or "首段 opening_match 没有承接 scene_transition_contract" in normalized_error
            or "首段 timed_beats 没有消费 scene_transition_contract" in normalized_error
        ):
            retry_note += (
                " 这次失败说明跨 scene 过渡合同没有被真正消费。"
                "如果当前不是首个 scene，就必须先用 `scene_transition_contract` 建立上一场尾部到当前场开头的桥。"
                "本次至少要做到三点："
                "第一，scene 级合同里的 `previous_scene_id / transition_mode / next_scene_entry_match` 不能缺；"
                "第二，首个 chunk 必须把 `bridge_action` 和 `visual_bridge` 写进自己的开场推进；"
                "第三，首个 segment 的 `opening_match` 和前 1-2 条 `timed_beats` 必须先承接上一场尾部，再 reveal 当前场环境。"
                "不要把新 scene 直接写成毫无来由的重新开场。"
            )
        if (
            "covered_event_ids" in normalized_error
            or "关键事件覆盖" in normalized_error
            or "章节关键事件" in normalized_error
            or "must-cover event" in normalized_error
            or "source_evidence 无法在当前章节正文中定位" in normalized_error
        ):
            retry_note += (
                " 这次失败说明当前章节的 scene 没有完整覆盖关键事件。"
                "本次必须严格对齐关键事件列表：每个 scene 都要填写 covered_event_ids，"
                "所有 covered_event_ids 拼接后必须与关键事件顺序完全一致，"
                "尤其不能漏掉章节后半段的关系落点、动作结果或结尾决定。"
            )
        if "关键事件" in normalized_error and "推进点" in normalized_error and "过于粗" in normalized_error:
            retry_note += (
                " 这次失败说明 chapter event planner 把多个推进阶段合并成了同一个关键事件。"
                "本次必须把粗事件拆成更细的相邻 event："
                "普通 event 最多只保留 1-2 个紧密绑定的推进点；如果当前章节已经拆成多个 event，章节首尾 event 最多允许 3 个。"
                "如果一句里已经同时出现“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”，"
                "就必须改写成多个连续 event_id，而不是继续塞进同一个 summary。"
                "背景介绍、关系说明、回忆补叙如果只是解释上下文，也不要单独建成 must-cover event。"
                "中间 event 尤其不能把一轮问句、一次回答和一个动作结果同时塞进去。"
                "`source_evidence` 也只保留当前 event 对应的 1-2 个相邻正文短句，"
                "不要把后续 event 的证据一起拼进来。"
            )
        if "重复表达同一事件" in normalized_error or "adjacent_segment_duplicate" in normalized_error:
            retry_note += (
                " 这次失败说明你把同一动作链拆得过碎。"
                "本次应主动合并近义相邻 segment，优先减少 segment 数，"
                "不要为了凑满 expected_segment_count 而重复同一事件。"
            )
        retry_note += f" 请严格按 {schema.__name__} 返回。{retry_suffix}"
        metadata = dict(request.metadata)
        metadata["structured_retry_attempt"] = attempt
        return PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt + retry_note,
            metadata=metadata,
        )

    def _execute_structured_request(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        attempts: int,
        validator: Callable[[StructuredModelT], StructuredModelT] | None,
        request_builder: Callable[..., PromptRequest],
        response_coercer: Callable[[object, type[StructuredModelT]], StructuredModelT],
        failure_builder: Callable[[Exception | None], Exception],
    ) -> StructuredModelT:
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            attempt_request = request_builder(
                request=request,
                schema=schema,
                attempt=attempt,
                last_error=last_error,
            )
            attempt_request = attach_prompt_metrics(attempt_request)
            request.metadata.update(
                {
                    "system_prompt_chars": attempt_request.metadata["system_prompt_chars"],
                    "user_prompt_chars": attempt_request.metadata["user_prompt_chars"],
                    "total_prompt_chars": attempt_request.metadata["total_prompt_chars"],
                }
            )
            try:
                response = self.backend.generate_structured(attempt_request, schema)
                candidate = response_coercer(response, schema)
                if validator is not None:
                    return validator(candidate)
                return candidate
            except AgentBackendUnavailableError:
                raise
            except Exception as exc:
                last_error = exc
        raise failure_builder(last_error)

    def _coerce_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        if response is None:
            raise RuntimeError(
                f"模型没有返回 {schema.__name__} 结构化对象；"
                "可能是本轮没有触发 tool call，也没有返回可解析 JSON。"
            )
        return schema.model_validate(response)

    def _validate_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        return schema.model_validate(response)

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

    def _extract_direction_semantics(self, text: str) -> set[str]:
        normalized = str(text or "").strip()
        if not normalized:
            return set()
        semantics: set[str] = set()
        if any(pattern.search(normalized) for pattern in DIRECTION_APPROACH_PATTERNS):
            semantics.add("approach")
        if any(pattern.search(normalized) for pattern in DIRECTION_RETREAT_PATTERNS):
            semantics.add("retreat")
        return semantics

    def _validate_segment_direction_consistency(
        self,
        *,
        segment_id: str,
        screen_direction: str,
        end_state_lock: str,
        end_frame_prompt: str,
        timed_beats: list[str],
    ) -> None:
        screen_semantics = self._extract_direction_semantics(screen_direction)
        tail_reference_text = " ".join(
            item
            for item in (
                end_state_lock,
                end_frame_prompt,
                timed_beats[-1] if timed_beats else "",
            )
            if str(item or "").strip()
        )
        tail_semantics = self._extract_direction_semantics(tail_reference_text)
        if len(screen_semantics) >= 2:
            raise ValueError(
                f"segment {segment_id} 的 shot_state.screen_direction 同时包含靠近镜头和远离镜头的相反方向语义："
                f"{screen_direction.strip()!r}。"
            )
        if len(tail_semantics) >= 2:
            raise ValueError(
                f"segment {segment_id} 的尾部收束文本同时包含靠近镜头和远离镜头的相反方向语义："
                f"{tail_reference_text.strip()!r}。"
            )
        if not screen_semantics or not tail_semantics:
            return
        if screen_semantics == tail_semantics:
            return
        raise ValueError(
            f"segment {segment_id} 的 shot_state.screen_direction 与尾部收束方向冲突。"
            f"screen_direction={screen_direction.strip()!r}；"
            f"end_state/end_frame={tail_reference_text.strip()!r}。"
            "请统一为同一运动轴线，不要一边写靠近镜头，一边又写背影远去或走向深处。"
        )

    def _validate_mid_frame_anchor_group_continuity(
        self,
        *,
        segment_id: str,
        start_frame_characters: list[str],
        mid_frame_characters: list[str],
        mid_frame_mode: str,
        end_frame_characters: list[str],
    ) -> None:
        normalized_start = [str(name).strip() for name in start_frame_characters if str(name).strip()]
        normalized_end = [str(name).strip() for name in end_frame_characters if str(name).strip()]
        start_anchor = set(normalized_start)
        end_anchor = set(normalized_end)
        if len(start_anchor) < 2 or start_anchor != end_anchor:
            return
        mid_anchor = {str(name).strip() for name in mid_frame_characters if str(name).strip()}
        if not mid_anchor:
            return
        if start_anchor.issubset(mid_anchor):
            return
        if start_anchor.isdisjoint(mid_anchor):
            return
        if self._normalize_mid_frame_mode(mid_frame_mode) == "insert_cut":
            return
        anchor_names = "、".join(normalized_start)
        mid_names = "、".join(
            str(name).strip()
            for name in mid_frame_characters
            if str(name).strip()
        ) or "空"
        raise ValueError(
            f"segment {segment_id} 的 mid_frame_characters 不能只保留首尾同组角色的一部分。"
            f"首尾帧固定角色组为 {anchor_names}，但中段写成了 {mid_names}。"
            "如果中段仍是这组角色的连续表演，就必须保留整组角色；"
            "如果中段是其中一人的插入特写，就必须把 mid_frame_mode 设为 insert_cut，"
            "并显式写出从双人镜头切入再切回双人镜头的运镜；"
            "否则就不要只保留其中一人。"
        )

    def _normalize_mid_frame_mode(self, value: str) -> str:
        return "insert_cut" if str(value or "").strip().lower() == "insert_cut" else "continuous"

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
