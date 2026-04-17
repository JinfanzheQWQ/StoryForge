from __future__ import annotations

from storyforge.domains.novel.contracts import StoryBrief
from storyforge.domains.novel.schemas import (
    CastAnalysisSchema,
    CastRelationshipSchema,
    CastSlotSchema,
    ChapterDraftSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    StoryDraftSetSchema,
    StoryArchitectureSchema,
)


class NovelRepairMixin:
    def _repair_story_draft_set(
        self,
        story_draft_set: StoryDraftSetSchema,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
    ) -> StoryDraftSetSchema:
        repaired: list[ChapterDraftSchema] = []

        for index, current_item in enumerate(
            story_draft_set.chapters[: brief.chapter_count],
            start=1,
        ):
            repaired.append(
                current_item.model_copy(
                    update={
                        "number": index,
                        "title": current_item.title.strip(),
                        "summary": current_item.summary.strip(),
                        "markdown": current_item.markdown.strip(),
                        "visual_hooks": self._normalize_text_items(current_item.visual_hooks),
                        "continuity_refs": self._normalize_text_items(current_item.continuity_refs),
                    }
                )
            )

        return StoryDraftSetSchema(chapters=repaired)

    def _repair_cast_analysis(
        self,
        analysis: CastAnalysisSchema,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> CastAnalysisSchema:
        story_shape = analysis.story_shape.strip()
        explicit_counterpart = self._resolve_explicit_counterpart_flag(
            analysis,
            brief,
            story_shape=story_shape,
            story_draft_set=story_draft_set,
        )
        requires_dual_leads = self._resolve_requires_dual_leads_flag(
            analysis,
            brief,
            story_shape=story_shape,
            explicit_counterpart=explicit_counterpart,
            story_draft_set=story_draft_set,
        )
        prefers_male_female_pair = (
            analysis.prefers_male_female_pair
            or self._brief_prefers_male_female_pair(brief, analysis)
        )
        expected_pair = self._expected_primary_character_genders(brief, analysis)
        requested_core_cast_count = max(1, analysis.recommended_core_cast_count)

        repaired_slots = self._repair_cast_slots(
            analysis.slots,
            explicit_counterpart=explicit_counterpart,
            expected_pair=expected_pair,
        )
        recommended_core_cast_count = min(requested_core_cast_count, len(repaired_slots))
        repaired_relationships = self._repair_cast_relationships(
            analysis.relationships,
            repaired_slots,
        )

        return analysis.model_copy(
            update={
                "story_shape": story_shape,
                "recommended_core_cast_count": recommended_core_cast_count,
                "requires_dual_leads": requires_dual_leads,
                "explicit_counterpart": explicit_counterpart,
                "prefers_male_female_pair": prefers_male_female_pair,
                "cast_strategy": analysis.cast_strategy.strip(),
                "chapter_participation_rule": analysis.chapter_participation_rule.strip(),
                "ordering_rule": analysis.ordering_rule.strip(),
                "slots": repaired_slots,
                "relationships": repaired_relationships,
            }
        )

    def _resolve_explicit_counterpart_flag(
        self,
        analysis: CastAnalysisSchema,
        brief: StoryBrief,
        *,
        story_shape: str,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> bool:
        if story_shape == "dual_relationship_with_supporting_cast":
            return True
        if story_shape in {"single_lead_with_supporting_cast", "ensemble"}:
            return False
        story_draft_text = self._story_draft_text(story_draft_set)
        if story_draft_text:
            return analysis.explicit_counterpart or self._text_requires_explicit_counterpart(story_draft_text)
        return analysis.explicit_counterpart or self._brief_requires_explicit_counterpart(brief)

    def _resolve_requires_dual_leads_flag(
        self,
        analysis: CastAnalysisSchema,
        brief: StoryBrief,
        *,
        story_shape: str,
        explicit_counterpart: bool,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> bool:
        if explicit_counterpart:
            return True
        if story_shape == "dual_lead_with_supporting_cast":
            return True
        if story_shape in {"single_lead_with_supporting_cast", "ensemble"}:
            return False
        story_draft_text = self._story_draft_text(story_draft_set)
        if story_draft_text:
            return analysis.requires_dual_leads or self._text_requires_multiple_core_characters(story_draft_text)
        return analysis.requires_dual_leads or self._brief_requires_dual_leads(brief)

    def _repair_cast_slots(
        self,
        slots: list[CastSlotSchema],
        *,
        explicit_counterpart: bool,
        expected_pair: tuple[str, str] | None,
    ) -> list[CastSlotSchema]:
        repaired: list[CastSlotSchema] = []
        seen_slot_ids: set[str] = set()

        for index, slot in enumerate(slots):
            slot_id = slot.slot_id.strip()
            if slot_id in seen_slot_ids:
                continue
            brief_label = slot.brief_label.strip()
            source_evidence = self._normalize_text_items(slot.source_evidence) or [brief_label]
            tier = slot.tier.strip()
            story_function = slot.story_function.strip()
            objective = slot.objective.strip()
            gender_hint = slot.gender_hint.strip()
            if expected_pair is not None and index < 2 and gender_hint not in {"男", "女"}:
                gender_hint = expected_pair[index]
            repaired.append(
                slot.model_copy(
                    update={
                        "slot_id": slot_id,
                        "brief_label": brief_label,
                        "source_evidence": source_evidence,
                        "tier": tier,
                        "story_function": story_function,
                        "objective": objective,
                        "gender_hint": gender_hint,
                        "order_priority": max(1, slot.order_priority),
                        "must_appear_in": self._normalize_text_items(slot.must_appear_in),
                        "notes": slot.notes.strip(),
                    }
                )
            )
            seen_slot_ids.add(slot_id)

        repaired.sort(key=lambda item: (item.order_priority, item.slot_id))
        if explicit_counterpart and len(repaired) >= 2:
            repaired[0] = repaired[0].model_copy(update={"tier": "lead"})
            repaired[1] = repaired[1].model_copy(update={"tier": "lead"})
        return repaired

    def _repair_cast_relationships(
        self,
        relationships: list[CastRelationshipSchema],
        slots: list[CastSlotSchema],
    ) -> list[CastRelationshipSchema]:
        valid_slot_ids = {item.slot_id for item in slots}
        repaired: list[CastRelationshipSchema] = []
        seen_pairs: set[tuple[str, str, str]] = set()

        for item in relationships:
            if item.source_slot_id not in valid_slot_ids or item.target_slot_id not in valid_slot_ids:
                continue
            key = (item.source_slot_id, item.target_slot_id, item.relationship_type)
            if key in seen_pairs:
                continue
            repaired.append(item)
            seen_pairs.add(key)

        repaired.sort(key=lambda item: item.priority)
        return repaired

    def _repair_character_roster(
        self,
        roster: CharacterRosterSchema,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> CharacterRosterSchema:
        repaired = []
        for item in roster.characters:
            gender = item.gender.strip()
            image_prompt = item.image_prompt.strip()
            if gender not in image_prompt:
                image_prompt = f"{image_prompt} 性别：{gender}。"
            repaired.append(
                item.model_copy(
                    update={
                        "cast_slot_id": item.cast_slot_id.strip(),
                        "name": item.name.strip(),
                        "role": item.role.strip(),
                        "gender": gender,
                        "desire": item.desire.strip(),
                        "conflict": item.conflict.strip(),
                        "arc": item.arc.strip(),
                        "visual_signature": self._normalize_text_items(item.visual_signature),
                        "voice_style": item.voice_style.strip(),
                        "image_prompt": image_prompt,
                    }
                )
            )

        repaired = self._repair_primary_character_genders(
            repaired,
            brief,
            cast_analysis,
        )
        return CharacterRosterSchema(characters=repaired)

    def _repair_chapter_plan_set(
        self,
        chapter_plan_set: ChapterPlanSetSchema,
        brief: StoryBrief,
        character_roster: CharacterRosterSchema,
        cast_analysis: CastAnalysisSchema | None = None,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> ChapterPlanSetSchema:
        canonical_names = [item.name for item in character_roster.characters]
        role_map = {item.name: item.role for item in character_roster.characters}
        repaired_chapters = []
        source_items = chapter_plan_set.chapters[: brief.chapter_count]
        for index, chapter in enumerate(source_items):
            featured: list[str] = []
            for raw_name in chapter.featured_characters:
                resolved = self._resolve_roster_name(raw_name, canonical_names, role_map)
                if resolved and resolved not in featured:
                    featured.append(resolved)

            repaired_chapters.append(
                chapter.model_copy(
                    update={
                        "number": index + 1,
                        "title": chapter.title.strip(),
                        "summary": chapter.summary.strip(),
                        "goal": chapter.goal.strip(),
                        "key_conflict": chapter.key_conflict.strip(),
                        "beats": self._normalize_text_items(chapter.beats),
                        "cliffhanger": chapter.cliffhanger.strip(),
                        "featured_characters": featured,
                    }
                )
            )

        return ChapterPlanSetSchema(chapters=repaired_chapters[: brief.chapter_count])

    def _resolve_roster_name(
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

        lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "男一",
            "女一",
            "告白者",
            "主动方",
            "发起者",
        }
        if token in lead_aliases:
            return canonical_names[0] if canonical_names else ""

        counterpart_aliases = {
            "被告白的人",
            "被表白的人",
            "对方",
            "另一方",
            "回应方",
            "被回应的人",
        }
        if token in counterpart_aliases:
            if len(canonical_names) >= 2:
                return canonical_names[1]
            return canonical_names[0] if canonical_names else ""

        fuzzy_matches = [name for name in canonical_names if token in name or name in token]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [name for name, role in role_map.items() if token in role or role in token]
        if len(role_matches) == 1:
            return role_matches[0]
        return ""

    def _normalize_text_items(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            token = value.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized
