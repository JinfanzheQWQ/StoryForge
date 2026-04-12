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

        generic_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主角团",
            "神秘人",
            "录音师",
            "修复师",
        }
        if token in generic_aliases:
            return canonical_names[0]

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
        }
        if token.lower() in generic_lead_aliases or token in generic_lead_aliases:
            featured = self._fallback_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            return featured[0] if featured else ""

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
