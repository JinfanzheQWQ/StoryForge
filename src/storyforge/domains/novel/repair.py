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
        fallback = self._fallback_story_draft_set(brief, architecture)
        repaired: list[ChapterDraftSchema] = []

        for index in range(brief.chapter_count):
            fallback_item = fallback.chapters[index]
            current_item = (
                story_draft_set.chapters[index]
                if index < len(story_draft_set.chapters)
                else fallback_item
            )
            repaired.append(
                current_item.model_copy(
                    update={
                        "number": index + 1,
                        "title": current_item.title.strip() or fallback_item.title,
                        "summary": current_item.summary.strip() or fallback_item.summary,
                        "markdown": current_item.markdown.strip() or fallback_item.markdown,
                        "visual_hooks": current_item.visual_hooks or fallback_item.visual_hooks,
                        "continuity_refs": current_item.continuity_refs or fallback_item.continuity_refs,
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
        fallback = self._fallback_cast_analysis(
            brief,
            architecture,
            story_draft_set=story_draft_set,
        )
        story_shape = analysis.story_shape.strip() or fallback.story_shape
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
        recommended_core_cast_count = max(
            1,
            analysis.recommended_core_cast_count,
            fallback.recommended_core_cast_count,
        )
        prefers_male_female_pair = (
            analysis.prefers_male_female_pair
            or self._brief_prefers_male_female_pair(brief, analysis)
        )
        expected_pair = self._expected_primary_character_genders(brief, analysis)

        repaired_slots = self._repair_cast_slots(
            analysis.slots,
            fallback.slots,
            recommended_core_cast_count=recommended_core_cast_count,
            explicit_counterpart=explicit_counterpart,
            expected_pair=expected_pair,
        )
        repaired_relationships = self._repair_cast_relationships(
            analysis.relationships,
            repaired_slots,
            fallback.relationships,
        )

        cast_strategy = analysis.cast_strategy.strip() or fallback.cast_strategy
        chapter_participation_rule = (
            analysis.chapter_participation_rule.strip() or fallback.chapter_participation_rule
        )
        ordering_rule = analysis.ordering_rule.strip() or fallback.ordering_rule

        return analysis.model_copy(
            update={
                "story_shape": story_shape,
                "recommended_core_cast_count": recommended_core_cast_count,
                "requires_dual_leads": requires_dual_leads,
                "explicit_counterpart": explicit_counterpart,
                "prefers_male_female_pair": prefers_male_female_pair,
                "cast_strategy": cast_strategy,
                "chapter_participation_rule": chapter_participation_rule,
                "ordering_rule": ordering_rule,
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
        fallback_slots: list[CastSlotSchema],
        *,
        recommended_core_cast_count: int,
        explicit_counterpart: bool,
        expected_pair: tuple[str, str] | None,
    ) -> list[CastSlotSchema]:
        repaired: list[CastSlotSchema] = []
        seen_slot_ids: set[str] = set()

        for index, slot in enumerate(slots):
            fallback_slot = fallback_slots[index % len(fallback_slots)]
            slot_id = slot.slot_id.strip() or fallback_slot.slot_id
            if slot_id in seen_slot_ids:
                continue
            brief_label = slot.brief_label.strip() or fallback_slot.brief_label
            source_evidence = slot.source_evidence or fallback_slot.source_evidence or [brief_label]
            tier = slot.tier.strip() or fallback_slot.tier
            story_function = slot.story_function.strip() or fallback_slot.story_function
            objective = slot.objective.strip() or fallback_slot.objective
            gender_hint = slot.gender_hint.strip() or fallback_slot.gender_hint
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
                        "order_priority": max(1, slot.order_priority or fallback_slot.order_priority),
                        "must_appear_in": slot.must_appear_in or fallback_slot.must_appear_in,
                        "notes": slot.notes.strip() or fallback_slot.notes,
                    }
                )
            )
            seen_slot_ids.add(slot_id)

        for fallback_slot in fallback_slots:
            if len(repaired) >= recommended_core_cast_count:
                break
            if fallback_slot.slot_id in seen_slot_ids:
                continue
            repaired.append(fallback_slot)
            seen_slot_ids.add(fallback_slot.slot_id)

        repaired.sort(key=lambda item: (item.order_priority, item.slot_id))
        if explicit_counterpart and len(repaired) >= 2:
            repaired[0] = repaired[0].model_copy(update={"tier": "lead"})
            repaired[1] = repaired[1].model_copy(update={"tier": "lead"})
        return repaired

    def _repair_cast_relationships(
        self,
        relationships: list[CastRelationshipSchema],
        slots: list[CastSlotSchema],
        fallback_relationships: list[CastRelationshipSchema],
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

        for item in fallback_relationships:
            key = (item.source_slot_id, item.target_slot_id, item.relationship_type)
            if key in seen_pairs:
                continue
            if item.source_slot_id not in valid_slot_ids or item.target_slot_id not in valid_slot_ids:
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
        fallback = self._fallback_character_roster(
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )
        minimum_count = self._minimum_core_character_count(brief, cast_analysis)
        repaired = []
        seen_names: set[str] = set()

        for index, item in enumerate(roster.characters):
            fallback_item = fallback.characters[index % len(fallback.characters)]
            cast_slot_id = item.cast_slot_id.strip() or fallback_item.cast_slot_id
            name = item.name.strip() or fallback_item.name
            if name in seen_names:
                continue
            gender = item.gender.strip() or fallback_item.gender
            image_prompt = item.image_prompt.strip() or fallback_item.image_prompt
            if gender not in image_prompt:
                image_prompt = f"{image_prompt} 性别：{gender}。"
            repaired.append(
                item.model_copy(
                    update={
                        "cast_slot_id": cast_slot_id,
                        "name": name,
                        "gender": gender,
                        "image_prompt": image_prompt,
                    }
                )
            )
            seen_names.add(name)

        for fallback_item in fallback.characters:
            if len(repaired) >= minimum_count:
                break
            if fallback_item.name in seen_names:
                continue
            repaired.append(fallback_item)
            seen_names.add(fallback_item.name)

        repaired = self._repair_primary_character_genders(
            repaired,
            brief,
            cast_analysis,
        )
        repaired = self._repair_primary_character_roles(
            repaired,
            brief,
            fallback,
            cast_analysis,
        )
        repaired = self._repair_cast_slot_alignment(repaired, fallback)

        return CharacterRosterSchema(characters=repaired)

    def _repair_chapter_plan_set(
        self,
        chapter_plan_set: ChapterPlanSetSchema,
        brief: StoryBrief,
        character_roster: CharacterRosterSchema,
        cast_analysis: CastAnalysisSchema | None = None,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> ChapterPlanSetSchema:
        fallback = self._fallback_chapter_plan_set(
            brief,
            character_roster,
            cast_analysis=cast_analysis,
            story_draft_set=story_draft_set,
        )
        canonical_names = [item.name for item in character_roster.characters]
        role_map = {item.name: item.role for item in character_roster.characters}
        minimum_featured_count = min(len(canonical_names), self._minimum_featured_character_count(brief, cast_analysis))
        repaired_chapters = []
        requires_explicit_counterpart = self._brief_requires_explicit_counterpart(
            brief,
            cast_analysis,
        )
        primary_pair = canonical_names[: max(1, minimum_featured_count)]
        draft_by_number = {
            item.number: item for item in (story_draft_set.chapters if story_draft_set is not None else [])
        }

        source_items = chapter_plan_set.chapters or fallback.chapters
        for index, chapter in enumerate(source_items):
            fallback_chapter = fallback.chapters[index % len(fallback.chapters)]
            source_chapter = draft_by_number.get(chapter.number)
            featured: list[str] = []
            for raw_name in chapter.featured_characters:
                resolved = self._resolve_roster_name(raw_name, canonical_names, role_map)
                if resolved and resolved not in featured:
                    featured.append(resolved)

            if not featured:
                featured = canonical_names[: max(1, minimum_featured_count)]

            combined_text = " ".join(
                [
                    chapter.title,
                    chapter.goal,
                    chapter.summary,
                    chapter.key_conflict,
                    chapter.cliffhanger,
                    *chapter.beats,
                ]
            )
            if requires_explicit_counterpart and len(featured) < minimum_featured_count:
                for name in primary_pair:
                    if name not in featured:
                        featured.append(name)
                    if len(featured) >= minimum_featured_count:
                        break
            elif (
                self._text_requires_multiple_core_characters(combined_text)
                and len(featured) < minimum_featured_count
            ):
                for name in canonical_names:
                    if name not in featured:
                        featured.append(name)
                    if len(featured) >= minimum_featured_count:
                        break

            repaired_chapters.append(
                chapter.model_copy(
                    update={
                        "number": index + 1,
                        "title": chapter.title.strip() or (source_chapter.title if source_chapter is not None else fallback_chapter.title),
                        "summary": chapter.summary.strip() or (source_chapter.summary if source_chapter is not None else fallback_chapter.summary),
                        "goal": chapter.goal.strip() or fallback_chapter.goal,
                        "key_conflict": chapter.key_conflict.strip() or fallback_chapter.key_conflict,
                        "beats": chapter.beats or fallback_chapter.beats,
                        "cliffhanger": chapter.cliffhanger.strip() or fallback_chapter.cliffhanger,
                        "featured_characters": featured,
                    }
                )
            )

        for index in range(len(repaired_chapters), brief.chapter_count):
            repaired_chapters.append(fallback.chapters[index])

        return ChapterPlanSetSchema(chapters=repaired_chapters[: brief.chapter_count])

    def _repair_primary_character_roles(
        self,
        characters: list,
        brief: StoryBrief,
        fallback: CharacterRosterSchema,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> list:
        if len(characters) < 2 or not self._brief_requires_explicit_counterpart(
            brief,
            cast_analysis,
        ):
            return characters

        generic_roles = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "对手 / 镜像角色",
            "关键对位角色",
        }
        repaired = list(characters)

        for index in range(2):
            item = repaired[index]
            fallback_item = fallback.characters[index]
            role = item.role.strip() or fallback_item.role
            if role in generic_roles:
                role = fallback_item.role

            image_prompt = item.image_prompt.strip() or fallback_item.image_prompt
            role_marker = f"关系定位：{role}"
            if role and role_marker not in image_prompt:
                image_prompt = f"{image_prompt} {role_marker}。".strip()

            repaired[index] = item.model_copy(
                update={
                    "role": role,
                    "image_prompt": image_prompt,
                }
            )

        return repaired

    def _repair_cast_slot_alignment(
        self,
        characters: list,
        fallback: CharacterRosterSchema,
    ) -> list:
        repaired = list(characters)
        for index, item in enumerate(repaired):
            fallback_item = fallback.characters[index % len(fallback.characters)]
            cast_slot_id = item.cast_slot_id.strip() or fallback_item.cast_slot_id
            repaired[index] = item.model_copy(update={"cast_slot_id": cast_slot_id})
        return repaired

    def _minimum_featured_character_count(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> int:
        if self._brief_requires_explicit_counterpart(brief, cast_analysis):
            return 2
        if self._brief_requires_dual_leads(brief, cast_analysis):
            return 2
        return 1

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
