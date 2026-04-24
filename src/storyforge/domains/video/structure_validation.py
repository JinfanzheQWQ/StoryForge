from __future__ import annotations

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    ChapterCoveragePlanSchema,
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentChunkSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
)
from storyforge.domains.video.text_rules import (
    extract_boundary_critical_terms,
    extract_progression_signal_terms,
    progress_text_too_generic,
    text_explicitly_stalled,
    text_new_signal_count,
    text_overlap_ratio,
    normalize_similarity_text,
)


class VideoStructureValidationMixin:
    """Shared structure validators for chapter/scene/chunk planning."""

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

    def _validate_scene_segment_chunk_output(
        self,
        chunk_plan: SceneSegmentChunkPlanSchema,
        *,
        scene: ChapterSceneSchema,
        creative_strict: bool = True,
        warning_sink: list[str] | None = None,
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
                duplicate_message = (
                    f"scene {scene.scene_id} 的相邻 chunk {previous_chunk.chunk_id} 与 "
                    f"{normalized_chunk.chunk_id} 重复表达同一事件，缺少明确推进。"
                )
                if creative_strict:
                    raise ValueError(duplicate_message)
                if warning_sink is not None:
                    warning_sink.append(duplicate_message)
            total_expected_segments += normalized_chunk.expected_segment_count
            if creative_strict:
                self._validate_scene_chunk_event_scope(
                    scene=scene,
                    chunk=normalized_chunk,
                    is_last_chunk=order_index == len(chunk_plan.chunks),
                )
            else:
                try:
                    self._validate_scene_chunk_event_scope(
                        scene=scene,
                        chunk=normalized_chunk,
                        is_last_chunk=order_index == len(chunk_plan.chunks),
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
            normalized_chunks.append(normalized_chunk)
            previous_chunk = normalized_chunk
        if total_expected_segments > self.SCENE_MAX_EXPECTED_SEGMENTS:
            raise ValueError(
                f"scene {scene.scene_id} 预期共 {total_expected_segments} 个 segment，"
                f"超过 scene 上限 {self.SCENE_MAX_EXPECTED_SEGMENTS}。"
            )
        if normalized_chunks:
            if creative_strict:
                self._validate_scene_chunk_transition_entry(
                    scene=scene,
                    first_chunk=normalized_chunks[0],
                )
            else:
                try:
                    self._validate_scene_chunk_transition_entry(
                        scene=scene,
                        first_chunk=normalized_chunks[0],
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
        for normalized_chunk in normalized_chunks:
            if creative_strict:
                self._validate_scene_chunk_action_capacity(
                    scene=scene,
                    chunk=normalized_chunk,
                )
            else:
                try:
                    self._validate_scene_chunk_action_capacity(
                        scene=scene,
                        chunk=normalized_chunk,
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
        return chunk_plan.model_copy(
            update={
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "chunks": normalized_chunks,
            }
        )

    def _soft_accept_scene_chunk_plan(
        self,
        chunk_plan: SceneSegmentChunkPlanSchema,
        *,
        scene: ChapterSceneSchema,
        chapter_number: int,
        failure: Exception,
    ) -> SceneSegmentChunkPlanSchema | None:
        if not self._should_soften_scene_chunk_plan_validation(failure):
            return None
        warnings: list[str] = []
        softened_plan = self._validate_scene_segment_chunk_output(
            chunk_plan,
            scene=scene,
            creative_strict=False,
            warning_sink=warnings,
        )
        for warning in warnings:
            self._record_planner_warning(
                f"chapter {chapter_number} scene {scene.scene_id}：{warning} 当前先允许继续生成 segment。"
            )
        return softened_plan

    def _should_soften_scene_chunk_plan_validation(self, error: Exception) -> bool:
        normalized_error = str(error or "")
        soft_markers = (
            "重复表达同一事件",
            "动作容量过载",
            "提前引入了未绑定事件推进",
            "最后一个 chunk 没有真正落到当前 scene 绑定事件的最后结果",
            "首个 chunk 没有消费 scene_transition_contract 的开场承接",
            "首个 chunk 没有明确写出当前 scene 的环境 reveal",
        )
        return any(marker in normalized_error for marker in soft_markers)

    def _should_soften_scene_chunk_contract_validation(self, error: Exception) -> bool:
        normalized_error = str(error or "")
        soft_markers = (
            "重复表达同一事件",
            "opening_match 过于空泛",
            "缺少 continuity_link.opening_match",
            "continuity_link.opening_match 不能写成上一段承接话术",
            "没有明确承接上一段尾部状态",
            "首段 opening_match 没有承接 scene_transition_contract",
            "首段 timed_beats 没有消费 scene_transition_contract",
            "最后一个 segment 仍停在 transition_goal 发生前",
            "没有真正落到当前 chunk 的 transition_goal",
            "关键帧语义距离过近",
        )
        return any(marker in normalized_error for marker in soft_markers)

    def _soft_accept_scene_chunk_contract_batch(
        self,
        contracts: SceneSegmentContractBatchSchema,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        previous_tail_segment: SceneSegmentContractSchema | None,
        effective_expected_segment_count: int,
        failure: Exception,
    ) -> SceneSegmentContractBatchSchema | None:
        if not self._should_soften_scene_chunk_contract_validation(failure):
            return None
        warnings: list[str] = []
        softened_contracts = self._validate_scene_chunk_contract_output(
            contracts,
            scene=scene,
            chunk=chunk,
            previous_tail_segment=previous_tail_segment,
            effective_expected_segment_count=effective_expected_segment_count,
            creative_strict=False,
            warning_sink=warnings,
        )
        for warning in warnings:
            self._record_planner_warning(
                f"chapter {scene.chapter_number} scene {scene.scene_id} chunk {chunk.chunk_id}：{warning} 当前先允许继续执行 segment。"
            )
        return softened_contracts

    def _validate_scene_chunk_transition_entry(
        self,
        *,
        scene: ChapterSceneSchema,
        first_chunk: SceneSegmentChunkSchema,
    ) -> None:
        contract = scene.scene_transition_contract
        if not str(contract.previous_scene_id or "").strip():
            return
        transition_mode = self._normalize_scene_transition_mode(contract.transition_mode)
        chunk_signature = " ".join(
            [
                first_chunk.title.strip(),
                first_chunk.summary.strip(),
                " ".join(item.strip() for item in first_chunk.must_cover if item.strip()),
                first_chunk.transition_goal.strip(),
            ]
        )
        entry_seed = " ".join(
            part.strip()
            for part in (
                str(contract.next_scene_entry_match or "").strip(),
                str(contract.bridge_action or "").strip(),
                " ".join(item.strip() for item in contract.carry_over_elements if item.strip()),
            )
            if str(part).strip()
        )
        if max(
            text_overlap_ratio(chunk_signature, entry_seed),
            text_overlap_ratio(" ".join(first_chunk.must_cover), entry_seed),
        ) < 0.18:
            raise ValueError(
                f"scene {scene.scene_id} 的首个 chunk 没有消费 scene_transition_contract 的开场承接。"
            )
        if transition_mode != "hard_cut":
            reveal_overlap = text_overlap_ratio(
                chunk_signature,
                str(contract.visual_bridge or "").strip(),
            )
            if reveal_overlap < 0.1 and progress_text_too_generic(first_chunk.summary):
                raise ValueError(
                    f"scene {scene.scene_id} 的首个 chunk 没有明确写出当前 scene 的环境 reveal。"
                )

    def _validate_scene_chunk_action_capacity(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
    ) -> None:
        event_node_count = self._estimate_chunk_event_node_count(chunk)
        required_segment_count = self._minimum_segment_count_for_chunk_nodes(event_node_count)
        if chunk.expected_segment_count >= required_segment_count:
            return
        raise ValueError(
            f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 动作容量过载："
            f"当前 must_cover / transition_goal 至少包含 {event_node_count} 个推进点，"
            f"expected_segment_count 至少应为 {required_segment_count}，或拆成更多 chunk。"
        )

    def _validate_scene_chunk_event_scope(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        is_last_chunk: bool,
    ) -> None:
        covered_event_summaries = [
            str(item).strip()
            for item in list(getattr(scene, "covered_event_summaries", []) or [])
            if str(item).strip()
        ]
        if not covered_event_summaries:
            return

        chunk_signature = " ".join(
            part.strip()
            for part in (
                chunk.title,
                chunk.summary,
                " ".join(item.strip() for item in chunk.must_cover if item.strip()),
                chunk.transition_goal,
            )
            if str(part).strip()
        )
        allowed_event_signal = " ".join(covered_event_summaries)
        allowed_signal_terms = extract_boundary_critical_terms(
            " ".join([allowed_event_signal, scene.summary])
        )
        if int(chunk.order_index or 0) == 1:
            allowed_signal_terms |= self._extract_scene_transition_scope_terms(
                scene.scene_transition_contract
            )
        chunk_signal_terms = extract_boundary_critical_terms(chunk_signature)
        unexpected_critical_terms = sorted(chunk_signal_terms - allowed_signal_terms)
        if unexpected_critical_terms:
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 提前引入了未绑定事件推进："
                + "、".join(unexpected_critical_terms)
            )

        if is_last_chunk:
            last_event_summary = covered_event_summaries[-1]
            closing_signature = " ".join(
                part.strip()
                for part in (
                    chunk.summary,
                    " ".join(item.strip() for item in chunk.must_cover if item.strip()),
                    chunk.transition_goal,
                )
                if str(part).strip()
            )
            closing_critical_terms = extract_boundary_critical_terms(closing_signature)
            if closing_critical_terms:
                last_event_boundary_terms = extract_boundary_critical_terms(
                    last_event_summary
                )
                if closing_critical_terms & last_event_boundary_terms:
                    return
                closing_overlap = max(
                    text_overlap_ratio(closing_signature, last_event_summary),
                    text_overlap_ratio(chunk.transition_goal, last_event_summary),
                )
                if closing_overlap < 0.14:
                    raise ValueError(
                        f"scene {scene.scene_id} 的最后一个 chunk 没有真正落到当前 scene 绑定事件的最后结果。"
                    )

    def _extract_scene_transition_scope_terms(
        self,
        contract,
    ) -> set[str]:
        if contract is None:
            return set()
        transition_mode = self._normalize_scene_transition_mode(
            getattr(contract, "transition_mode", "")
        )
        if not str(getattr(contract, "previous_scene_id", "") or "").strip():
            return set()
        texts = [
            str(getattr(contract, "previous_scene_exit_state", "") or "").strip(),
            str(getattr(contract, "next_scene_entry_match", "") or "").strip(),
            str(getattr(contract, "bridge_action", "") or "").strip(),
            str(getattr(contract, "visual_bridge", "") or "").strip(),
        ]
        texts.extend(
            str(item).strip()
            for item in list(getattr(contract, "carry_over_elements", []) or [])
            if str(item).strip()
        )
        if transition_mode == "hard_cut":
            texts = [
                str(getattr(contract, "next_scene_entry_match", "") or "").strip(),
            ]
        return extract_boundary_critical_terms(" ".join(texts))

    def _estimate_chunk_event_node_count(
        self,
        chunk: SceneSegmentChunkSchema,
    ) -> int:
        event_texts: list[str] = []
        for item in chunk.must_cover:
            text = str(item or "").strip()
            if not text:
                continue
            if progress_text_too_generic(text) and not extract_progression_signal_terms(text):
                continue
            if max([text_overlap_ratio(text, existing) for existing in event_texts] or [0.0]) < 0.72:
                event_texts.append(text)
        transition_goal = str(chunk.transition_goal or "").strip()
        if (
            transition_goal
            and not (
                progress_text_too_generic(transition_goal)
                and not extract_progression_signal_terms(transition_goal)
            )
            and max(
                [text_overlap_ratio(transition_goal, item) for item in event_texts] or [0.0]
            ) < 0.72
        ):
            event_texts.append(transition_goal)
        return max(1, len(event_texts))

    def _minimum_segment_count_for_chunk_nodes(
        self,
        event_node_count: int,
    ) -> int:
        if event_node_count <= 3:
            return 1
        if event_node_count <= 5:
            return 2
        if event_node_count <= 7:
            return 3
        return self.SCENE_SEGMENT_CHUNK_MAX_SEGMENTS

    def _validate_scene_chunk_contract_output(
        self,
        contracts: SceneSegmentContractBatchSchema,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        previous_tail_segment: SceneSegmentContractSchema | None = None,
        effective_expected_segment_count: int | None = None,
        creative_strict: bool = True,
        warning_sink: list[str] | None = None,
    ) -> SceneSegmentContractBatchSchema:
        previous_segment: SceneSegmentContractSchema | None = None
        for segment in contracts.segments:
            if (
                previous_segment is not None
                and self._scene_chunk_segments_look_duplicate(previous_segment, segment)
            ):
                duplicate_message = (
                    f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 中，"
                    f"相邻 segment {previous_segment.segment_id} 与 {segment.segment_id} "
                    "重复表达同一事件，缺少动作推进。"
                )
                if creative_strict:
                    raise ValueError(duplicate_message)
                if warning_sink is not None:
                    warning_sink.append(duplicate_message)
            previous_segment = segment
        contracts = self._validate_scene_segment_contract_output(
            contracts,
            scene=scene,
            allow_nonstart_first_segment=previous_tail_segment is not None,
            creative_strict=creative_strict,
            warning_sink=warning_sink,
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
                previous_tail_state = self._build_scene_chunk_exit_state(previous_tail_segment)
                previous_end_state = str(previous_tail_state.get("visible_tail_state", "") or "")
                opening_seed = str(previous_tail_state.get("opening_match_seed", "") or "")
                carry_over_state = " ".join(
                    str(item).strip()
                    for item in list(previous_tail_state.get("carry_over_elements", []) or [])
                    if str(item).strip()
                )
                opening_text = first_segment.continuity_link.opening_match.strip()
                opening_overlap = max(
                    text_overlap_ratio(opening_text, previous_end_state),
                    text_overlap_ratio(opening_text, opening_seed),
                    text_overlap_ratio(opening_text, carry_over_state),
                )
                if opening_overlap < 0.22:
                    warning_message = (
                        f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 首段 opening_match "
                        "没有明确承接上一 chunk 尾部状态。"
                    )
                    if creative_strict:
                        raise ValueError(warning_message)
                    if warning_sink is not None:
                        warning_sink.append(warning_message)
        if contracts.segments:
            if creative_strict:
                self._validate_scene_boundary_segment_entry(
                    scene=scene,
                    chunk=chunk,
                    first_segment=contracts.segments[0],
                )
                self._validate_scene_chunk_result_landing(
                    scene=scene,
                    chunk=chunk,
                    last_segment=contracts.segments[-1],
                )
            else:
                try:
                    self._validate_scene_boundary_segment_entry(
                        scene=scene,
                        chunk=chunk,
                        first_segment=contracts.segments[0],
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
                try:
                    self._validate_scene_chunk_result_landing(
                        scene=scene,
                        chunk=chunk,
                        last_segment=contracts.segments[-1],
                    )
                except ValueError as exc:
                    if warning_sink is not None:
                        warning_sink.append(str(exc))
        return contracts.model_copy(
            update={
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
            }
        )

    def _validate_scene_boundary_segment_entry(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        first_segment: SceneSegmentContractSchema,
    ) -> None:
        contract = scene.scene_transition_contract
        if chunk.order_index != 1 or not str(contract.previous_scene_id or "").strip():
            return
        transition_mode = self._normalize_scene_transition_mode(contract.transition_mode)
        opening_text = first_segment.continuity_link.opening_match.strip()
        opening_seed = " ".join(
            part.strip()
            for part in (
                str(contract.previous_scene_exit_state or "").strip(),
                str(contract.next_scene_entry_match or "").strip(),
                " ".join(item.strip() for item in contract.carry_over_elements if item.strip()),
            )
            if str(part).strip()
        )
        opening_overlap = max(
            text_overlap_ratio(opening_text, opening_seed),
            text_overlap_ratio(opening_text, str(contract.next_scene_entry_match or "").strip()),
        )
        if opening_overlap < 0.18:
            raise ValueError(
                f"scene {scene.scene_id} 的首段 opening_match 没有承接 scene_transition_contract 的 entry state。"
            )
        if transition_mode != "hard_cut":
            bridge_seed = " ".join(
                part.strip()
                for part in (
                    self._first_timed_beat_text(first_segment.timed_beats),
                    self._middle_timed_beat_text(first_segment.timed_beats[:2]),
                    first_segment.shot_state.action_progression.strip(),
                )
                if str(part).strip()
            )
            bridge_overlap = max(
                text_overlap_ratio(bridge_seed, str(contract.bridge_action or "").strip()),
                text_overlap_ratio(bridge_seed, str(contract.visual_bridge or "").strip()),
            )
            if bridge_overlap < 0.14:
                raise ValueError(
                    f"scene {scene.scene_id} 的首段 timed_beats 没有消费 scene_transition_contract 的 bridge_action。"
                )

    def _validate_scene_chunk_result_landing(
        self,
        *,
        scene: ChapterSceneSchema,
        chunk: SceneSegmentChunkSchema,
        last_segment: SceneSegmentContractSchema,
    ) -> None:
        transition_goal = str(chunk.transition_goal or "").strip()
        chunk_summary = str(chunk.summary or "").strip()
        all_must_cover = " ".join(
            str(item).strip() for item in list(chunk.must_cover or []) if str(item).strip()
        )
        last_must_cover = next(
            (
                str(item).strip()
                for item in reversed(list(chunk.must_cover or []))
                if str(item).strip()
            ),
            "",
        )
        goal_seed = " ".join(
            part.strip()
            for part in (last_must_cover, transition_goal)
            if str(part).strip()
        )
        goal_terms = extract_progression_signal_terms(goal_seed)
        if not goal_seed or not goal_terms:
            return

        closing_signature = self._build_scene_chunk_result_landing_signature(last_segment)
        closing_overlap = max(
            text_overlap_ratio(closing_signature, transition_goal),
            text_overlap_ratio(closing_signature, chunk_summary),
            text_overlap_ratio(closing_signature, all_must_cover),
            text_overlap_ratio(closing_signature, last_must_cover),
            text_overlap_ratio(
                str(last_segment.shot_state.end_state_lock or "").strip(),
                transition_goal,
            ),
            text_overlap_ratio(
                str(last_segment.shot_state.end_state_lock or "").strip(),
                chunk_summary,
            ),
            text_overlap_ratio(
                self._last_timed_beat_text(last_segment.timed_beats),
                chunk_summary,
            ),
            text_overlap_ratio(
                self._last_timed_beat_text(last_segment.timed_beats),
                transition_goal,
            ),
        )
        if self._segment_closing_stops_before_goal(goal_seed, closing_signature):
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 最后一个 segment "
                "仍停在 transition_goal 发生前，没有真正落到当前 chunk 的结果。"
            )
        if closing_overlap < 0.14:
            if self._chunk_reads_like_atmospheric_closure(chunk) and max(
                text_overlap_ratio(closing_signature, chunk_summary),
                text_overlap_ratio(closing_signature, all_must_cover),
            ) >= 0.1:
                return
            raise ValueError(
                f"scene {scene.scene_id} 的 chunk {chunk.chunk_id} 最后一个 segment "
                "没有真正落到当前 chunk 的 transition_goal。"
            )

    def _build_scene_chunk_result_landing_signature(
        self,
        segment: SceneSegmentContractSchema,
    ) -> str:
        tail_audio = (
            str(segment.dialogue_lines[-1] or "").strip()
            if segment.dialogue_lines
            else (
                str(segment.subtitle_lines[-1] or "").strip()
                if segment.subtitle_lines
                else str(segment.narration or "").strip()
            )
        )
        return " ".join(
            part.strip()
            for part in (
                str(segment.summary or "").strip(),
                self._build_end_anchor_state_text(
                    summary=segment.summary,
                    timed_beats=segment.timed_beats,
                    shot_state=segment.shot_state,
                ),
                tail_audio,
            )
            if str(part).strip()
        )

    def _segment_closing_stops_before_goal(
        self,
        goal_text: str,
        closing_text: str,
    ) -> bool:
        normalized_closing = normalize_similarity_text(closing_text)
        if not normalized_closing:
            return False
        for term in extract_progression_signal_terms(goal_text):
            if any(
                f"{prefix}{term}" in normalized_closing
                for prefix in ("准备", "即将", "将要", "快要", "正要", "欲", "等待", "尚未", "还未")
            ):
                return True
        return any(
            phrase in normalized_closing
            for phrase in (
                "等待下一拍",
                "等待后续",
                "等待下一场推进",
                "停在回应前的一刻",
                "停在开口前的一刻",
                "停在告白前的一刻",
                "停在亲吻前的一刻",
            )
        )

    def _chunk_reads_like_atmospheric_closure(
        self,
        chunk: SceneSegmentChunkSchema,
    ) -> bool:
        combined = " ".join(
            part.strip()
            for part in (
                str(chunk.summary or "").strip(),
                str(chunk.transition_goal or "").strip(),
                " ".join(str(item).strip() for item in list(chunk.must_cover or []) if str(item).strip()),
            )
            if str(part).strip()
        )
        normalized = normalize_similarity_text(combined)
        if not normalized:
            return False
        if any(
            token in normalized
            for token in (
                "安静",
                "静谧",
                "寂静",
                "沉默",
                "余韵",
                "凝固",
                "定格",
                "世界安静",
                "场景结束",
                "镜头结束",
                "收束",
                "广播声远去",
                "风停",
                "花落静止",
            )
        ):
            return True
        return False

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
        signature_overlap = text_overlap_ratio(previous_signature, current_signature)
        summary_overlap = text_overlap_ratio(previous_chunk.summary, current_chunk.summary)
        must_cover_overlap = text_overlap_ratio(
            " ".join(previous_chunk.must_cover),
            " ".join(current_chunk.must_cover),
        )
        new_signal_count = text_new_signal_count(previous_signature, current_signature)
        transition_overlap = text_overlap_ratio(
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
                    or progress_text_too_generic(current_chunk.transition_goal)
                )
            )
            or (
                summary_overlap >= 0.45
                and must_cover_overlap >= 0.28
                and (
                    not (
                        extract_progression_signal_terms(current_signature)
                        - extract_progression_signal_terms(previous_signature)
                    )
                    or text_explicitly_stalled(current_signature)
                )
                and progress_text_too_generic(current_chunk.transition_goal)
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
        summary_overlap = text_overlap_ratio(previous_segment.summary, current_segment.summary)
        action_overlap = text_overlap_ratio(previous_action, current_action)
        beats_overlap = text_overlap_ratio(
            " ".join(previous_segment.timed_beats),
            " ".join(current_segment.timed_beats),
        )
        signature_overlap = text_overlap_ratio(previous_signature, current_signature)
        new_signal_count = text_new_signal_count(previous_signature, current_signature)
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
                    or progress_text_too_generic(allowed_changes)
                    or text_overlap_ratio(previous_action, allowed_changes) >= 0.72
                )
            )
            or (
                summary_overlap >= 0.45
                and action_overlap >= 0.3
                and beats_overlap >= 0.45
                and (
                    not (
                        extract_progression_signal_terms(current_signature)
                        - extract_progression_signal_terms(previous_signature)
                    )
                    or text_explicitly_stalled(current_signature)
                )
                and (
                    not allowed_changes
                    or progress_text_too_generic(allowed_changes)
                    or text_explicitly_stalled(allowed_changes)
                )
            )
        )

    def _validate_chapter_scene_structure_output(
        self,
        structure: ChapterSceneStructureSchema,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        chapter_event_plan: ChapterCoveragePlanSchema,
    ) -> ChapterSceneStructureSchema:
        if not structure.scenes:
            raise ValueError("ChapterSceneStructureSchema.scenes 不能为空。")
        expected_event_ids = [item.event_id for item in chapter_event_plan.events]
        event_summary_map = {
            item.event_id: item.summary.strip()
            for item in chapter_event_plan.events
            if item.summary.strip()
        }
        event_character_map = {
            item.event_id: {
                name.strip()
                for name in item.involved_characters
                if name.strip()
            }
            for item in chapter_event_plan.events
        }
        seen_scene_ids: set[str] = set()
        covered_event_sequence: list[str] = []
        previous_scene: ChapterSceneSchema | None = None
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
            if not scene.covered_event_ids:
                raise ValueError(f"scene {scene.scene_id} 的 covered_event_ids 不能为空。")
            if len(scene.covered_event_ids) != len(set(scene.covered_event_ids)):
                raise ValueError(f"scene {scene.scene_id} 的 covered_event_ids 不能重复。")
            invalid_event_ids = [
                event_id
                for event_id in scene.covered_event_ids
                if event_id not in expected_event_ids
            ]
            if invalid_event_ids:
                raise ValueError(
                    f"scene {scene.scene_id} 使用了不存在的关键事件 ID："
                    + "、".join(invalid_event_ids)
                )
            positions = [expected_event_ids.index(event_id) for event_id in scene.covered_event_ids]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                raise ValueError(
                    f"scene {scene.scene_id} 的 covered_event_ids 必须对应连续事件块，不能跳过中间事件。"
                )
            required_characters: set[str] = set()
            for event_id in scene.covered_event_ids:
                required_characters.update(event_character_map.get(event_id, set()))
            missing_characters = sorted(
                name for name in required_characters
                if name not in scene.involved_characters
            )
            if missing_characters:
                raise ValueError(
                    f"scene {scene.scene_id} 覆盖了包含这些角色的关键事件，但 involved_characters 缺失："
                    + "、".join(missing_characters)
                )
            self._validate_scene_transition_contract(
                current_scene=scene,
                previous_scene=previous_scene,
            )
            covered_event_sequence.extend(scene.covered_event_ids)
            previous_scene = scene

        if covered_event_sequence != expected_event_ids:
            missing_event_ids = [
                event_id for event_id in expected_event_ids if event_id not in covered_event_sequence
            ]
            repeated_event_ids = [
                event_id for event_id in covered_event_sequence
                if covered_event_sequence.count(event_id) > 1
            ]
            details: list[str] = []
            if missing_event_ids:
                details.append("缺失：" + "、".join(missing_event_ids))
            if repeated_event_ids:
                details.append("重复：" + "、".join(dict.fromkeys(repeated_event_ids)))
            raise ValueError(
                "scene structure 的关键事件覆盖不完整或顺序错误。"
                + ("；".join(details) if details else "")
            )
        return structure.model_copy(
            update={
                "scenes": [
                    scene.model_copy(
                        update={
                            "covered_event_summaries": [
                                event_summary_map[event_id]
                                for event_id in scene.covered_event_ids
                                if event_summary_map.get(event_id)
                            ]
                        }
                    )
                    for scene in structure.scenes
                ]
            }
        )

    def _normalize_scene_transition_mode(self, raw_mode: str) -> str:
        value = str(raw_mode or "").strip().lower()
        if value in {"direct_continue", "adjacent_move", "motivated_cut", "hard_cut"}:
            return value
        return ""

    def _validate_scene_transition_contract(
        self,
        *,
        current_scene: ChapterSceneSchema,
        previous_scene: ChapterSceneSchema | None,
    ) -> None:
        contract = current_scene.scene_transition_contract
        previous_scene_id = str(contract.previous_scene_id or "").strip()
        transition_mode = self._normalize_scene_transition_mode(contract.transition_mode)
        has_contract_signal = bool(
            previous_scene_id
            or transition_mode
            or str(contract.previous_scene_exit_state or "").strip()
            or str(contract.next_scene_entry_match or "").strip()
            or str(contract.bridge_action or "").strip()
            or list(contract.carry_over_elements)
            or str(contract.screen_direction_policy or "").strip()
            or str(contract.visual_bridge or "").strip()
            or str(contract.audio_bridge or "none").strip().lower() != "none"
            or int(contract.transition_focus_seconds or 0) > 0
        )
        if previous_scene is None:
            if has_contract_signal:
                raise ValueError(
                    f"scene {current_scene.scene_id} 作为首个 scene 时，"
                    "scene_transition_contract 必须为空合同。"
                )
            return

        if previous_scene_id != previous_scene.scene_id:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.previous_scene_id "
                f"必须指向上一场 {previous_scene.scene_id}。"
            )
        if not transition_mode:
            raise ValueError(
                f"scene {current_scene.scene_id} 缺少合法的 "
                "scene_transition_contract.transition_mode。"
            )
        if str(contract.audio_bridge or "none").strip().lower() not in {
            "none",
            "j_cut",
            "l_cut",
            "ambient_bridge",
        }:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.audio_bridge 非法。"
            )

        required_fields = {"next_scene_entry_match": contract.next_scene_entry_match}
        if transition_mode != "hard_cut":
            required_fields.update(
                {
                    "previous_scene_exit_state": contract.previous_scene_exit_state,
                    "bridge_action": contract.bridge_action,
                    "screen_direction_policy": contract.screen_direction_policy,
                    "visual_bridge": contract.visual_bridge,
                }
            )
        missing_fields = [
            field_name
            for field_name, value in required_fields.items()
            if not str(value or "").strip()
        ]
        if missing_fields:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract 缺少："
                + "、".join(missing_fields)
            )
        if transition_mode != "hard_cut" and not [
            item for item in contract.carry_over_elements if str(item or "").strip()
        ]:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.carry_over_elements 不能为空。"
            )
        if transition_mode != "hard_cut" and int(contract.transition_focus_seconds or 0) < 1:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.transition_focus_seconds "
                "必须在 1-3 秒内。"
            )

        previous_scene_signal = self._build_scene_transition_previous_scene_signal(previous_scene)
        previous_overlap = max(
            text_overlap_ratio(str(contract.previous_scene_exit_state or "").strip(), previous_scene_signal),
            text_overlap_ratio(" ".join(contract.carry_over_elements), previous_scene_signal),
        )
        if transition_mode != "hard_cut" and previous_overlap < 0.12:
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.previous_scene_exit_state "
                "没有明显承接上一 scene 已成立的尾部状态。"
            )
        if not self._scene_transition_entry_matches_current_scene(current_scene, contract):
            raise ValueError(
                f"scene {current_scene.scene_id} 的 scene_transition_contract.next_scene_entry_match "
                "没有明显落到当前 scene 的开场状态。"
            )

    def _build_scene_transition_previous_scene_signal(
        self,
        scene: ChapterSceneSchema,
    ) -> str:
        return " ".join(
            part.strip()
            for part in (
                scene.summary,
                scene.scene_anchor,
                scene.scene_bible.character_blocking,
                scene.scene_bible.continuity_notes,
            )
            if str(part).strip()
        )

    def _build_scene_transition_current_scene_signal(
        self,
        scene: ChapterSceneSchema,
    ) -> str:
        return " ".join(
            part.strip()
            for part in (
                scene.summary,
                scene.scene_anchor,
                scene.scene_bible.character_blocking,
                scene.scene_bible.spatial_layout,
                scene.scene_bible.continuity_notes,
            )
            if str(part).strip()
        )

    def _scene_transition_entry_matches_current_scene(
        self,
        scene: ChapterSceneSchema,
        contract,
    ) -> bool:
        entry_text = str(contract.next_scene_entry_match or "").strip()
        if not entry_text:
            return False
        current_signal = self._build_scene_transition_current_scene_signal(scene)
        visual_bridge = str(contract.visual_bridge or "").strip()
        if max(
            text_overlap_ratio(entry_text, current_signal),
            text_overlap_ratio(visual_bridge, current_signal),
        ) >= 0.12:
            return self._scene_transition_entry_has_filmable_state(entry_text)
        if not self._scene_transition_entry_has_current_anchor(scene, entry_text):
            return False
        return self._scene_transition_entry_has_filmable_state(entry_text)

    def _scene_transition_entry_has_current_anchor(
        self,
        scene: ChapterSceneSchema,
        entry_text: str,
    ) -> bool:
        normalized = normalize_similarity_text(entry_text)
        anchors = [
            scene.title,
            scene.scene_anchor,
            scene.scene_bible.location,
            scene.scene_bible.spatial_layout,
            scene.scene_bible.character_blocking,
            scene.scene_bible.continuity_notes,
            *scene.scene_bible.background_anchors,
            *scene.scene_bible.fixed_props,
        ]
        for anchor in anchors:
            anchor_text = str(anchor or "").strip()
            if len(anchor_text) < 2:
                continue
            if normalize_similarity_text(anchor_text) in normalized:
                return True
        return False

    def _scene_transition_entry_has_filmable_state(self, entry_text: str) -> bool:
        text = str(entry_text or "").strip()
        if not text:
            return False
        filmable_tokens = (
            "站", "坐", "停", "走", "进入", "入画", "来到", "到达", "看向", "望向",
            "面向", "背对", "并肩", "靠近", "转身", "低头", "抬头", "拿着", "握着",
            "停在", "站在", "坐在", "位于", "处在", "开头", "第一秒", "先建立",
        )
        if any(token in text for token in filmable_tokens):
            return True
        return bool(extract_progression_signal_terms(text))
