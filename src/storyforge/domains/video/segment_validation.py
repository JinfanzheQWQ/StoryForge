from __future__ import annotations

from math import ceil
import re

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.errors import (
    SegmentActionSplitRequiredError,
    SegmentSpeechSplitRequiredError,
)
from storyforge.domains.video.schemas import (
    VideoSegmentPlanSchema,
    ChapterSceneSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
)
from storyforge.domains.video.text_rules import (
    ACTION_STEP_SPLIT_PATTERN,
    DIRECTION_APPROACH_PATTERNS,
    DIRECTION_RETREAT_PATTERNS,
    GENERIC_OPENING_MATCH_PHRASES,
    TIMED_BEAT_PREFIX_PATTERN,
    extract_progression_signal_terms,
    normalize_similarity_text,
    progress_text_too_generic,
    text_explicitly_stalled,
    text_new_signal_count,
    text_overlap_ratio,
)


TIMED_BEAT_PATTERN = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒"
)


class VideoSegmentValidationMixin:
    """Validates segment contracts and frame-transition constraints."""

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
                normalized = normalize_similarity_text(clause)
                if len(normalized) < 4:
                    continue
                if progress_text_too_generic(clause) and not extract_progression_signal_terms(clause):
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
        overlap = text_overlap_ratio(normalized_left, normalized_right)
        if overlap < 0.82:
            stalled_overlap = (
                overlap >= 0.72
                and (
                    text_explicitly_stalled(normalized_left)
                    or text_explicitly_stalled(normalized_right)
                )
            )
            if not stalled_overlap:
                return False
        new_signal_count = text_new_signal_count(normalized_left, normalized_right)
        left_terms = extract_progression_signal_terms(normalized_left)
        right_terms = extract_progression_signal_terms(normalized_right)
        if right_terms - left_terms:
            return False
        if (
            overlap >= 0.72
            and (
                text_explicitly_stalled(normalized_left)
                or text_explicitly_stalled(normalized_right)
            )
        ):
            return True
        if new_signal_count > 2:
            return False
        if progress_text_too_generic(normalized_right):
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
            text_explicitly_stalled(normalized_left)
            and text_explicitly_stalled(normalized_right)
            and (
                not normalized_allowed
                or text_explicitly_stalled(normalized_allowed)
                or progress_text_too_generic(normalized_allowed)
            )
        ):
            return True
        overlap = text_overlap_ratio(normalized_left, normalized_right)
        if overlap < 0.7:
            return False
        new_signal_count = text_new_signal_count(normalized_left, normalized_right)
        if new_signal_count > 2:
            return False
        if (
            text_explicitly_stalled(normalized_left)
            or text_explicitly_stalled(normalized_right)
        ):
            return True
        if not normalized_allowed or progress_text_too_generic(normalized_allowed):
            return overlap >= 0.76
        return text_overlap_ratio(normalized_left, normalized_allowed) >= 0.74

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
                opening_overlap = text_overlap_ratio(
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
