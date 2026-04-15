from __future__ import annotations

import re

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
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
        fallback_map = {
            item.name: item
            for item in self._fallback_character_visual_bible(novel_package).characters
        }
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

        for name in canonical_names:
            repaired.setdefault(name, fallback_map[name])

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
        fallback_plan = self._fallback_segment_plan(novel_package, visual_bible)
        fallback_by_chapter = self._group_segments_by_chapter(fallback_plan.segments)
        valid_chapters = {chapter.number for chapter in novel_package.outline.chapters}
        original_by_chapter = self._group_segments_by_chapter(
            [
                item
                for item in plan.segments
                if item.chapter_number in valid_chapters
            ]
        )

        repaired_segments: list[VideoSegmentSchema] = []
        for chapter in novel_package.outline.chapters:
            chosen = list(original_by_chapter.get(chapter.number, []))
            if chosen:
                repaired_segments.extend(chosen)
                continue

            fallback_segments = fallback_by_chapter.get(chapter.number, [])
            if fallback_segments:
                repaired_segments.append(fallback_segments[0])

        return VideoSegmentPlanSchema(segments=repaired_segments)

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
                resolved_names = self._fallback_segment_characters(
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
                        "title": self._replace_character_aliases(segment.title, alias_map),
                        "involved_characters": resolved_names,
                        "start_frame_characters": self._normalize_frame_characters_for_segment(
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
                        "scene_prompt": self._replace_character_aliases(segment.scene_prompt, alias_map),
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
            featured = self._fallback_segment_characters(
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
            featured = self._fallback_segment_characters(
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

    def _fallback_segment_characters(
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
                segment.scene_prompt,
                segment.start_frame_prompt,
                segment.end_frame_prompt,
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
        if context_names:
            return context_names

        prompt_names = self._extract_visible_frame_names(prompt_text, resolved_names)
        if prompt_names:
            return prompt_names

        if len(frame_names) == 1:
            return frame_names
        if len(frame_names) > 1 and self._frame_text_requires_group(
            " ".join([prompt_text, frame_context_text])
        ):
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
