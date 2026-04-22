from __future__ import annotations

import re

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    ContinuityLinkSchema,
    SceneBibleSchema,
    ShotStateSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


class VideoRepairMixin:
    def _repair_character_visual_bible(
        self,
        visual_bible: CharacterVisualBibleSchema,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        canonical_characters = list(novel_package.outline.characters)
        canonical_names = [item.name for item in canonical_characters]
        role_map = {item.name: item.role for item in canonical_characters}
        gender_map = {item.name: item.gender for item in canonical_characters}
        repaired: dict[str, object] = {}

        for item in visual_bible.characters:
            resolved_name = self._resolve_character_name(
                raw_name=item.name,
                canonical_names=canonical_names,
                role_map=role_map,
            ) or self._resolve_character_name(
                raw_name=item.role,
                canonical_names=canonical_names,
                role_map=role_map,
            )
            if not resolved_name or resolved_name in repaired:
                continue
            repaired_item = item.model_copy(
                update={
                    "name": resolved_name,
                    "role": role_map.get(resolved_name, item.role),
                    "gender": gender_map.get(resolved_name, item.gender),
                    "portrait_prompt": self._replace_character_aliases(
                        item.portrait_prompt,
                        {item.name: resolved_name},
                    ),
                }
            )
            repaired[resolved_name] = repaired_item

        return CharacterVisualBibleSchema(
            characters=[repaired[name] for name in canonical_names]
        )

    def _resolve_character_name(
        self,
        raw_name: str,
        canonical_names: list[str],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token
        if len(canonical_names) == 1:
            return canonical_names[0]

        lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主角团",
            "神秘人",
            "录音师",
            "修复师",
            "告白者",
            "主动方",
            "发起者",
        }
        if token in lead_aliases:
            return canonical_names[0]

        counterpart_aliases = {
            "被告白的人",
            "被表白的人",
            "对方",
            "另一方",
            "回应方",
            "被回应的人",
        }
        if token in counterpart_aliases:
            return canonical_names[1] if len(canonical_names) >= 2 else canonical_names[0]

        fuzzy_matches = [
            name for name in canonical_names if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name for name, role in role_map.items() if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]
        return ""

    def _repair_segment_plan(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        valid_chapters = {chapter.number for chapter in novel_package.outline.chapters}
        repaired_segments = [
            item
            for item in plan.segments
            if item.chapter_number in valid_chapters
        ]
        return VideoSegmentPlanSchema(segments=repaired_segments)

    def _repair_scene_bibles(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
    ) -> VideoSegmentPlanSchema:
        chapter_numbers = {
            item.number
            for item in novel_package.outline.chapters
        }
        repaired_by_scene: dict[tuple[int, str], SceneBibleSchema] = {}
        for scene in plan.scenes:
            if scene.chapter_number not in chapter_numbers:
                continue
            repaired_by_scene[(scene.chapter_number, scene.scene_id)] = self._repair_scene_bible(
                novel_package=novel_package,
                chapter_number=scene.chapter_number,
                scene_title=scene.title,
                scene_summary=scene.summary,
                scene_anchor=scene.scene_anchor,
                scene_bible=scene.scene_bible,
                involved_characters=scene.involved_characters,
            )

        repaired_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            repaired_scene_bible = repaired_by_scene.get((segment.chapter_number, segment.scene_id))
            if repaired_scene_bible is None:
                repaired_scene_bible = self._repair_scene_bible(
                    novel_package=novel_package,
                    chapter_number=segment.chapter_number,
                    scene_title=segment.scene_title or segment.title,
                    scene_summary=segment.scene_summary or segment.summary,
                    scene_anchor=segment.scene_anchor,
                    scene_bible=segment.scene_bible,
                    involved_characters=segment.involved_characters,
                )
            repaired_segments.append(
                segment.model_copy(update={"scene_bible": repaired_scene_bible})
            )

        return VideoSegmentPlanSchema(segments=repaired_segments)

    def _repair_shot_states(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
    ) -> VideoSegmentPlanSchema:
        repaired_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            repaired_segments.append(
                segment.model_copy(
                    update={
                        "shot_state": self._repair_shot_state(
                            novel_package=novel_package,
                            segment=segment,
                        )
                    }
                )
            )
        return VideoSegmentPlanSchema(segments=repaired_segments)

    def _repair_continuity_links(
        self,
        plan: VideoSegmentPlanSchema,
    ) -> VideoSegmentPlanSchema:
        repaired_segments: list[VideoSegmentSchema] = []
        previous_segment: VideoSegmentSchema | None = None
        for segment in plan.segments:
            repaired_link = self._repair_continuity_link(
                segment=segment,
                previous_segment=previous_segment,
            )
            should_reuse_previous = (
                previous_segment is not None
                and repaired_link.transition_mode == "continue"
                and repaired_link.previous_segment_id == previous_segment.segment_id
            )
            repaired_segment = segment.model_copy(
                update={
                    "continuity_link": repaired_link,
                    "reuse_previous_end_frame": should_reuse_previous,
                }
            )
            repaired_segments.append(repaired_segment)
            previous_segment = repaired_segment
        return VideoSegmentPlanSchema(segments=repaired_segments)

    def _repair_scene_bible(
        self,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        scene_title: str,
        scene_summary: str,
        scene_anchor: str,
        scene_bible: SceneBibleSchema,
        involved_characters: list[str],
    ) -> SceneBibleSchema:
        default_payload = self._derive_scene_bible_defaults(
            novel_package=novel_package,
            chapter_number=chapter_number,
            scene_title=scene_title or "场景",
            scene_summary=scene_summary or scene_title or "当前场景",
            scene_anchor=scene_anchor,
            focus_characters=involved_characters,
        )
        payload = scene_bible.model_dump()
        repaired: dict[str, object] = {}
        for key, default_value in default_payload.items():
            current_value = payload.get(key)
            repaired[key] = (
                current_value
                if self._scene_bible_value_has_signal(current_value)
                else default_value
            )
        return SceneBibleSchema.model_validate(repaired)

    def _repair_shot_state(
        self,
        *,
        novel_package: NovelPackage,
        segment: VideoSegmentSchema,
    ) -> ShotStateSchema:
        default_payload = self._derive_shot_state_defaults(
            summary=segment.summary,
            scene_anchor=segment.scene_anchor,
            scene_bible=segment.scene_bible,
            focus_characters=segment.involved_characters,
        )
        payload = segment.shot_state.model_dump()
        repaired: dict[str, object] = {}
        for key, default_value in default_payload.items():
            current_value = payload.get(key)
            repaired[key] = (
                current_value
                if self._shot_state_value_has_signal(current_value)
                else default_value
            )

        if not str(repaired.get("action_progression", "")).strip():
            repaired["action_progression"] = segment.summary
        if not str(repaired.get("end_state_lock", "")).strip():
            repaired["end_state_lock"] = (
                self._extract_beat_descriptions(segment.timed_beats)[-1]
                if self._extract_beat_descriptions(segment.timed_beats)
                else segment.summary
            )
        return ShotStateSchema.model_validate(repaired)

    def _repair_continuity_link(
        self,
        *,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema | None,
    ) -> ContinuityLinkSchema:
        payload = segment.continuity_link.model_dump()
        if previous_segment is None:
            return ContinuityLinkSchema.model_validate(
                {
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": "",
                    "carry_over_elements": [],
                    "allowed_changes": (
                        str(payload.get("allowed_changes", "") or "")
                        or "作为当前故事或场景的起始片段建立新的连续性基线。"
                    ),
                    "transition_reason": (
                        str(payload.get("transition_reason", "") or "")
                        or "首段没有上一片段可承接。"
                    ),
                }
            )

        derived_mode = self._derive_continuity_mode(segment, previous_segment)
        raw_mode = str(payload.get("transition_mode", "") or "").strip().lower()
        transition_mode = raw_mode if raw_mode in {"start", "continue", "cut"} else derived_mode
        if transition_mode == "start":
            transition_mode = derived_mode

        opening_match = str(payload.get("opening_match", "") or "").strip()
        if transition_mode == "continue":
            derived_opening_match = self._derive_opening_match(previous_segment)
            if (
                not opening_match
                or self._continuity_statement_too_generic(opening_match)
                or self._text_overlap_ratio(
                    opening_match,
                    previous_segment.shot_state.end_state_lock or previous_segment.summary,
                ) < 0.22
            ):
                opening_match = derived_opening_match

        carry_over_elements = [
            str(item).strip()
            for item in payload.get("carry_over_elements", [])
            if str(item).strip()
        ]
        if transition_mode == "continue" and not carry_over_elements:
            carry_over_elements = self._derive_carry_over_elements(previous_segment)

        allowed_changes = str(payload.get("allowed_changes", "") or "").strip()
        if transition_mode == "continue":
            derived_allowed_changes = self._derive_allowed_changes(segment, previous_segment)
            if (
                not allowed_changes
                or self._continuity_statement_too_generic(allowed_changes)
                or self._text_overlap_ratio(
                    allowed_changes,
                    previous_segment.shot_state.end_state_lock or previous_segment.summary,
                ) >= 0.78
            ):
                allowed_changes = derived_allowed_changes
        elif not allowed_changes:
            allowed_changes = (
                "允许切换到新的时空、景别和动作状态。"
                if transition_mode == "cut"
                else "作为起始段建立新的连续性基线。"
            )

        transition_reason = str(payload.get("transition_reason", "") or "").strip()
        if not transition_reason:
            transition_reason = (
                "同一 scene 内连续推进当前动作链。"
                if transition_mode == "continue"
                else (
                    "发生了明确转场、时空切换或镜头切断。"
                    if transition_mode == "cut"
                    else "当前片段为起始段。"
                )
            )

        return ContinuityLinkSchema.model_validate(
            {
                "previous_segment_id": (
                    previous_segment.segment_id
                    if transition_mode == "continue"
                    else ""
                ),
                "transition_mode": transition_mode,
                "opening_match": opening_match,
                "carry_over_elements": (
                    carry_over_elements if transition_mode == "continue" else []
                ),
                "allowed_changes": allowed_changes,
                "transition_reason": transition_reason,
            }
        )

    def _derive_continuity_mode(
        self,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        explicit_previous_id = segment.continuity_link.previous_segment_id.strip()
        explicit_mode = segment.continuity_link.transition_mode.strip().lower()
        if explicit_mode == "continue" and explicit_previous_id == previous_segment.segment_id:
            return "continue"
        if explicit_mode == "cut":
            return "cut"

        transition_hint = self._normalize_transition_hint(segment.transition_hint)
        if transition_hint == "continue":
            return "continue"
        if transition_hint == "cut":
            return "cut"

        if segment.scene_id and previous_segment.scene_id and segment.scene_id == previous_segment.scene_id:
            return "continue"
        if (
            segment.source_segment_id
            and previous_segment.source_segment_id
            and segment.source_segment_id == previous_segment.source_segment_id
        ):
            return "continue"
        if self._contains_hard_cut_hint(
            previous_segment.model_copy(update={"narration": previous_segment.narration + " " + segment.narration})
        ):
            return "cut"
        return "cut"

    def _derive_carry_over_elements(
        self,
        previous_segment: VideoSegmentSchema,
    ) -> list[str]:
        carry_over: list[str] = []
        if previous_segment.shot_state.blocking:
            carry_over.append("角色站位")
        if previous_segment.shot_state.screen_direction:
            carry_over.append("视线与运动方向")
        if previous_segment.shot_state.prop_continuity:
            carry_over.append("关键道具与手部状态")
        if previous_segment.scene_bible.background_anchors:
            carry_over.append("背景锚点")
        if previous_segment.shot_state.end_state_lock:
            carry_over.append("上一段尾部动作定格")
        if not carry_over:
            carry_over.extend(["角色站位", "视线方向", "关键道具"])
        return carry_over

    def _derive_opening_match(
        self,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        previous_end = (
            previous_segment.shot_state.end_state_lock
            or previous_segment.shot_state.action_progression
            or previous_segment.summary
        )
        parts = [f"开场先严格承接上一段尾部：{previous_end}"]
        if previous_segment.shot_state.blocking:
            parts.append(f"保留站位/朝向：{previous_segment.shot_state.blocking}")
        if previous_segment.shot_state.prop_continuity:
            parts.append(f"保留持物/服装状态：{previous_segment.shot_state.prop_continuity}")
        if previous_segment.shot_state.screen_direction:
            parts.append(f"维持运动与视线方向：{previous_segment.shot_state.screen_direction}")
        return "；".join(part.strip() for part in parts if part.strip())

    def _derive_allowed_changes(
        self,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        previous_end = (
            previous_segment.shot_state.end_state_lock
            or previous_segment.shot_state.action_progression
            or previous_segment.summary
        )
        beat_descriptions = self._extract_beat_descriptions(segment.timed_beats)
        target_progress = (
            segment.shot_state.action_progression
            or segment.summary
            or (beat_descriptions[0] if beat_descriptions else "")
        )
        if self._text_overlap_ratio(previous_end, target_progress) >= 0.78:
            target_progress = segment.summary or target_progress
        return (
            f"承接开场后，必须把动作从“{previous_end}”推进到“{target_progress}”，"
            "不能只是重复上一段的同一拍。"
        )

    def _group_segments_by_chapter(
        self,
        segments: list[VideoSegmentSchema],
    ) -> dict[int, list[VideoSegmentSchema]]:
        grouped: dict[int, list[VideoSegmentSchema]] = {}
        for item in segments:
            grouped.setdefault(item.chapter_number, []).append(item)
        return grouped

    def _normalize_segment_characters(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        canonical_names = [item.name for item in novel_package.outline.characters] or [
            item.name for item in visual_bible.characters
        ]
        chapter_feature_map = {
            item.number: list(item.featured_characters)
            for item in novel_package.outline.chapters
        }
        role_map = {
            item.name: item.role
            for item in novel_package.outline.characters
        }

        normalized_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            alias_map: dict[str, str] = {}
            resolved_names: list[str] = []
            for raw_name in segment.involved_characters:
                resolved = self._resolve_character_alias(
                    raw_name=raw_name,
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                    role_map=role_map,
                )
                if resolved:
                    alias_map[raw_name] = resolved
                    if resolved not in resolved_names:
                        resolved_names.append(resolved)

            if not resolved_names:
                resolved_names = self._default_segment_characters(
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                )
            resolved_names = self._augment_segment_characters_from_text(
                segment=segment,
                resolved_names=resolved_names,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )

            normalized_segments.append(
                segment.model_copy(
                    update={
                        "scene_title": self._replace_character_aliases(segment.scene_title, alias_map),
                        "scene_summary": self._replace_character_aliases(segment.scene_summary, alias_map),
                        "scene_anchor": self._replace_character_aliases(segment.scene_anchor, alias_map),
                        "scene_bible": self._replace_character_aliases_in_scene_bible(
                            segment.scene_bible,
                            alias_map,
                        ),
                        "shot_state": self._replace_character_aliases_in_shot_state(
                            segment.shot_state,
                            alias_map,
                        ),
                        "continuity_link": self._replace_character_aliases_in_continuity_link(
                            segment.continuity_link,
                            alias_map,
                        ),
                        "title": self._replace_character_aliases(segment.title, alias_map),
                        "involved_characters": resolved_names,
                        "start_frame_characters": self._normalize_frame_characters_for_segment(
                            frame_position="start",
                            raw_names=segment.start_frame_characters,
                            prompt_text=segment.start_frame_prompt,
                            frame_context_text=self._frame_context_text(segment, "start"),
                            resolved_names=resolved_names,
                            chapter_number=segment.chapter_number,
                            canonical_names=canonical_names,
                            chapter_feature_map=chapter_feature_map,
                            role_map=role_map,
                        ),
                        "mid_frame_characters": self._normalize_frame_characters_for_segment(
                            frame_position="mid",
                            raw_names=segment.mid_frame_characters,
                            prompt_text=segment.mid_frame_prompt,
                            frame_context_text=self._frame_context_text(segment, "mid"),
                            resolved_names=resolved_names,
                            chapter_number=segment.chapter_number,
                            canonical_names=canonical_names,
                            chapter_feature_map=chapter_feature_map,
                            role_map=role_map,
                        ),
                        "end_frame_characters": self._normalize_frame_characters_for_segment(
                            frame_position="end",
                            raw_names=segment.end_frame_characters,
                            prompt_text=segment.end_frame_prompt,
                            frame_context_text=self._frame_context_text(segment, "end"),
                            resolved_names=resolved_names,
                            chapter_number=segment.chapter_number,
                            canonical_names=canonical_names,
                            chapter_feature_map=chapter_feature_map,
                            role_map=role_map,
                        ),
                        "summary": self._replace_character_aliases(segment.summary, alias_map),
                        "narration": self._replace_character_aliases(segment.narration, alias_map),
                        "dialogue_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.dialogue_lines
                        ],
                        "subtitle_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.subtitle_lines
                        ],
                        "character_voice_notes": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.character_voice_notes
                        ],
                        "sound_effects": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.sound_effects
                        ],
                        "music_direction": self._replace_character_aliases(
                            segment.music_direction,
                            alias_map,
                        ),
                        "timed_beats": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.timed_beats
                        ],
                        "start_frame_prompt": self._replace_character_aliases(
                            segment.start_frame_prompt,
                            alias_map,
                        ),
                        "mid_frame_prompt": self._replace_character_aliases(
                            segment.mid_frame_prompt,
                            alias_map,
                        ),
                        "end_frame_prompt": self._replace_character_aliases(
                            segment.end_frame_prompt,
                            alias_map,
                        ),
                    }
                )
            )

        return VideoSegmentPlanSchema(segments=normalized_segments)

    def _resolve_character_alias(
        self,
        raw_name: str,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token

        generic_lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主人物",
            "lead",
            "hero",
            "protagonist",
            "告白者",
            "主动方",
            "发起者",
        }
        if token.lower() in generic_lead_aliases or token in generic_lead_aliases:
            featured = self._default_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            return featured[0] if featured else ""

        counterpart_aliases = {
            "被告白的人",
            "被表白的人",
            "对方",
            "另一方",
            "回应方",
            "被回应的人",
        }
        if token in counterpart_aliases:
            featured = self._default_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            if len(featured) >= 2:
                return featured[1]
            return canonical_names[1] if len(canonical_names) >= 2 else ""

        fuzzy_matches = [
            name
            for name in canonical_names
            if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name
            for name, role in role_map.items()
            if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]

        return ""

    def _default_segment_characters(
        self,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
    ) -> list[str]:
        featured = [
            name
            for name in chapter_feature_map.get(chapter_number, [])
            if name in canonical_names
        ]
        if featured:
            return featured
        return canonical_names[:1]

    def _augment_segment_characters_from_text(
        self,
        segment: VideoSegmentSchema,
        resolved_names: list[str],
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> list[str]:
        combined_text = " ".join(
            [
                segment.title,
                segment.summary,
                segment.narration,
                segment.start_frame_prompt,
                segment.end_frame_prompt,
                segment.scene_bible.location,
                segment.scene_bible.time_window,
                segment.scene_bible.weather,
                segment.scene_bible.lighting,
                segment.scene_bible.spatial_layout,
                segment.scene_bible.character_blocking,
                segment.scene_bible.continuity_notes,
                " ".join(segment.scene_bible.background_anchors),
                " ".join(segment.scene_bible.fixed_props),
                segment.shot_state.framing,
                segment.shot_state.camera_motion,
                segment.shot_state.blocking,
                segment.shot_state.action_progression,
                segment.shot_state.emotion_progression,
                segment.shot_state.prop_continuity,
                segment.shot_state.screen_direction,
                segment.shot_state.end_state_lock,
                segment.continuity_link.previous_segment_id,
                segment.continuity_link.opening_match,
                " ".join(segment.continuity_link.carry_over_elements),
                segment.continuity_link.allowed_changes,
                segment.continuity_link.transition_reason,
                " ".join(segment.dialogue_lines),
                " ".join(segment.subtitle_lines),
                " ".join(segment.timed_beats),
            ]
        )
        augmented = list(resolved_names)
        for name in canonical_names:
            if name in combined_text and name not in augmented:
                augmented.append(name)

        alias_candidates = list(segment.involved_characters)
        alias_candidates.extend(self._extract_dialogue_speakers(segment.dialogue_lines))
        for raw_name in alias_candidates:
            resolved = self._resolve_character_alias(
                raw_name=raw_name,
                chapter_number=segment.chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )
            if resolved and resolved not in augmented:
                augmented.append(resolved)

        if self._looks_like_two_person_scene(combined_text) and len(augmented) < 2:
            for name in chapter_feature_map.get(segment.chapter_number, []):
                if name not in augmented and name in canonical_names:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break
            for name in canonical_names:
                if len(augmented) >= 2:
                    break
                if name not in augmented:
                    augmented.append(name)

        if len(augmented) < 2 and self._dialogue_implies_two_speakers(segment.dialogue_lines):
            for name in canonical_names:
                if name not in augmented:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break

        return augmented

    def _normalize_frame_characters_for_segment(
        self,
        *,
        frame_position: str,
        raw_names: list[str],
        prompt_text: str,
        frame_context_text: str,
        resolved_names: list[str],
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> list[str]:
        frame_names: list[str] = []
        for raw_name in raw_names:
            resolved = self._resolve_character_alias(
                raw_name=raw_name,
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )
            if resolved and resolved in resolved_names and resolved not in frame_names:
                frame_names.append(resolved)

        context_names = self._extract_visible_frame_names(frame_context_text, resolved_names)
        if frame_position != "mid" and frame_names:
            return frame_names
        if context_names:
            return context_names

        prompt_names = self._extract_visible_frame_names(prompt_text, resolved_names)
        if prompt_names:
            return prompt_names

        if frame_names:
            return frame_names

        if len(resolved_names) == 1:
            return list(resolved_names)
        return []

    def _frame_context_text(
        self,
        segment: VideoSegmentSchema,
        frame_position: str,
    ) -> str:
        timed_context = self._select_timed_beat_for_frame(
            segment.timed_beats,
            segment.duration_seconds,
            frame_position,
        )
        if timed_context:
            return timed_context
        if frame_position == "start":
            return segment.start_frame_prompt
        if frame_position == "mid":
            return segment.mid_frame_prompt
        return segment.end_frame_prompt

    def _select_timed_beat_for_frame(
        self,
        timed_beats: list[str],
        duration_seconds: int,
        frame_position: str,
    ) -> str:
        if not timed_beats:
            return ""

        target_time = 0.0
        if frame_position == "mid":
            target_time = max(0.0, duration_seconds / 2)
        elif frame_position == "end":
            target_time = max(0.0, duration_seconds - 0.1)

        parsed_ranges: list[tuple[float, float, str]] = []
        for item in timed_beats:
            match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*[-~—–]\s*(\d+(?:\.\d+)?)",
                item,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            start = float(match.group(1))
            end = float(match.group(2))
            if end < start:
                start, end = end, start
            parsed_ranges.append((start, end, item))

        for start, end, item in parsed_ranges:
            if start <= target_time <= end:
                return item

        if frame_position == "start":
            return timed_beats[0]
        if frame_position == "end":
            return timed_beats[-1]
        return timed_beats[len(timed_beats) // 2]

    def _extract_visible_frame_names(
        self,
        text: str,
        candidate_names: list[str],
    ) -> list[str]:
        cleaned_text = self._remove_frame_character_roster_text(text)
        visible_names: list[str] = []
        for name in candidate_names:
            if name not in cleaned_text:
                continue
            if self._name_has_visible_frame_evidence(cleaned_text, name):
                visible_names.append(name)
        return visible_names

    def _remove_frame_character_roster_text(self, text: str) -> str:
        return re.sub(
            r"(?:当前帧出镜角色|角色)\s*[:：]\s*[^，。；;]*[，。；;]?",
            "",
            text,
        )

    def _name_has_visible_frame_evidence(self, text: str, name: str) -> bool:
        escaped_name = re.escape(name)
        visible_after = (
            "独自|在|站|坐|走|跑|转身|抬头|低头|背对|面对|看着|望着|凝视|拿着|握着|"
            "出现|走近|走来|靠近|停下|开口|说|回答|回应|微笑|哭|笑|伸手|牵|拥抱|亲吻|吻|进入|离开"
        )
        visible_before = (
            "镜头聚焦|画面聚焦|画面出现|看见|看到|只见|出现|走来|走近|靠近|站在|坐在|"
            "背对镜头|面对镜头|转向|拥抱|亲吻|牵着"
        )
        if re.search(rf"{escaped_name}.{{0,14}}(?:{visible_after})", text):
            return True
        if re.search(rf"(?:{visible_before}).{{0,14}}{escaped_name}", text):
            return True

        non_visible_object = (
            "等待|等着|等|想起|回忆|怀念|想念|寻找|找|期待|盼着|盼望|望向|看向|听到|听见"
        )
        if re.search(rf"(?:{non_visible_object}).{{0,8}}{escaped_name}", text):
            return False
        return True

    def _frame_text_requires_group(self, text: str) -> bool:
        group_keywords = (
            "两人",
            "双方",
            "彼此",
            "一起",
            "同时",
            "同框",
            "对视",
            "对话",
            "交谈",
            "争吵",
            "对峙",
            "拥抱",
            "牵手",
            "亲吻",
            "接吻",
            "并肩",
        )
        return any(keyword in text for keyword in group_keywords)

    def _extract_dialogue_speakers(self, dialogue_lines: list[str]) -> list[str]:
        speakers: list[str] = []
        for line in dialogue_lines:
            speaker, separator, _ = line.partition("：")
            if not separator:
                speaker, separator, _ = line.partition(":")
            if not separator:
                continue
            normalized = re.sub(r"[（(].*?[）)]", "", speaker).strip()
            if normalized and normalized not in speakers:
                speakers.append(normalized)
        return speakers

    def _looks_like_two_person_scene(self, text: str) -> bool:
        keywords = (
            "告白",
            "表白",
            "对视",
            "对话",
            "争吵",
            "质问",
            "审问",
            "谈判",
            "拥抱",
            "牵手",
            "亲吻",
            "并肩",
            "对峙",
        )
        return any(keyword in text for keyword in keywords)

    def _dialogue_implies_two_speakers(self, dialogue_lines: list[str]) -> bool:
        if len(dialogue_lines) >= 2:
            return True
        if not dialogue_lines:
            return False
        line = dialogue_lines[0]
        return "你" in line or "她" in line or "他" in line

    def _replace_character_aliases(self, text: str, alias_map: dict[str, str]) -> str:
        updated = text
        for alias, actual_name in alias_map.items():
            if alias and actual_name:
                updated = updated.replace(alias, actual_name)
        return updated

    def _replace_character_aliases_in_scene_bible(
        self,
        scene_bible: SceneBibleSchema,
        alias_map: dict[str, str],
    ) -> SceneBibleSchema:
        payload = scene_bible.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return SceneBibleSchema.model_validate(repaired_payload)

    def _replace_character_aliases_in_shot_state(
        self,
        shot_state: ShotStateSchema,
        alias_map: dict[str, str],
    ) -> ShotStateSchema:
        payload = shot_state.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return ShotStateSchema.model_validate(repaired_payload)

    def _replace_character_aliases_in_continuity_link(
        self,
        continuity_link: ContinuityLinkSchema,
        alias_map: dict[str, str],
    ) -> ContinuityLinkSchema:
        payload = continuity_link.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return ContinuityLinkSchema.model_validate(repaired_payload)

    def _scene_bible_value_has_signal(self, value: object) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(str(item).strip() for item in value)
        return value is not None

    def _shot_state_value_has_signal(self, value: object) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(str(item).strip() for item in value)
        return value is not None

    def _continuity_statement_too_generic(self, text: str) -> bool:
        normalized = self._normalize_similarity_text(text)
        if not normalized:
            return True
        reduced = normalized
        for token in (
            "开场",
            "开头",
            "继续",
            "承接",
            "延续",
            "上一段",
            "上一镜头",
            "上一片段",
            "尾部",
            "尾帧",
            "状态",
            "镜头",
            "画面",
            "保持",
            "一致",
            "跟上",
        ):
            reduced = reduced.replace(token, "")
        return len(reduced) < 6

    def _normalize_similarity_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())

    def _text_ngrams(self, value: str) -> set[str]:
        normalized = self._normalize_similarity_text(value)
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

    def _text_overlap_ratio(self, left: str, right: str) -> float:
        left_grams = self._text_ngrams(left)
        right_grams = self._text_ngrams(right)
        if not left_grams or not right_grams:
            return 0.0
        return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))
