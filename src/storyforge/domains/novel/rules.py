from __future__ import annotations

import re
from typing import Any

from storyforge.domains.novel.contracts import StoryBrief
from storyforge.domains.novel.heuristics import (
    brief_prefers_male_female_pair,
    brief_requires_dual_leads,
    brief_requires_explicit_counterpart,
    build_brief_text,
    extract_role_labels_from_brief,
    infer_primary_character_genders,
    text_requires_explicit_counterpart,
    text_requires_multiple_core_characters,
)
from storyforge.domains.novel.schemas import CastAnalysisSchema, StoryDraftSetSchema


class NovelRuleMixin:
    def _story_draft_text(
        self,
        story_draft_set: StoryDraftSetSchema | None,
    ) -> str:
        if story_draft_set is None:
            return ""
        return "\n".join(
            f"{item.title}\n{item.summary}\n{item.markdown}"
            for item in story_draft_set.chapters
        ).strip()

    def _minimum_core_character_count(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> int:
        if cast_analysis is not None:
            return max(1, cast_analysis.recommended_core_cast_count)

        extracted_role_count = len(extract_role_labels_from_brief(brief, limit=6))
        baseline = 2 if self._text_requires_multiple_core_characters(build_brief_text(brief)) else 1
        return max(baseline, extracted_role_count)

    def _repair_primary_character_genders(
        self,
        characters: list[Any],
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> list[Any]:
        if len(characters) < 2 or not self._brief_prefers_male_female_pair(
            brief,
            cast_analysis,
        ):
            return characters

        first = characters[0]
        second = characters[1]
        expected_pair = self._expected_primary_character_genders(
            brief,
            cast_analysis,
        )
        if expected_pair is not None:
            first_gender, second_gender = expected_pair
        else:
            first_gender = first.gender.strip()
            second_gender = second.gender.strip()

        if expected_pair is None and {first_gender, second_gender} == {"男", "女"}:
            return characters

        updated_characters = list(characters)
        if expected_pair is None:
            if first_gender not in {"男", "女"}:
                first_gender = "男"
            opposite_gender = "女" if first_gender == "男" else "男"
            if second_gender == first_gender or second_gender not in {"男", "女"}:
                second_gender = opposite_gender

        updated_characters[0] = self._update_character_gender(first, first_gender)
        updated_characters[1] = self._update_character_gender(second, second_gender)
        return updated_characters

    def _update_character_gender(self, item: Any, gender: str) -> Any:
        image_prompt = item.image_prompt.strip()
        if image_prompt:
            image_prompt = re.sub(r"性别：[^。；;!！?？]*[。；;!！?？]?", "", image_prompt).strip()
            if gender not in image_prompt:
                image_prompt = f"{image_prompt} 性别：{gender}。".strip()
        return item.model_copy(update={"gender": gender, "image_prompt": image_prompt})

    def _text_requires_multiple_core_characters(self, text: str) -> bool:
        return text_requires_multiple_core_characters(text)

    def _text_requires_explicit_counterpart(self, text: str) -> bool:
        return text_requires_explicit_counterpart(text)

    def _brief_prefers_male_female_pair(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> bool:
        if cast_analysis is not None:
            return cast_analysis.prefers_male_female_pair
        return brief_prefers_male_female_pair(brief)

    def _brief_requires_dual_leads(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> bool:
        if cast_analysis is not None:
            return cast_analysis.requires_dual_leads
        return brief_requires_dual_leads(brief)

    def _brief_requires_explicit_counterpart(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> bool:
        if cast_analysis is not None:
            return cast_analysis.explicit_counterpart
        return brief_requires_explicit_counterpart(brief)

    def _expected_primary_character_genders(
        self,
        brief: StoryBrief,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> tuple[str, str] | None:
        if cast_analysis is not None:
            primary_slots = cast_analysis.primary_slots(2)
            if len(primary_slots) >= 2:
                first_gender = self._normalize_gender_hint(primary_slots[0].gender_hint)
                second_gender = self._normalize_gender_hint(primary_slots[1].gender_hint)
            else:
                first_gender = ""
                second_gender = ""
            if first_gender and second_gender:
                return first_gender, second_gender
        return infer_primary_character_genders(brief)

    def _normalize_gender_hint(self, value: str) -> str:
        token = value.strip()
        if token in {"男", "女"}:
            return token
        return ""
