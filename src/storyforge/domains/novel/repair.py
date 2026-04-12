from __future__ import annotations

from storyforge.domains.novel.contracts import StoryBrief
from storyforge.domains.novel.schemas import (
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    StoryArchitectureSchema,
)


class NovelRepairMixin:
    def _repair_character_roster(
        self,
        roster: CharacterRosterSchema,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
    ) -> CharacterRosterSchema:
        fallback = self._fallback_character_roster(brief, architecture)
        minimum_count = self._minimum_core_character_count(brief)
        repaired = []
        seen_names: set[str] = set()

        for index, item in enumerate(roster.characters):
            fallback_item = fallback.characters[index % len(fallback.characters)]
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

        repaired = self._repair_primary_character_genders(repaired, brief)

        return CharacterRosterSchema(characters=repaired)

    def _repair_chapter_plan_set(
        self,
        chapter_plan_set: ChapterPlanSetSchema,
        brief: StoryBrief,
        character_roster: CharacterRosterSchema,
    ) -> ChapterPlanSetSchema:
        canonical_names = [item.name for item in character_roster.characters]
        role_map = {item.name: item.role for item in character_roster.characters}
        minimum_featured_count = min(
            len(canonical_names),
            self._minimum_core_character_count(brief),
        )
        repaired_chapters = []

        for chapter in chapter_plan_set.chapters:
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
            if (
                self._text_requires_multiple_core_characters(combined_text)
                and len(featured) < minimum_featured_count
            ):
                for name in canonical_names:
                    if name not in featured:
                        featured.append(name)
                    if len(featured) >= minimum_featured_count:
                        break

            repaired_chapters.append(
                chapter.model_copy(update={"featured_characters": featured})
            )

        return ChapterPlanSetSchema(chapters=repaired_chapters)

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

        generic_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "男一",
            "女一",
            "告白者",
            "被告白的人",
            "对方",
        }
        if token in generic_aliases:
            return canonical_names[0] if canonical_names else ""

        fuzzy_matches = [name for name in canonical_names if token in name or name in token]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [name for name, role in role_map.items() if token in role or role in token]
        if len(role_matches) == 1:
            return role_matches[0]
        return ""
