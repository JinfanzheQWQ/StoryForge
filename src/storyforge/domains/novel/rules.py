from __future__ import annotations

import re
from typing import Any

from storyforge.domains.novel.contracts import StoryBrief


class NovelRuleMixin:
    def _minimum_core_character_count(self, brief: StoryBrief) -> int:
        return 2 if self._text_requires_multiple_core_characters(self._brief_text(brief)) else 1

    def _repair_primary_character_genders(
        self,
        characters: list[Any],
        brief: StoryBrief,
    ) -> list[Any]:
        if len(characters) < 2 or not self._brief_prefers_male_female_pair(brief):
            return characters

        first = characters[0]
        second = characters[1]
        first_gender = first.gender.strip()
        second_gender = second.gender.strip()

        if {first_gender, second_gender} == {"男", "女"}:
            return characters

        updated_characters = list(characters)
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

    def _brief_text(self, brief: StoryBrief) -> str:
        return " ".join(
            [
                brief.title_hint,
                brief.idea,
                brief.genre,
                brief.tone,
                " ".join(brief.must_include),
                " ".join(brief.style_keywords),
            ]
        )

    def _text_requires_multiple_core_characters(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        keywords = (
            "告白",
            "表白",
            "暗恋",
            "恋人",
            "情侣",
            "前任",
            "重逢",
            "求婚",
            "情书",
            "约会",
            "夫妻",
            "对峙",
            "争吵",
            "谈判",
            "审问",
            "质问",
            "双人",
            "对话",
            "母女",
            "父子",
            "姐妹",
            "兄弟",
            "师徒",
        )
        return any(keyword in compact for keyword in keywords)

    def _brief_prefers_male_female_pair(self, brief: StoryBrief) -> bool:
        if not self._text_requires_multiple_core_characters(self._brief_text(brief)):
            return False
        text = self._brief_text(brief).lower()
        same_gender_keywords = (
            "双男",
            "双女",
            "男男",
            "女女",
            "耽美",
            "百合",
            "bl",
            "gl",
            "同性",
            "男同",
            "女同",
        )
        return not any(keyword in text for keyword in same_gender_keywords)
