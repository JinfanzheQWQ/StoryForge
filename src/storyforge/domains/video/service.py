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
)
from storyforge.core.io import to_jsonable
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.errors import (
    SegmentSpeechSplitRequiredError,
    VideoStructuredGenerationError,
)
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    ContinuityLink,
    SceneBible,
    ShotState,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.planning import VideoPlanningMixin
from storyforge.domains.video.prompting import VideoPromptingMixin
from storyforge.domains.video.repair import VideoRepairMixin
from storyforge.domains.video.schemas import (
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    CharacterVisualBibleSchema,
    SceneContinuityRepairSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentChunkSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    SegmentContinuityRepairSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
TIMED_BEAT_PATTERN = re.compile(r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")
GENERIC_PROGRESS_FILLER_TERMS = (
    "继续",
    "承接",
    "保持",
    "延续",
    "推进",
    "过渡",
    "状态",
    "情绪",
    "动作",
    "关系",
    "当前",
    "片段",
    "场景",
)
PROGRESSION_SIGNAL_TERMS = (
    "走",
    "跑",
    "停",
    "回头",
    "转身",
    "抬头",
    "低头",
    "看",
    "望",
    "靠近",
    "走近",
    "迈步",
    "前进",
    "后退",
    "进入",
    "离开",
    "伸手",
    "递",
    "接",
    "开口",
    "说",
    "回答",
    "拥抱",
    "亲吻",
    "坐下",
    "起身",
)
NO_PROGRESS_PHRASES = (
    "没有新的动作推进",
    "没有继续前进",
    "继续保持",
    "保持当前",
    "停在原地",
    "仍停在",
    "继续停在",
    "没有推进",
)
GENERIC_OPENING_MATCH_PHRASES = (
    "承接上一段继续",
    "场景开始",
    "开场进入",
    "继续推进",
    "继续当前状态",
    "新场景开始",
)


def _normalize_similarity_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def _text_ngrams(value: str) -> set[str]:
    normalized = _normalize_similarity_text(value)
    if not normalized:
        return set()
    if len(normalized) <= 3:
        return {normalized}
    grams: set[str] = set()
    for size in (2, 3):
        if len(normalized) < size:
            continue
        grams.update(
            normalized[index : index + size]
            for index in range(len(normalized) - size + 1)
        )
    return grams


def _text_overlap_ratio(left: str, right: str) -> float:
    left_grams = _text_ngrams(left)
    right_grams = _text_ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))


def _text_new_signal_count(previous: str, current: str) -> int:
    return len(_text_ngrams(current) - _text_ngrams(previous))


def _progress_text_too_generic(text: str) -> bool:
    normalized = _normalize_similarity_text(text)
    if not normalized:
        return True
    reduced = normalized
    for token in GENERIC_PROGRESS_FILLER_TERMS:
        reduced = reduced.replace(token, "")
    return len(reduced) < 6


def _extract_progression_signal_terms(text: str) -> set[str]:
    normalized = _normalize_similarity_text(text)
    return {
        term
        for term in PROGRESSION_SIGNAL_TERMS
        if term and term in normalized
    }


def _text_explicitly_stalled(text: str) -> bool:
    normalized = _normalize_similarity_text(text)
    return any(
        _normalize_similarity_text(phrase) in normalized
        for phrase in NO_PROGRESS_PHRASES
    )


class NovelToVideoService(
    VideoPromptingMixin,
    VideoRepairMixin,
    VideoPlanningMixin,
):
    PLANNER_MIN_DURATION_SECONDS = 5
    SEEDANCE_MIN_DURATION_SECONDS = 2
    SEEDANCE_MAX_DURATION_SECONDS = 12
    SPEECH_CHARS_PER_SECOND = 3
    SCENE_SEGMENT_CHUNK_MAX_SEGMENTS = 4
    SCENE_MAX_EXPECTED_SEGMENTS = 8

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
            scene_structure = self._run_structured_agent(
                schema=ChapterSceneStructureSchema,
                request=PromptRequest(
                    system_prompt=(
                        "你是章节场景规划 Agent。"
                        "请只规划当前章节有哪些 scene。"
                        "只输出 scene 结构，不要输出 segment，不要输出图片 prompt。"
                    ),
                    user_prompt=self._build_chapter_scene_planner_user_prompt(
                        novel_package,
                        chapter_number=chapter.number,
                        story_memory=story_memory,
                    ),
                    metadata={
                        "task": "video-chapter-scene-planner",
                        "chapter_number": chapter.number,
                    },
                ),
                validator=lambda value, chapter_number=chapter.number: self._validate_chapter_scene_structure_output(
                    value,
                    novel_package=novel_package,
                    chapter_number=chapter_number,
                ),
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
        return merged_plan, story_memory

    def _build_chapter_plan_from_scene_structure(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene_structure: ChapterSceneStructureSchema,
    ) -> VideoSegmentPlanSchema:
        scene_plans = [
            self._build_scene_plan_from_scene_structure(
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter_number,
                raw_scene=scene,
            )
            for scene in scene_structure.scenes
        ]
        return self._merge_chapter_segment_plans(scene_plans)

    def _build_scene_plan_from_scene_structure(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        raw_scene: ChapterSceneSchema,
    ) -> VideoSegmentPlanSchema:
        materialized_scene = self._materialize_chapter_scene(
            raw_scene=raw_scene,
            novel_package=novel_package,
            chapter_number=chapter_number,
        )
        chunk_plan = self._plan_scene_chunk_outline(
            novel_package=novel_package,
            story_memory=story_memory,
            chapter_number=chapter_number,
            scene=materialized_scene,
        )
        chunk_batches: list[SceneSegmentContractBatchSchema] = []
        previous_chunk_exit_state: dict[str, object] | None = None
        previous_tail_segment: SceneSegmentContractSchema | None = None
        for chunk in chunk_plan.chunks:
            chunk_contracts = self._build_scene_chunk_contract_batch(
                novel_package=novel_package,
                story_memory=story_memory,
                chapter_number=chapter_number,
                scene=materialized_scene,
                chunk=chunk,
                previous_chunk_exit_state=previous_chunk_exit_state,
                previous_tail_segment=previous_tail_segment,
            )
            chunk_batches.append(chunk_contracts)
            previous_tail_segment = chunk_contracts.segments[-1]
            previous_chunk_exit_state = self._build_scene_chunk_exit_state(previous_tail_segment)
        return self._build_scene_plan_from_chunk_batches(
            novel_package=novel_package,
            scene=materialized_scene,
            chunk_batches=chunk_batches,
        )

    def _plan_scene_chunk_outline(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene: ChapterSceneSchema,
    ) -> SceneSegmentChunkPlanSchema:
        return self._run_structured_agent(
            schema=SceneSegmentChunkPlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是场景内分块规划 Agent。"
                    "请先把一个 scene 拆成更小的连续 chunk。"
                    "只输出短小的 chunk 大纲，不要输出 segments。"
                ),
                user_prompt=self._build_scene_chunk_planner_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                    story_memory=story_memory,
                    scene_payload=scene.model_dump(),
                ),
                metadata={
                    "task": "video-scene-chunk-planner",
                    "chapter_number": chapter_number,
                    "scene_id": scene.scene_id,
                },
            ),
            validator=lambda value, current_scene=scene: self._validate_scene_segment_chunk_output(
                value,
                scene=current_scene,
            ),
        )

    def _build_scene_chunk_contract_batch(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        previous_chunk_exit_state: dict[str, object] | None,
        previous_tail_segment: SceneSegmentContractSchema | None,
    ) -> SceneSegmentContractBatchSchema:
        task_metadata = {
            "task": "video-scene-segment-planner",
            "chapter_number": chapter_number,
            "scene_id": scene.scene_id,
            "chunk_id": chunk.chunk_id,
            "chunk_order_index": chunk.order_index,
        }
        retry_state = {
            "effective_expected_segment_count": int(chunk.expected_segment_count),
            "forced_min_segments": 0,
            "last_candidate": None,
        }

        def request_builder(
            *,
            request: PromptRequest,
            schema: type[StructuredModelT],
            attempt: int,
            last_error: Exception | None,
        ) -> PromptRequest:
            if isinstance(last_error, SegmentSpeechSplitRequiredError):
                retry_state["effective_expected_segment_count"] = min(
                    self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                    max(
                        int(retry_state["effective_expected_segment_count"]),
                        int(last_error.required_segment_count),
                    ),
                )
                retry_state["forced_min_segments"] = max(
                    int(retry_state["forced_min_segments"]),
                    int(last_error.required_segment_count),
                )
            base_request = PromptRequest(
                system_prompt=(
                    "你是场景内分段导演 Agent。"
                    "请只为目标 scene 的当前 chunk 生成可执行的 segment contracts。"
                    "不要输出图片 prompt，不要输出环境音与音乐方向。"
                ),
                user_prompt=self._build_scene_segment_contract_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                    story_memory=story_memory,
                    scene_payload=scene.model_dump(),
                    chunk_payload=chunk.model_dump(),
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    max_segments_override=int(retry_state["effective_expected_segment_count"]),
                    forced_min_segments=(
                        int(retry_state["forced_min_segments"]) or None
                    ),
                ),
                metadata={
                    **task_metadata,
                    "effective_expected_segment_count": int(
                        retry_state["effective_expected_segment_count"]
                    ),
                },
            )
            return self._build_retry_request(
                request=base_request,
                schema=schema,
                attempt=attempt,
                last_error=last_error,
            )

        def validate_chunk_candidate(
            value: SceneSegmentContractBatchSchema,
            *,
            current_scene: ChapterSceneSchema = scene,
            current_chunk: SceneSegmentChunkSchema = chunk,
            current_previous_tail: SceneSegmentContractSchema | None = previous_tail_segment,
        ) -> SceneSegmentContractBatchSchema:
            retry_state["last_candidate"] = value
            return self._validate_scene_chunk_contract_output(
                value,
                scene=current_scene,
                chunk=current_chunk,
                previous_tail_segment=current_previous_tail,
                effective_expected_segment_count=int(
                    retry_state["effective_expected_segment_count"]
                ),
            )

        try:
            chunk_contracts = self._execute_structured_request(
                schema=SceneSegmentContractBatchSchema,
                request=PromptRequest(
                    system_prompt="",
                    user_prompt="",
                    metadata=task_metadata,
                ),
                attempts=self.structured_retry_attempts,
                validator=validate_chunk_candidate,
                request_builder=request_builder,
                response_coercer=self._coerce_structured_response,
                failure_builder=lambda last_error: VideoStructuredGenerationError(
                    task=str(task_metadata.get("task", "video-scene-segment-planner")),
                    schema_name=SceneSegmentContractBatchSchema.__name__,
                    attempts=self.structured_retry_attempts,
                    cause=last_error or RuntimeError("unknown structured generation failure"),
                    metadata=dict(task_metadata),
                ),
            )
        except VideoStructuredGenerationError as exc:
            last_candidate = retry_state.get("last_candidate")
            if (
                isinstance(exc.cause, SegmentSpeechSplitRequiredError)
                and isinstance(last_candidate, SceneSegmentContractBatchSchema)
            ):
                effective_expected_segment_count = min(
                    self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                    max(
                        int(retry_state["effective_expected_segment_count"]),
                        int(exc.cause.required_segment_count),
                    ),
                )
                chunk_contracts = self._repair_scene_chunk_contract_batch_after_split_failure(
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter_number,
                    scene=scene,
                    chunk=chunk,
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    previous_tail_segment=previous_tail_segment,
                    failed_contracts=last_candidate,
                    split_error=exc.cause,
                    effective_expected_segment_count=effective_expected_segment_count,
                )
            else:
                raise
        return self._normalize_scene_chunk_contract_batch(
            scene=scene,
            chunk=chunk,
            contracts=chunk_contracts,
            previous_tail_segment=previous_tail_segment,
        )

    def _repair_scene_chunk_contract_batch_after_split_failure(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        previous_chunk_exit_state: dict[str, object] | None,
        previous_tail_segment: SceneSegmentContractSchema | None,
        failed_contracts: SceneSegmentContractBatchSchema,
        split_error: SegmentSpeechSplitRequiredError,
        effective_expected_segment_count: int,
    ) -> SceneSegmentContractBatchSchema:
        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的超长对白拆段修复 Agent。"
                "你只修复当前 chunk 里超出单段 12 秒上限的片段，"
                "把失败合同重写成可执行的正式 segment contracts。"
            ),
            user_prompt=self._build_scene_segment_overflow_repair_user_prompt(
                novel_package,
                chapter_number=chapter_number,
                story_memory=story_memory,
                scene_payload=scene.model_dump(),
                chunk_payload=chunk.model_dump(),
                previous_chunk_exit_state=previous_chunk_exit_state,
                failed_contract_payload=failed_contracts.model_dump(),
                offending_segment_id=split_error.segment_id,
                required_duration_seconds=split_error.required_duration_seconds,
                current_duration_seconds=split_error.current_duration_seconds,
                required_segment_count=split_error.required_segment_count,
                max_segments_override=effective_expected_segment_count,
            ),
            metadata={
                "task": "video-scene-segment-overflow-repair",
                "chapter_number": chapter_number,
                "scene_id": scene.scene_id,
                "chunk_id": chunk.chunk_id,
                "chunk_order_index": chunk.order_index,
            },
        )
        return self._run_strict_structured_agent(
            schema=SceneSegmentContractBatchSchema,
            request=request,
            validator=lambda value, current_scene=scene, current_chunk=chunk, current_previous_tail=previous_tail_segment, current_limit=effective_expected_segment_count: self._validate_scene_chunk_contract_output(
                value,
                scene=current_scene,
                chunk=current_chunk,
                previous_tail_segment=current_previous_tail,
                effective_expected_segment_count=current_limit,
            ),
            attempts=max(2, self.structured_retry_attempts),
        )

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

    def _validate_scene_segment_chunk_output(
        self,
        chunk_plan: SceneSegmentChunkPlanSchema,
        *,
        scene: ChapterSceneSchema,
    ) -> SceneSegmentChunkPlanSchema:
        if not chunk_plan.chunks:
            raise ValueError(f"scene {scene.scene_id} 没有产出任何 chunk。")
        if len(chunk_plan.chunks) > 4:
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk 数过多，最多允许 4 个，实际 {len(chunk_plan.chunks)} 个。"
            )
        seen_chunk_ids: set[str] = set()
        normalized_chunks: list[SceneSegmentChunkSchema] = []
        total_expected_segments = 0
        previous_chunk: SceneSegmentChunkSchema | None = None
        for order_index, chunk in enumerate(
            sorted(chunk_plan.chunks, key=lambda item: item.order_index),
            start=1,
        ):
            if chunk.chunk_id in seen_chunk_ids:
                raise ValueError(f"scene {scene.scene_id} 的 chunk_id 重复：{chunk.chunk_id}")
            seen_chunk_ids.add(chunk.chunk_id)
            if not chunk.title.strip() or not chunk.summary.strip():
                raise ValueError(f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 缺少 title 或 summary。")
            must_cover = [item for item in chunk.must_cover if item.strip()]
            if not must_cover:
                must_cover = [chunk.summary.strip()]
            normalized_chunk = chunk.model_copy(
                update={
                    "order_index": order_index,
                    "must_cover": must_cover[:3],
                }
            )
            if (
                previous_chunk is not None
                and self._scene_chunks_look_duplicate(previous_chunk, normalized_chunk)
            ):
                raise ValueError(
                    f"scene {scene.scene_id} 的相邻 chunk {previous_chunk.chunk_id} 与 "
                    f"{normalized_chunk.chunk_id} 重复表达同一事件，缺少明确推进。"
                )
            total_expected_segments += normalized_chunk.expected_segment_count
            normalized_chunks.append(normalized_chunk)
            previous_chunk = normalized_chunk
        if total_expected_segments > self.SCENE_MAX_EXPECTED_SEGMENTS:
            raise ValueError(
                f"scene {scene.scene_id} 预期共 {total_expected_segments} 个 segment，"
                f"超过 scene 上限 {self.SCENE_MAX_EXPECTED_SEGMENTS}。"
            )
        return chunk_plan.model_copy(
            update={
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "chunks": normalized_chunks,
            }
        )

    def _validate_scene_chunk_contract_output(
        self,
        contracts: SceneSegmentContractBatchSchema,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        previous_tail_segment: SceneSegmentContractSchema | None = None,
        effective_expected_segment_count: int | None = None,
    ) -> SceneSegmentContractBatchSchema:
        contracts = self._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
            allow_nonstart_first_segment=previous_tail_segment is not None,
        )
        segment_count = len(contracts.segments)
        if segment_count > self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS:
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 输出了 {segment_count} 个 segment，"
                f"超过单 chunk 上限 {self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS}。"
            )
        current_chunk_segment_limit = int(
            effective_expected_segment_count or chunk.expected_segment_count
        )
        max_allowed_segments = min(
            self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
            current_chunk_segment_limit,
        )
        if segment_count > max_allowed_segments:
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 预期 "
                f"{current_chunk_segment_limit} 个 segment，实际输出 {segment_count} 个，"
                "超过当前 chunk 的执行上限。"
            )
        if previous_tail_segment is not None:
            first_segment = contracts.segments[0]
            first_transition_mode = first_segment.continuity_link.transition_mode.strip().lower()
            if first_transition_mode not in {"continue", "cut"}:
                raise ValueError(
                    f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 首段必须承接上一 chunk，"
                    "transition_mode 只能是 continue 或 cut。"
                )
            if first_transition_mode == "continue":
                previous_end_state = (
                    previous_tail_segment.shot_state.end_state_lock.strip()
                    or previous_tail_segment.shot_state.action_progression.strip()
                    or previous_tail_segment.summary.strip()
                )
                opening_overlap = _text_overlap_ratio(
                    first_segment.continuity_link.opening_match.strip(),
                    previous_end_state,
                )
                if opening_overlap < 0.22:
                    raise ValueError(
                        f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 首段 opening_match "
                        "没有明确承接上一 chunk 尾部状态。"
                    )
        previous_segment: SceneSegmentContractSchema | None = None
        for segment in contracts.segments:
            if (
                previous_segment is not None
                and self._scene_chunk_segments_look_duplicate(previous_segment, segment)
            ):
                raise ValueError(
                    f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 中，"
                    f"相邻 segment {previous_segment.segment_id} 与 {segment.segment_id} "
                    "重复表达同一事件，缺少动作推进。"
                )
            previous_segment = segment
        return contracts.model_copy(
            update={
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
            }
        )

    def _scene_chunks_look_duplicate(
        self,
        previous_chunk: SceneSegmentChunkSchema,
        current_chunk: SceneSegmentChunkSchema,
    ) -> bool:
        previous_signature = " ".join(
            [
                previous_chunk.title,
                previous_chunk.summary,
                " ".join(previous_chunk.must_cover),
                previous_chunk.transition_goal,
            ]
        )
        current_signature = " ".join(
            [
                current_chunk.title,
                current_chunk.summary,
                " ".join(current_chunk.must_cover),
                current_chunk.transition_goal,
            ]
        )
        signature_overlap = _text_overlap_ratio(previous_signature, current_signature)
        summary_overlap = _text_overlap_ratio(previous_chunk.summary, current_chunk.summary)
        must_cover_overlap = _text_overlap_ratio(
            " ".join(previous_chunk.must_cover),
            " ".join(current_chunk.must_cover),
        )
        new_signal_count = _text_new_signal_count(previous_signature, current_signature)
        transition_overlap = _text_overlap_ratio(
            previous_chunk.transition_goal,
            current_chunk.transition_goal,
        )
        return (
            (
                signature_overlap >= 0.78
                and summary_overlap >= 0.74
                and must_cover_overlap >= 0.7
                and new_signal_count <= 2
                and (
                    transition_overlap >= 0.55
                    or _progress_text_too_generic(current_chunk.transition_goal)
                )
            )
            or (
                summary_overlap >= 0.45
                and must_cover_overlap >= 0.28
                and (
                    not (
                        _extract_progression_signal_terms(current_signature)
                        - _extract_progression_signal_terms(previous_signature)
                    )
                    or _text_explicitly_stalled(current_signature)
                )
                and _progress_text_too_generic(current_chunk.transition_goal)
            )
        )

    def _scene_chunk_segments_look_duplicate(
        self,
        previous_segment: SceneSegmentContractSchema,
        current_segment: SceneSegmentContractSchema,
    ) -> bool:
        previous_action = (
            previous_segment.shot_state.action_progression.strip()
            or previous_segment.summary.strip()
        )
        current_action = (
            current_segment.shot_state.action_progression.strip()
            or current_segment.summary.strip()
        )
        previous_signature = " ".join(
            [
                previous_segment.title,
                previous_segment.summary,
                previous_action,
                " ".join(previous_segment.timed_beats),
            ]
        )
        current_signature = " ".join(
            [
                current_segment.title,
                current_segment.summary,
                current_action,
                " ".join(current_segment.timed_beats),
            ]
        )
        summary_overlap = _text_overlap_ratio(previous_segment.summary, current_segment.summary)
        action_overlap = _text_overlap_ratio(previous_action, current_action)
        beats_overlap = _text_overlap_ratio(
            " ".join(previous_segment.timed_beats),
            " ".join(current_segment.timed_beats),
        )
        signature_overlap = _text_overlap_ratio(previous_signature, current_signature)
        new_signal_count = _text_new_signal_count(previous_signature, current_signature)
        allowed_changes = current_segment.continuity_link.allowed_changes.strip()
        return (
            (
                summary_overlap >= 0.74
                and action_overlap >= 0.74
                and signature_overlap >= 0.78
                and beats_overlap >= 0.62
                and new_signal_count <= 2
                and (
                    not allowed_changes
                    or _progress_text_too_generic(allowed_changes)
                    or _text_overlap_ratio(previous_action, allowed_changes) >= 0.72
                )
            )
            or (
                summary_overlap >= 0.45
                and action_overlap >= 0.3
                and beats_overlap >= 0.45
                and (
                    not (
                        _extract_progression_signal_terms(current_signature)
                        - _extract_progression_signal_terms(previous_signature)
                    )
                    or _text_explicitly_stalled(current_signature)
                )
                and (
                    not allowed_changes
                    or _progress_text_too_generic(allowed_changes)
                    or _text_explicitly_stalled(allowed_changes)
                )
            )
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
        return {
            "segment_id": tail_segment.segment_id,
            "summary": tail_segment.summary,
            "end_frame_characters": list(tail_segment.end_frame_characters),
            "end_state_lock": tail_segment.shot_state.end_state_lock,
            "screen_direction": tail_segment.shot_state.screen_direction,
            "transition_mode": tail_segment.continuity_link.transition_mode,
        }

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

    def _validate_chapter_scene_structure_output(
        self,
        structure: ChapterSceneStructureSchema,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> ChapterSceneStructureSchema:
        if not structure.scenes:
            raise ValueError("ChapterSceneStructureSchema.scenes 不能为空。")
        seen_scene_ids: set[str] = set()
        for scene in structure.scenes:
            if scene.chapter_number != chapter_number:
                raise ValueError(
                    f"scene {scene.scene_id} 的 chapter_number 必须为 {chapter_number}。"
                )
            if not scene.scene_id.strip():
                raise ValueError("scene_id 不能为空。")
            if scene.scene_id in seen_scene_ids:
                raise ValueError(f"scene_id 重复：{scene.scene_id}")
            seen_scene_ids.add(scene.scene_id)
            if not scene.title.strip() or not scene.summary.strip():
                raise ValueError(f"scene {scene.scene_id} 缺少 title 或 summary。")
        return structure

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

    def _validate_scene_segment_contract_output(
        self,
        contracts: SceneSegmentContractBatchSchema,
        *,
        scene: ChapterSceneSchema,
        allow_nonstart_first_segment: bool = False,
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
            if not segment.timed_beats:
                raise ValueError(f"segment {segment.segment_id} 缺少 timed_beats。")
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
            if effective_requires_mid_frame and not segment.requires_mid_frame:
                raise ValueError(
                    f"segment {segment.segment_id} 满足中段锚点帧条件时，"
                    "requires_mid_frame 必须为 true，且必须显式给出 mid_frame_characters。"
                )
            if effective_requires_mid_frame and not segment.mid_frame_characters:
                raise ValueError(
                    f"segment {segment.segment_id} 的 mid_frame_characters 不能为空，"
                    "且只能使用 involved_characters 内角色。"
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
            if not segment.continuity_link.opening_match.strip():
                raise ValueError(f"segment {segment.segment_id} 缺少 continuity_link.opening_match。")
            opening_match = segment.continuity_link.opening_match.strip()
            if any(phrase in opening_match for phrase in GENERIC_OPENING_MATCH_PHRASES):
                raise ValueError(
                    f"segment {segment.segment_id} 的 continuity_link.opening_match 过于空泛，"
                    "必须写出可拍到的开场状态。"
                )
            if transition_mode == "start" and "承接上一段" in opening_match:
                raise ValueError(
                    f"segment {segment.segment_id} 作为起始段时，"
                    "continuity_link.opening_match 不能写成上一段承接话术。"
                )
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
                    raise ValueError(
                        f"segment {segment.segment_id} 的 continuity_link.opening_match "
                        "没有明确承接上一段尾部状态。"
                    )
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
        subtitle_lines = contract.subtitle_lines or self._build_subtitle_lines(
            narration=contract.narration,
            dialogue_lines=contract.dialogue_lines,
            timed_beats=timed_beats,
        )
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=involved_characters,
            duration_seconds=contract.duration_seconds,
            dialogue_lines=contract.dialogue_lines,
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
                "end_frame_characters": end_frame_characters,
                "narration": contract.narration or contract.summary,
                "dialogue_lines": list(contract.dialogue_lines),
                "subtitle_lines": subtitle_lines,
                "timed_beats": timed_beats,
                "sound_effects": self._build_local_sound_effects(scene.scene_bible, timed_beats),
                "music_direction": self._build_local_music_direction(
                    novel_package=novel_package,
                    scene=scene,
                    segment_summary=contract.summary,
                ),
                "scene_prompt": "",
                "start_frame_prompt": "",
                "mid_frame_prompt": "",
                "end_frame_prompt": "",
                "duration_seconds": contract.duration_seconds,
                "requires_mid_frame": requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(contract.transition_hint),
            }
        )
        scene_prompt = self._build_local_scene_prompt(scene, base_segment)
        start_frame_prompt = self._build_local_start_frame_prompt(scene, base_segment)
        end_frame_prompt = self._build_local_end_frame_prompt(scene, base_segment)
        enriched_segment = base_segment.model_copy(
            update={
                "scene_prompt": scene_prompt,
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

    def _build_local_scene_prompt(
        self,
        scene: ChapterSceneSchema,
        segment: VideoSegmentSchema,
    ) -> str:
        beat_descriptions = self._extract_beat_descriptions(segment.timed_beats)
        focus = "；".join(beat_descriptions[:2]) or segment.summary
        characters = "、".join(segment.involved_characters) or "环境"
        return (
            f"{scene.title}，{focus}，角色 {characters}。"
            f"场景基线：{self._scene_bible_brief(scene.scene_bible)}。"
            f"镜头重点：{self._shot_state_brief(segment.shot_state)}。"
        )

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
        return f"首帧，{characters} 开场进入 {scene.title}，{opening_focus}。"

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
        return f"尾帧，{characters} 在 {scene.title} 收束到 {closing_focus}。"

    def _build_local_sound_effects(
        self,
        scene_bible,
        timed_beats: list[str],
    ) -> list[str]:
        effects: list[str] = []
        weather = self._scene_bible_value(scene_bible, "weather").strip()
        if weather:
            effects.append(f"{weather}环境声")
        fixed_props = self._scene_bible_list(scene_bible, "fixed_props")
        if fixed_props:
            effects.append(f"{fixed_props[0]}相关细节声")
        beat_text = " ".join(timed_beats)
        if any(keyword in beat_text for keyword in ("走", "跑", "靠近", "停下", "转身", "拥抱")):
            effects.append("脚步与衣料摩擦声")
        if not effects:
            effects.append("环境底噪")
        return effects[:3]

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
                    role=item.role,
                    gender=item.gender,
                    appearance=item.appearance,
                    outfit=item.outfit,
                    source_prompt=item.portrait_prompt,
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
                sound_effects=item.sound_effects,
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                scene_prompt=item.scene_prompt,
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
        if "mid_frame_characters 不能为空" in normalized_error or "只能使用 involved_characters 内角色" in normalized_error:
            retry_note += (
                " 这次失败说明中段出镜角色写错了。"
                "mid_frame_characters 必须严格跟随片段中间那一拍真实出镜的人物，"
                "不要直接照搬整个 scene cast，也不要把只在尾帧才出现的人提前写进中段帧。"
            )
        if "缺少 continuity_link.opening_match" in normalized_error or "opening_match 过于空泛" in normalized_error:
            retry_note += (
                " 这次失败说明 opening_match 不合格。"
                "无论是 start 还是 continue，opening_match 都必须写成可拍到的开场状态，"
                "不要留空，也不要写“承接上一段继续”“场景开始”这类空话。"
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
            fields_to_check = [
                segment.summary,
                segment.narration,
                segment.scene_prompt,
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
            if not candidate.mid_frame_prompt.strip():
                raise ValueError("requires_mid_frame=true 时 mid_frame_prompt 不能为空。")
            if not candidate.mid_frame_characters:
                raise ValueError("requires_mid_frame=true 时 mid_frame_characters 不能为空。")

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

        if not candidate.timed_beats:
            raise ValueError("timed_beats 不能为空。")
        max_end_seconds = 0.0
        parsed_any = False
        for beat in candidate.timed_beats:
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
                f"timed_beats 最后结束时间 {max_end_seconds:g}s 超过当前片段时长 {duration_seconds}s。"
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
                "scene_prompt": repair_patch.scene_prompt.strip(),
                "start_frame_prompt": repair_patch.start_frame_prompt.strip(),
                "mid_frame_prompt": repair_patch.mid_frame_prompt.strip(),
                "end_frame_prompt": repair_patch.end_frame_prompt.strip(),
                "start_frame_characters": list(repair_patch.start_frame_characters),
                "mid_frame_characters": list(repair_patch.mid_frame_characters),
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
            "scene_prompt",
            "start_frame_prompt",
            "mid_frame_prompt",
            "end_frame_prompt",
            "start_frame_characters",
            "mid_frame_characters",
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
