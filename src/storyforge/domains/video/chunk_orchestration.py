from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import PromptRequest
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.errors import (
    SegmentActionSplitRequiredError,
    SegmentSpeechSplitRequiredError,
    VideoStructuredGenerationError,
)
from storyforge.domains.video.schemas import (
    ChapterSceneSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentChunkSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    VideoSegmentPlanSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class VideoSceneChunkOrchestrationMixin:
    """Orchestrates scene chunk planning and targeted segment-contract repairs."""

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
            validator=lambda value, current_scene=scene, current_story_memory=story_memory, current_chapter_number=chapter_number: self._validate_or_repair_scene_chunk_plan(
                value,
                novel_package=novel_package,
                story_memory=current_story_memory,
                chapter_number=current_chapter_number,
                scene=current_scene,
            ),
        )

    def _validate_or_repair_scene_chunk_plan(
        self,
        chunk_plan: SceneSegmentChunkPlanSchema,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene: ChapterSceneSchema,
    ) -> SceneSegmentChunkPlanSchema:
        try:
            return self._validate_scene_segment_chunk_output(
                chunk_plan,
                scene=scene,
            )
        except ValueError as exc:
            if self._should_repair_scene_chunk_plan(exc):
                try:
                    repaired_plan = self._repair_scene_chunk_plan_after_validation_failure(
                        chunk_plan=chunk_plan,
                        novel_package=novel_package,
                        story_memory=story_memory,
                        chapter_number=chapter_number,
                        scene=scene,
                        failure=exc,
                    )
                    return self._validate_scene_segment_chunk_output(
                        repaired_plan,
                        scene=scene,
                    )
                except Exception as repair_exc:
                    soften_failure = (
                        repair_exc
                        if self._should_soften_scene_chunk_plan_validation(repair_exc)
                        else exc
                    )
                    softened_plan = self._soft_accept_scene_chunk_plan(
                        repaired_plan if "repaired_plan" in locals() else chunk_plan,
                        scene=scene,
                        chapter_number=chapter_number,
                        failure=soften_failure,
                    )
                    if softened_plan is not None:
                        return softened_plan
                    raise
            softened_plan = self._soft_accept_scene_chunk_plan(
                chunk_plan,
                scene=scene,
                chapter_number=chapter_number,
                failure=exc,
            )
            if softened_plan is not None:
                return softened_plan
            raise

    def _should_repair_scene_chunk_plan(self, error: Exception) -> bool:
        normalized_error = str(error or "")
        return (
            "chunk" in normalized_error
            and "动作容量过载" in normalized_error
            and "expected_segment_count 至少应为" in normalized_error
        )

    def _repair_scene_chunk_plan_after_validation_failure(
        self,
        *,
        chunk_plan: SceneSegmentChunkPlanSchema,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
        scene: ChapterSceneSchema,
        failure: Exception,
    ) -> SceneSegmentChunkPlanSchema:
        failure_message = str(failure or "").strip()
        offending_chunk_id = ""
        required_segment_count: int | None = None
        chunk_match = re.search(r"chunk\s+(\S+)\s+动作容量过载", failure_message)
        if chunk_match is not None:
            offending_chunk_id = str(chunk_match.group(1) or "").strip()
        segment_count_match = re.search(r"expected_segment_count 至少应为\s+(\d+)", failure_message)
        if segment_count_match is not None:
            required_segment_count = int(segment_count_match.group(1))
        return self._run_strict_structured_agent(
            schema=SceneSegmentChunkPlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是 StoryForge 的 Scene Chunk Repair Agent。"
                    "你只修复失败的 chunk 大纲，不生成 segment，不输出解释。"
                ),
                user_prompt=self._build_scene_chunk_repair_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                    story_memory=story_memory,
                    scene_payload=scene.model_dump(),
                    invalid_plan=chunk_plan,
                    failure_message=failure_message,
                    offending_chunk_id=offending_chunk_id,
                    required_segment_count=required_segment_count,
                ),
                metadata={
                    "task": "video-scene-chunk-repair",
                    "chapter_number": chapter_number,
                    "scene_id": scene.scene_id,
                    "offending_chunk_id": offending_chunk_id,
                    "required_segment_count": int(required_segment_count or 0),
                },
            ),
            validator=lambda value, current_scene=scene: self._validate_scene_segment_chunk_output(
                value,
                scene=current_scene,
            ),
            attempts=max(2, self.structured_retry_attempts),
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
            if isinstance(last_error, (SegmentSpeechSplitRequiredError, SegmentActionSplitRequiredError)):
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
            elif (
                isinstance(exc.cause, SegmentActionSplitRequiredError)
                and isinstance(last_candidate, SceneSegmentContractBatchSchema)
            ):
                effective_expected_segment_count = min(
                    self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                    max(
                        int(retry_state["effective_expected_segment_count"]),
                        int(exc.cause.required_segment_count),
                    ),
                )
                chunk_contracts = self._repair_scene_chunk_contract_batch_after_action_failure(
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
            elif (
                isinstance(last_candidate, SceneSegmentContractBatchSchema)
                and self._should_repair_scene_chunk_contract_batch_after_timeline_failure(
                    exc.cause
                )
            ):
                chunk_contracts = self._repair_scene_chunk_contract_batch_after_timeline_failure(
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter_number,
                    scene=scene,
                    chunk=chunk,
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    previous_tail_segment=previous_tail_segment,
                    failed_contracts=last_candidate,
                    failure=exc.cause,
                    effective_expected_segment_count=int(
                        retry_state["effective_expected_segment_count"]
                    ),
                )
            elif (
                isinstance(last_candidate, SceneSegmentContractBatchSchema)
                and self._should_repair_scene_chunk_contract_batch_after_focus_conflict_failure(
                    exc.cause
                )
            ):
                chunk_contracts = self._repair_scene_chunk_contract_batch_after_focus_conflict_failure(
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter_number,
                    scene=scene,
                    chunk=chunk,
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    previous_tail_segment=previous_tail_segment,
                    failed_contracts=last_candidate,
                    failure=exc.cause,
                    effective_expected_segment_count=int(
                        retry_state["effective_expected_segment_count"]
                    ),
                )
            else:
                if isinstance(last_candidate, SceneSegmentContractBatchSchema):
                    softened_contracts = self._soft_accept_scene_chunk_contract_batch(
                        last_candidate,
                        scene=scene,
                        chunk=chunk,
                        previous_tail_segment=previous_tail_segment,
                        effective_expected_segment_count=int(
                            retry_state["effective_expected_segment_count"]
                        ),
                        failure=exc.cause,
                    )
                    if softened_contracts is not None:
                        chunk_contracts = softened_contracts
                    else:
                        raise
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
        retry_state: dict[str, object] = {"last_candidate": None}

        def validate_timeline_candidate(
            value: SceneSegmentContractBatchSchema,
            *,
            current_scene: ChapterSceneSchema = scene,
            current_chunk: SceneSegmentChunkSchema = chunk,
            current_previous_tail: SceneSegmentContractSchema | None = previous_tail_segment,
            current_limit: int = effective_expected_segment_count,
        ) -> SceneSegmentContractBatchSchema:
            retry_state["last_candidate"] = value
            return self._validate_scene_chunk_contract_output(
                value,
                scene=current_scene,
                chunk=current_chunk,
                previous_tail_segment=current_previous_tail,
                effective_expected_segment_count=current_limit,
            )

        try:
            return self._run_strict_structured_agent(
                schema=SceneSegmentContractBatchSchema,
                request=request,
                validator=validate_timeline_candidate,
                attempts=max(2, self.structured_retry_attempts),
            )
        except VideoStructuredGenerationError as exc:
            last_candidate = retry_state.get("last_candidate")
            if (
                isinstance(exc.cause, SegmentActionSplitRequiredError)
                and isinstance(last_candidate, SceneSegmentContractBatchSchema)
            ):
                next_limit = min(
                    self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                    max(
                        int(effective_expected_segment_count),
                        int(exc.cause.required_segment_count),
                    ),
                )
                return self._repair_scene_chunk_contract_batch_after_action_failure(
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter_number,
                    scene=scene,
                    chunk=chunk,
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    previous_tail_segment=previous_tail_segment,
                    failed_contracts=last_candidate,
                    split_error=exc.cause,
                    effective_expected_segment_count=next_limit,
                )
            raise

    def _repair_scene_chunk_contract_batch_after_action_failure(
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
        split_error: SegmentActionSplitRequiredError,
        effective_expected_segment_count: int,
    ) -> SceneSegmentContractBatchSchema:
        current_failed_contracts = failed_contracts
        current_split_error = split_error
        current_limit = min(
            self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
            max(
                int(effective_expected_segment_count),
                int(split_error.required_segment_count),
            ),
        )
        total_attempts = max(2, self.structured_retry_attempts)
        max_repair_rounds = max(2, min(8, len(current_failed_contracts.segments) + 2))
        last_failure: VideoStructuredGenerationError | None = None
        next_round_attempts = total_attempts

        for _ in range(max_repair_rounds):
            round_attempts = next_round_attempts
            next_round_attempts = total_attempts
            retry_state: dict[str, object] = {"last_candidate": None}
            task_metadata = {
                "task": "video-scene-segment-action-repair",
                "chapter_number": chapter_number,
                "scene_id": scene.scene_id,
                "chunk_id": chunk.chunk_id,
                "chunk_order_index": chunk.order_index,
                "offending_segment_id": current_split_error.segment_id,
                "required_segment_count": current_split_error.required_segment_count,
            }

            def request_builder(
                *,
                request: PromptRequest,
                schema: type[StructuredModelT],
                attempt: int,
                last_error: Exception | None,
            ) -> PromptRequest:
                base_request = PromptRequest(
                    system_prompt=(
                        "你是 StoryForge 的动作拆段修复 Agent。"
                        "你只修复当前 chunk 里动作容量超载的片段，"
                        "把失败合同重写成可执行的正式 segment contracts。"
                    ),
                    user_prompt=self._build_scene_segment_action_repair_user_prompt(
                        novel_package,
                        chapter_number=chapter_number,
                        story_memory=story_memory,
                        scene_payload=scene.model_dump(),
                        chunk_payload=chunk.model_dump(),
                        previous_chunk_exit_state=previous_chunk_exit_state,
                        failed_contract_payload=current_failed_contracts.model_dump(),
                        offending_segment_id=current_split_error.segment_id,
                        action_node_count=current_split_error.action_node_count,
                        current_duration_seconds=current_split_error.current_duration_seconds,
                        max_action_nodes=current_split_error.max_action_nodes,
                        required_segment_count=current_split_error.required_segment_count,
                        max_segments_override=current_limit,
                    ),
                    metadata=dict(task_metadata),
                )
                return self._build_repair_retry_request(
                    request=base_request,
                    schema=schema,
                    attempt=attempt,
                    last_error=last_error,
                )

            def validate_action_candidate(
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
                    effective_expected_segment_count=current_limit,
                )

            try:
                return self._execute_structured_request(
                    schema=SceneSegmentContractBatchSchema,
                    request=PromptRequest(
                        system_prompt="",
                        user_prompt="",
                        metadata=dict(task_metadata),
                    ),
                    attempts=round_attempts,
                    validator=validate_action_candidate,
                    request_builder=request_builder,
                    response_coercer=self._validate_structured_response,
                    failure_builder=lambda last_error, task_metadata=task_metadata: VideoStructuredGenerationError(
                        task=str(task_metadata.get("task", "video-scene-segment-action-repair")),
                        schema_name=SceneSegmentContractBatchSchema.__name__,
                        attempts=round_attempts,
                        cause=last_error or RuntimeError("unknown structured generation failure"),
                        metadata=dict(task_metadata),
                    ),
                )
            except VideoStructuredGenerationError as exc:
                last_failure = exc
                last_candidate = retry_state.get("last_candidate")
                normalized_error = " ".join(str(exc.cause or "").split()).strip()
                if isinstance(last_candidate, SceneSegmentContractBatchSchema):
                    count_match = re.search(
                        r"预期\s+(?P<expected>\d+)\s+个 segment，实际输出\s+(?P<actual>\d+)\s+个",
                        normalized_error,
                    )
                    if count_match is not None:
                        next_limit = min(
                            self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                            max(
                                int(current_limit),
                                int(count_match.group("actual")),
                            ),
                        )
                        if (
                            last_candidate.model_dump() == current_failed_contracts.model_dump()
                            and next_limit == current_limit
                        ):
                            break
                        current_failed_contracts = last_candidate
                        current_limit = next_limit
                        next_round_attempts = 1
                        continue
                    if self._should_repair_scene_chunk_contract_batch_after_focus_conflict_failure(exc.cause):
                        return self._repair_scene_chunk_contract_batch_after_focus_conflict_failure(
                            novel_package=novel_package,
                            story_memory=story_memory,
                            chapter_number=chapter_number,
                            scene=scene,
                            chunk=chunk,
                            previous_chunk_exit_state=previous_chunk_exit_state,
                            previous_tail_segment=previous_tail_segment,
                            failed_contracts=last_candidate,
                            failure=exc.cause,
                            effective_expected_segment_count=current_limit,
                        )
                    if self._should_soften_scene_chunk_contract_validation(exc.cause):
                        next_limit = min(
                            self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                            max(int(current_limit), len(last_candidate.segments)),
                        )
                        if last_candidate.model_dump() != current_failed_contracts.model_dump():
                            current_failed_contracts = last_candidate
                            current_limit = next_limit
                            next_round_attempts = 1
                            continue
                        softened_contracts = self._soft_accept_scene_chunk_contract_batch(
                            last_candidate,
                            scene=scene,
                            chunk=chunk,
                            previous_tail_segment=previous_tail_segment,
                            effective_expected_segment_count=next_limit,
                            failure=exc.cause,
                        )
                        if softened_contracts is not None:
                            return softened_contracts
                if not (
                    isinstance(exc.cause, SegmentActionSplitRequiredError)
                    and isinstance(last_candidate, SceneSegmentContractBatchSchema)
                ):
                    raise RuntimeError(
                        "Structured repair failed for task=video-scene-segment-action-repair "
                        f"schema={SceneSegmentContractBatchSchema.__name__} "
                        f"after {total_attempts} attempts: {exc.cause or 'unknown error'}"
                    ) from exc
                next_limit = min(
                    self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS,
                    max(
                        int(current_limit),
                        int(exc.cause.required_segment_count),
                    ),
                )
                if (
                    last_candidate.model_dump() == current_failed_contracts.model_dump()
                    and next_limit == current_limit
                ):
                    break
                current_failed_contracts = last_candidate
                current_split_error = exc.cause
                current_limit = next_limit

        raise RuntimeError(
            "Structured repair failed for task=video-scene-segment-action-repair "
            f"schema={SceneSegmentContractBatchSchema.__name__} "
            f"after {total_attempts} attempts: "
            f"{(last_failure.cause if last_failure is not None else split_error) or 'unknown error'}"
        )

    def _should_repair_scene_chunk_contract_batch_after_timeline_failure(
        self,
        error: Exception | None,
    ) -> bool:
        normalized_error = " ".join(str(error or "").split()).strip()
        return (
            "timed_beats" in normalized_error
            and "尾部约" in normalized_error
            and "缺少明确动作或收束节拍" in normalized_error
        )

    def _repair_scene_chunk_contract_batch_after_timeline_failure(
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
        failure: Exception,
        effective_expected_segment_count: int,
    ) -> SceneSegmentContractBatchSchema:
        failure_message = " ".join(str(failure or "").split()).strip()
        offending_segment_id = ""
        segment_match = re.search(
            r"segment\s+(?P<segment_id>\S+)\s+的\s+timed_beats",
            failure_message,
        )
        if segment_match is not None:
            offending_segment_id = str(segment_match.group("segment_id") or "").strip()
        timeline_match = re.search(
            r"timed_beats\s+最后结束时间\s+"
            r"(?P<max_end>\d+(?:\.\d+)?)s\s+早于当前片段时长\s+"
            r"(?P<duration>\d+(?:\.\d+)?)s，尾部约\s+"
            r"(?P<uncovered>\d+(?:\.\d+)?)s",
            failure_message,
        )
        max_end_seconds = None
        duration_seconds = None
        uncovered_seconds = None
        if timeline_match is not None:
            max_end_seconds = float(timeline_match.group("max_end"))
            duration_seconds = float(timeline_match.group("duration"))
            uncovered_seconds = float(timeline_match.group("uncovered"))
        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的 segment timeline repair Agent。"
                "你只修复当前 chunk 里 timed_beats 时间覆盖不完整的片段，"
                "不要重写无关剧情。"
            ),
            user_prompt=self._build_scene_segment_timeline_repair_user_prompt(
                novel_package,
                chapter_number=chapter_number,
                story_memory=story_memory,
                scene_payload=scene.model_dump(),
                chunk_payload=chunk.model_dump(),
                previous_chunk_exit_state=previous_chunk_exit_state,
                failed_contract_payload=failed_contracts.model_dump(),
                failure_message=failure_message,
                offending_segment_id=offending_segment_id,
                max_end_seconds=max_end_seconds,
                duration_seconds=duration_seconds,
                uncovered_seconds=uncovered_seconds,
                max_segments_override=effective_expected_segment_count,
            ),
            metadata={
                "task": "video-scene-segment-timeline-repair",
                "chapter_number": chapter_number,
                "scene_id": scene.scene_id,
                "chunk_id": chunk.chunk_id,
                "chunk_order_index": chunk.order_index,
                "offending_segment_id": offending_segment_id,
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

    def _should_repair_scene_chunk_contract_batch_after_focus_conflict_failure(
        self,
        error: Exception | None,
    ) -> bool:
        normalized_error = " ".join(str(error or "").split()).strip()
        return (
            "多人同帧时仍要求单人特写" in normalized_error
            and "单帧里重复出现" in normalized_error
        )

    def _parse_scene_segment_focus_conflict_failure(
        self,
        failure_message: str,
    ) -> dict[str, object]:
        normalized = " ".join(str(failure_message or "").split()).strip()
        match = re.search(
            r"segment\s+(?P<segment_id>\S+)\s+的\s+(?P<field_name>[^\s]+)\s+在\s+"
            r"(?P<frame_label>start_frame|mid_frame|end_frame)\s*"
            r"\((?P<frame_names>[^)]+)\)\s*多人同帧时仍要求单人特写",
            normalized,
        )
        if match is None:
            return {
                "segment_id": "",
                "field_name": "",
                "frame_label": "",
                "frame_characters": [],
            }
        frame_names = [
            item.strip()
            for item in re.split(r"[、,，]", str(match.group("frame_names") or ""))
            if item.strip()
        ]
        return {
            "segment_id": str(match.group("segment_id") or "").strip(),
            "field_name": str(match.group("field_name") or "").strip(),
            "frame_label": str(match.group("frame_label") or "").strip(),
            "frame_characters": frame_names,
        }

    def _repair_scene_chunk_contract_batch_after_focus_conflict_failure(
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
        failure: Exception,
        effective_expected_segment_count: int,
    ) -> SceneSegmentContractBatchSchema:
        failure_message = " ".join(str(failure or "").split()).strip()
        parsed = self._parse_scene_segment_focus_conflict_failure(failure_message)
        offending_segment_id = str(parsed.get("segment_id", "") or "").strip()
        field_name = str(parsed.get("field_name", "") or "").strip()
        frame_label = str(parsed.get("frame_label", "") or "").strip()
        frame_characters = list(parsed.get("frame_characters", []) or [])
        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的多人同帧镜头冲突修复 Agent。"
                "你只修复当前 chunk 里多人同帧却仍要求单人特写的 segment，"
                "不要重写无关剧情。"
            ),
            user_prompt=self._build_scene_segment_focus_repair_user_prompt(
                novel_package,
                chapter_number=chapter_number,
                story_memory=story_memory,
                scene_payload=scene.model_dump(),
                chunk_payload=chunk.model_dump(),
                previous_chunk_exit_state=previous_chunk_exit_state,
                failed_contract_payload=failed_contracts.model_dump(),
                failure_message=failure_message,
                offending_segment_id=offending_segment_id,
                field_name=field_name,
                frame_label=frame_label,
                frame_characters=frame_characters,
                max_segments_override=effective_expected_segment_count,
            ),
            metadata={
                "task": "video-scene-segment-focus-repair",
                "chapter_number": chapter_number,
                "scene_id": scene.scene_id,
                "chunk_id": chunk.chunk_id,
                "chunk_order_index": chunk.order_index,
                "offending_segment_id": offending_segment_id,
                "field_name": field_name,
                "frame_label": frame_label,
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
