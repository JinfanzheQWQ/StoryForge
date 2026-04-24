from __future__ import annotations

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import (
    ChapterCoverageEventSchema,
    ChapterCoverageEventSplitPlanSchema,
    ChapterCoveragePlanSchema,
)
from storyforge.domains.video.text_rules import (
    estimate_progression_node_count_from_texts,
    extract_progression_signal_terms,
)


class VideoChapterEventValidationMixin:
    """Validates chapter event coverage and targeted event splits."""

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
            summary_count = estimate_progression_node_count_from_texts([summary_text])
            if summary_count >= 2:
                return summary_count

        evidence_texts = [
            str(item or "").strip()
            for item in list(event.source_evidence or [])
            if str(item or "").strip()
        ]
        if not summary_text:
            return estimate_progression_node_count_from_texts(evidence_texts)

        summary_signals = extract_progression_signal_terms(summary_text)
        evidence_signals = extract_progression_signal_terms(" ".join(evidence_texts))
        extra_evidence_signals = evidence_signals - summary_signals
        if len(extra_evidence_signals) >= 2:
            return estimate_progression_node_count_from_texts(evidence_texts)

        return estimate_progression_node_count_from_texts([summary_text])
