from __future__ import annotations

import re

from storyforge.agents.base import PromptRequest
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import (
    ChapterCoveragePlanSchema,
    ChapterCoverageEventSplitPlanSchema,
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    VideoSegmentPlanSchema,
)


class VideoChapterOrchestrationMixin:
    """Orchestrates chapter-level event/scene planning and scene expansion."""

    def _plan_chapter_scene_structure(
        self,
        *,
        novel_package: NovelPackage,
        story_memory,
        chapter_number: int,
    ) -> ChapterSceneStructureSchema:
        chapter_event_plan = self._run_structured_agent(
            schema=ChapterCoveragePlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是章节关键事件提取 Agent。"
                    "请只提取当前章节里后续场景规划必须覆盖的关键推进事件。"
                    "不要生成 scene，不要生成 segment，不要生成图片 prompt。"
                ),
                user_prompt=self._build_chapter_event_coverage_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                ),
                metadata={
                    "task": "video-chapter-event-planner",
                    "chapter_number": chapter_number,
                },
            ),
            validator=lambda value, chapter_number=chapter_number: self._validate_or_repair_chapter_event_plan(
                value,
                novel_package=novel_package,
                chapter_number=chapter_number,
            ),
        )
        return self._run_structured_agent(
            schema=ChapterSceneStructureSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是章节场景规划 Agent。"
                    "请只规划当前章节有哪些 scene。"
                    "只输出 scene 结构，不要输出 segment，不要输出图片 prompt。"
                ),
                user_prompt=self._build_chapter_scene_planner_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                    story_memory=story_memory,
                    chapter_event_plan=chapter_event_plan,
                ),
                metadata={
                    "task": "video-chapter-scene-planner",
                    "chapter_number": chapter_number,
                },
            ),
            validator=lambda value, chapter_number=chapter_number, chapter_event_plan=chapter_event_plan: self._validate_chapter_scene_structure_output(
                value,
                novel_package=novel_package,
                chapter_number=chapter_number,
                chapter_event_plan=chapter_event_plan,
            ),
        )

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

    def _validate_or_repair_chapter_event_plan(
        self,
        chapter_event_plan: ChapterCoveragePlanSchema,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> ChapterCoveragePlanSchema:
        current_plan = chapter_event_plan
        max_repair_rounds = max(2, min(12, len(current_plan.events) + 2))
        for _ in range(max_repair_rounds):
            try:
                return self._validate_chapter_event_coverage_output(
                    current_plan,
                    novel_package=novel_package,
                    chapter_number=chapter_number,
                )
            except ValueError as exc:
                if not self._should_repair_chapter_event_plan(exc):
                    raise
                try:
                    repaired_plan = self._repair_chapter_event_plan_after_validation_failure(
                        chapter_event_plan=current_plan,
                        novel_package=novel_package,
                        chapter_number=chapter_number,
                        failure=exc,
                    )
                except Exception:
                    softened_plan = self._soft_accept_chapter_event_plan_after_capacity_failure(
                        current_plan,
                        novel_package=novel_package,
                        chapter_number=chapter_number,
                        failure=exc,
                    )
                    if softened_plan is not None:
                        return softened_plan
                    raise
                if repaired_plan.model_dump() == current_plan.model_dump():
                    softened_plan = self._soft_accept_chapter_event_plan_after_capacity_failure(
                        current_plan,
                        novel_package=novel_package,
                        chapter_number=chapter_number,
                        failure=exc,
                    )
                    if softened_plan is not None:
                        return softened_plan
                    raise RuntimeError(
                        "章节关键事件修复未产生新的事件规划，无法继续自动拆分粗事件。"
                    ) from exc
                current_plan = repaired_plan
        try:
            return self._validate_chapter_event_coverage_output(
                current_plan,
                novel_package=novel_package,
                chapter_number=chapter_number,
            )
        except ValueError as exc:
            softened_plan = self._soft_accept_chapter_event_plan_after_capacity_failure(
                current_plan,
                novel_package=novel_package,
                chapter_number=chapter_number,
                failure=exc,
            )
            if softened_plan is not None:
                return softened_plan
            raise

    def _soft_accept_chapter_event_plan_after_capacity_failure(
        self,
        chapter_event_plan: ChapterCoveragePlanSchema,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        failure: Exception,
    ) -> ChapterCoveragePlanSchema | None:
        if not self._should_repair_chapter_event_plan(failure):
            return None
        softened_plan = self._validate_chapter_event_coverage_output(
            chapter_event_plan,
            novel_package=novel_package,
            chapter_number=chapter_number,
            action_capacity_event_ids=set(),
        )
        for warning in self._collect_chapter_event_action_capacity_warnings(softened_plan):
            self._record_planner_warning(
                f"chapter {chapter_number}：{warning} 当前先允许继续规划，后续可再做事件拆分修复。"
            )
        return softened_plan

    def _should_repair_chapter_event_plan(self, error: Exception) -> bool:
        normalized_error = str(error or "")
        return (
            "关键事件" in normalized_error
            and "过于粗" in normalized_error
            and "推进点" in normalized_error
        )

    def _collect_chapter_event_action_capacity_warnings(
        self,
        chapter_event_plan: ChapterCoveragePlanSchema,
    ) -> list[str]:
        warnings: list[str] = []
        total_events = len(chapter_event_plan.events)
        for index, event in enumerate(chapter_event_plan.events, start=1):
            try:
                self._validate_chapter_event_action_capacity(
                    event,
                    event_index=index,
                    total_events=total_events,
                )
            except ValueError as exc:
                warnings.append(str(exc))
        return warnings

    def _repair_chapter_event_plan_after_validation_failure(
        self,
        *,
        chapter_event_plan: ChapterCoveragePlanSchema,
        novel_package: NovelPackage,
        chapter_number: int,
        failure: Exception,
    ) -> ChapterCoveragePlanSchema:
        failure_message = str(failure or "").strip()
        offending_event_id = ""

        match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", failure_message)
        if match is not None:
            offending_event_id = match.group(1).strip()
        try:
            return self._run_strict_structured_agent(
                schema=ChapterCoveragePlanSchema,
                request=PromptRequest(
                    system_prompt=(
                        "你是章节关键事件修复 Agent。"
                        "请只修复失败的 must-cover event 规划。"
                        "不要生成 scene，不要生成 segment，不要输出解释。"
                    ),
                    user_prompt=self._build_chapter_event_repair_user_prompt(
                        novel_package,
                        chapter_number=chapter_number,
                        invalid_plan=chapter_event_plan,
                        failure_message=failure_message,
                        offending_event_id=offending_event_id,
                    ),
                    metadata={
                        "task": "video-chapter-event-repair",
                        "chapter_number": chapter_number,
                        "offending_event_id": offending_event_id,
                    },
                ),
                validator=lambda value, chapter_number=chapter_number: self._validate_chapter_event_coverage_output(
                    value,
                    novel_package=novel_package,
                    chapter_number=chapter_number,
                ),
                attempts=max(2, self.structured_retry_attempts),
            )
        except RuntimeError as exc:
            if not self._should_split_chapter_event_after_repair_failure(exc):
                raise
            split_offending_event_id = self._extract_offending_chapter_event_id(str(exc)) or offending_event_id
            return self._split_chapter_event_after_repair_failure(
                chapter_event_plan=chapter_event_plan,
                novel_package=novel_package,
                chapter_number=chapter_number,
                failure_message=str(exc),
                offending_event_id=split_offending_event_id,
            )

    def _should_split_chapter_event_after_repair_failure(self, error: Exception) -> bool:
        normalized_error = str(error or "")
        return (
            "video-chapter-event-repair" in normalized_error
            and "关键事件" in normalized_error
            and "过于粗" in normalized_error
            and "推进点" in normalized_error
        )

    def _extract_offending_chapter_event_id(self, message: str) -> str:
        match = re.search(r"关键事件\s+(ch\d{2}-ev\d{2})", str(message or ""))
        if match is None:
            return ""
        return match.group(1).strip()

    def _split_chapter_event_after_repair_failure(
        self,
        *,
        chapter_event_plan: ChapterCoveragePlanSchema,
        novel_package: NovelPackage,
        chapter_number: int,
        failure_message: str,
        offending_event_id: str,
    ) -> ChapterCoveragePlanSchema:
        offending_index = next(
            (
                index
                for index, event in enumerate(chapter_event_plan.events)
                if event.event_id == offending_event_id
            ),
            -1,
        )
        if offending_index < 0:
            raise RuntimeError(
                f"无法在 chapter event plan 中定位需要拆分的事件：{offending_event_id or 'unknown'}"
            )
        split_plan = self._run_strict_structured_agent(
            schema=ChapterCoverageEventSplitPlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是章节关键事件拆分 Agent。"
                    "你只负责把一个过粗的 must-cover event 拆成更细的相邻 replacement events。"
                    "不要重写整章规划，不要生成 scene，不要生成 segment，不要输出解释。"
                ),
                user_prompt=self._build_chapter_event_split_repair_user_prompt(
                    novel_package,
                    chapter_number=chapter_number,
                    invalid_plan=chapter_event_plan,
                    offending_event_id=offending_event_id,
                    failure_message=failure_message,
                ),
                metadata={
                    "task": "video-chapter-event-split-repair",
                    "chapter_number": chapter_number,
                    "offending_event_id": offending_event_id,
                },
            ),
            validator=lambda value, chapter_number=chapter_number, offending_index=offending_index: self._validate_chapter_event_split_plan(
                value,
                chapter_event_plan=chapter_event_plan,
                novel_package=novel_package,
                chapter_number=chapter_number,
                offending_event_index=offending_index,
            ),
            attempts=max(2, self.structured_retry_attempts),
        )
        return self._merge_chapter_event_split_plan(
            chapter_event_plan=chapter_event_plan,
            split_plan=split_plan,
            chapter_number=chapter_number,
            offending_event_index=offending_index,
        )
