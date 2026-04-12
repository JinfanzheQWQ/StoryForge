from __future__ import annotations

from itertools import cycle
import re
from typing import Any, TypeVar

from pydantic import BaseModel

from storyforge.agents.base import AgentBackend, DryRunAgentBackend, PromptRequest
from storyforge.domains.novel.contracts import (
    ChapterPlan,
    CharacterProfile,
    CharacterVoiceProfile,
    DraftChapter,
    EditorialReview,
    NovelPackage,
    StoryBrief,
    StoryOutline,
)
from storyforge.domains.novel.prompts import (
    build_architect_system_prompt,
    build_architect_user_prompt,
    build_character_system_prompt,
    build_character_user_prompt,
    build_chapter_planner_system_prompt,
    build_chapter_planner_user_prompt,
    build_editor_system_prompt,
    build_editor_user_prompt,
    build_writer_system_prompt,
    build_writer_user_prompt,
)
from storyforge.domains.novel.schemas import (
    ChapterDraftSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    CharacterVoiceProfileSchema,
    EditorialReviewSchema,
    StoryArchitectureSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
DEFAULT_CHARACTER_NAMES = ["林雾", "沈砚", "周遥", "许舟", "秦岚", "顾屿"]


class NovelGeneratorService:
    def __init__(
        self,
        backend: AgentBackend | None = None,
        chapter_scene_count: int = 3,
        major_character_count: int = 3,
    ) -> None:
        self.backend = backend or DryRunAgentBackend()
        self.chapter_scene_count = chapter_scene_count
        self.major_character_count = major_character_count

    def build_novel_package(self, brief: StoryBrief) -> NovelPackage:
        architecture = self._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt=build_architect_system_prompt(),
                user_prompt=build_architect_user_prompt(brief),
                metadata={"task": "story-architect"},
            ),
            fallback=self._fallback_architecture(brief),
        )

        character_roster = self._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt=build_character_system_prompt(),
                user_prompt=build_character_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                ),
                metadata={"task": "character-designer"},
            ),
            fallback=self._fallback_character_roster(brief, architecture),
        )
        character_roster = self._repair_character_roster(
            character_roster,
            brief,
            architecture,
        )

        chapter_plan_set = self._run_structured_agent(
            schema=ChapterPlanSetSchema,
            request=PromptRequest(
                system_prompt=build_chapter_planner_system_prompt(),
                user_prompt=build_chapter_planner_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                    character_summary=character_roster.model_dump_json(ensure_ascii=False),
                ),
                metadata={"task": "chapter-planner"},
            ),
            fallback=self._fallback_chapter_plan_set(brief, character_roster),
        )
        chapter_plan_set = self._repair_chapter_plan_set(
            chapter_plan_set,
            brief,
            character_roster,
        )

        outline = self._assemble_outline(architecture, character_roster, chapter_plan_set)
        chapters = self._build_chapters(brief, outline)
        review = self._run_structured_agent(
            schema=EditorialReviewSchema,
            request=PromptRequest(
                system_prompt=build_editor_system_prompt(),
                user_prompt=build_editor_user_prompt(brief, outline, chapters),
                metadata={"task": "editor-review"},
            ),
            fallback=self._fallback_editorial_review(outline, chapters),
        )

        return NovelPackage(
            brief=brief,
            outline=outline,
            chapters=chapters,
            review=EditorialReview(
                overall_verdict=review.overall_verdict,
                strengths=review.strengths,
                continuity_risks=review.continuity_risks,
                revision_notes=review.revision_notes,
            ),
            workflow_trace={
                "story_architect": architecture.model_dump(),
                "character_designer": character_roster.model_dump(),
                "chapter_planner": chapter_plan_set.model_dump(),
                "editor_review": review.model_dump(),
            },
        )

    def _assemble_outline(
        self,
        architecture: StoryArchitectureSchema,
        roster: CharacterRosterSchema,
        chapter_plan_set: ChapterPlanSetSchema,
    ) -> StoryOutline:
        return StoryOutline(
            title=architecture.title,
            premise=architecture.premise,
            theme=architecture.theme,
            visual_motifs=architecture.visual_motifs,
            characters=[
                CharacterProfile(
                    name=item.name,
                    role=item.role,
                    gender=item.gender,
                    desire=item.desire,
                    conflict=item.conflict,
                    arc=item.arc,
                    visual_signature=item.visual_signature,
                    voice_style=item.voice_style or item.voice_profile.voice_style,
                    voice_profile=CharacterVoiceProfile.from_dict(
                        item.voice_profile.model_dump()
                    ),
                    image_prompt=item.image_prompt,
                )
                for item in roster.characters
            ],
            chapters=[
                ChapterPlan(
                    number=item.number,
                    title=item.title,
                    summary=item.summary,
                    key_conflict=item.key_conflict,
                    beats=item.beats,
                    cliffhanger=item.cliffhanger,
                    goal=item.goal,
                    featured_characters=item.featured_characters,
                )
                for item in chapter_plan_set.chapters
            ],
            agent_notes=(
                f"setting={architecture.setting}\n"
                f"story_engine={architecture.story_engine}\n"
                f"tone_notes={', '.join(architecture.tone_notes)}"
            ),
        )

    def _build_chapters(self, brief: StoryBrief, outline: StoryOutline) -> list[DraftChapter]:
        drafted: list[DraftChapter] = []
        for chapter in outline.chapters:
            chapter_payload = self._run_structured_agent(
                schema=ChapterDraftSchema,
                request=PromptRequest(
                    system_prompt=build_writer_system_prompt(),
                    user_prompt=build_writer_user_prompt(
                        brief=brief,
                        outline=outline,
                        chapter=chapter,
                        previous_chapters=drafted,
                    ),
                    metadata={"task": f"chapter-writer-{chapter.number:02d}"},
                ),
                fallback=self._fallback_chapter_draft(brief, outline, chapter),
            )
            drafted.append(
                DraftChapter(
                    number=chapter_payload.number,
                    title=chapter_payload.title,
                    markdown=chapter_payload.markdown,
                    summary=chapter_payload.summary,
                    agent_notes=f"goal={chapter.goal}",
                    visual_hooks=chapter_payload.visual_hooks,
                    continuity_refs=chapter_payload.continuity_refs,
                )
            )
        return drafted

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        fallback: StructuredModelT,
    ) -> StructuredModelT:
        # Dry-run and network-less environments still need to produce a full pipeline,
        # so any structured agent failure cleanly falls back to deterministic output.
        if isinstance(self.backend, DryRunAgentBackend):
            return fallback
        try:
            response = self.backend.generate_structured(request, schema)
            if isinstance(response, schema):
                return response
            return schema.model_validate(response)
        except Exception:
            return fallback

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

    def _fallback_architecture(self, brief: StoryBrief) -> StoryArchitectureSchema:
        motifs = brief.style_keywords or ["雾气", "回声", "霓虹"]
        return StoryArchitectureSchema(
            title=brief.title_hint,
            premise=f"{brief.idea} 这部小说围绕一场不断扩大的秘密展开。",
            theme=f"在 {brief.tone} 的氛围里讨论记忆、代价与选择。",
            setting="一座具有强视觉辨识度的城市或封闭区域，旧设施与新技术并存。",
            story_engine="主角每获得一条线索，就会引出更危险的新问题，迫使关系和局势持续升级。",
            visual_motifs=motifs,
            tone_notes=[brief.tone, "镜头感", "悬念递进"],
        )

    def _fallback_character_roster(
        self,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
    ) -> CharacterRosterSchema:
        names = cycle(DEFAULT_CHARACTER_NAMES)
        roles = [
            "主角",
            "对手 / 镜像角色",
            "盟友 / 情感支点",
            "关键证人",
            "幕后操盘者",
        ]
        genders = ["男", "女", "女", "男", "未指定"]
        characters = []
        for _ in range(self.major_character_count):
            name = next(names)
            role = roles[len(characters) % len(roles)]
            gender = genders[len(characters) % len(genders)]
            voice_profile = self._build_fallback_voice_profile(
                brief=brief,
                role=role,
            )
            characters.append(
                {
                    "name": name,
                    "role": role,
                    "gender": gender,
                    "desire": f"解开与《{brief.title_hint}》主线相关的真相",
                    "conflict": "越接近真相，代价越大，关系也越难维系。",
                    "arc": "从试探和保留，逐步走向主动承担。",
                    "visual_signature": list(architecture.visual_motifs[:2]) + [brief.genre],
                    "voice_style": voice_profile.voice_style,
                    "voice_profile": voice_profile.model_dump(),
                    "image_prompt": (
                        f"{name}，{gender}，{role}，青年到中青年年龄段，{brief.tone}，"
                        f"{'、'.join(architecture.visual_motifs)}，电影感角色肖像"
                    ),
                }
            )
        return CharacterRosterSchema.model_validate({"characters": characters})

    def _fallback_chapter_plan_set(
        self,
        brief: StoryBrief,
        character_roster: CharacterRosterSchema,
    ) -> ChapterPlanSetSchema:
        anchors = brief.must_include or ["关键线索", "失控夜晚", "旧档案"]
        anchor_cycle = cycle(anchors)
        lead_names = [item.name for item in character_roster.characters]
        chapters: list[dict[str, Any]] = []

        for index in range(1, brief.chapter_count + 1):
            anchor = next(anchor_cycle)
            chapters.append(
                {
                    "number": index,
                    "title": f"第 {index} 章：{anchor}",
                    "goal": f"让主角围绕“{anchor}”推进调查并升级人物关系。",
                    "summary": f"围绕“{anchor}”展开调查，主角距离真相更近，但局势更加危险。",
                    "key_conflict": f"主角必须在保留底牌和立刻行动之间作出选择，以处理“{anchor}”带来的风险。",
                    "beats": [
                        f"主角抵达与“{anchor}”相关的地点，确认异样。",
                        "信息交换引发新的误判或背叛风险。",
                        "一个更直接的危险事件迫使主角改变策略。",
                    ][: self.chapter_scene_count],
                    "cliffhanger": f"与“{anchor}”直接相关的人或证据突然出现，改变整个局势。",
                    "featured_characters": lead_names[: min(2, len(lead_names))],
                }
            )

        return ChapterPlanSetSchema.model_validate({"chapters": chapters})

    def _fallback_chapter_draft(
        self,
        brief: StoryBrief,
        outline: StoryOutline,
        chapter: ChapterPlan,
    ) -> ChapterDraftSchema:
        motifs = "、".join(outline.visual_motifs)
        visual_hooks = chapter.beats[:2] + [chapter.cliffhanger]
        continuity_refs = [chapter.goal, chapter.cliffhanger]
        beat_lines = "\n".join(f"- {beat}" for beat in chapter.beats)

        markdown = f"""# {chapter.title}

## 章节定位

- 类型：{brief.genre}
- 风格：{brief.tone}
- 本章目标：{chapter.goal}
- 重点角色：{", ".join(chapter.featured_characters) if chapter.featured_characters else "无"}
- 视觉母题：{motifs}

## 本章摘要

{chapter.summary}

## 场景节拍

{beat_lines}

## 草稿正文

{outline.characters[0].name} 进入这一章时，并不知道自己已经踩进了更大的陷阱。围绕“{chapter.title}”展开的线索不再只是一个单点异常，而是整部小说最关键的转向点。环境中的 {motifs} 持续出现，让人物始终处在压迫和暗示之中。

随着调查推进，{chapter.key_conflict}。这使得本章不只是信息推进，也是一轮关系洗牌。{outline.characters[0].name} 必须重新判断谁值得信任，谁只是把他推向更危险的位置。节拍中的每次行动，都在把人物推向无法回头的局面。

到章节收束时，{chapter.cliffhanger} 这不仅完成了本章的悬念封口，也为下一章的视频拆分提供了天然片段边界。

## 下一章接口

下一章将放大本章留下的风险，迫使角色采取更激进的行动。
"""
        return ChapterDraftSchema(
            number=chapter.number,
            title=chapter.title,
            summary=chapter.summary,
            markdown=markdown,
            visual_hooks=visual_hooks,
            continuity_refs=continuity_refs,
        )

    def _fallback_editorial_review(
        self,
        outline: StoryOutline,
        chapters: list[DraftChapter],
    ) -> EditorialReviewSchema:
        return EditorialReviewSchema(
            overall_verdict="当前版本已经具备小说开发和分段视频规划的基础，可继续进入角色图与镜头设计阶段。",
            strengths=[
                f"主题“{outline.theme}”和视觉母题已有较稳定抓手。",
                "章节之间保持了连续的悬念推进。",
                "大部分章节都能直接拆出多个视频片段。",
            ],
            continuity_risks=[
                "后续正式生成时，需要重点检查角色动机是否在长文本中持续一致。",
                "中后段章节应避免重复调查节奏，需要加入更强的关系变化。",
            ],
            revision_notes=[
                "正式接入 LLM 后，建议把每章摘要再压缩成角色状态卡和伏笔卡。",
                f"当前总章节数为 {len(chapters)}，可以在中段增加一次结构性大反转。",
            ],
        )

    def _build_fallback_voice_profile(
        self,
        brief: StoryBrief,
        role: str,
    ) -> CharacterVoiceProfileSchema:
        timbre = "冷静中低音，略带颗粒感"
        emotional_baseline = "克制、警觉"
        if "对手" in role or "幕后" in role or "镜像" in role:
            timbre = "低沉平稳，带压迫感"
            emotional_baseline = "冷静、审视、留有威胁感"
        elif "盟友" in role or "情感支点" in role:
            timbre = "柔和清晰，带安抚感"
            emotional_baseline = "稳住局面，但持续带一点紧张感"
        elif "证人" in role:
            timbre = "偏轻偏紧，呼吸感明显"
            emotional_baseline = "紧张、防备"

        return CharacterVoiceProfileSchema(
            voice_style=f"{brief.tone} 气质下可持续复用的稳定角色声线",
            timbre=timbre,
            speaking_rate="常态中速，紧张时短句略快，但整体仍清晰可辨",
            emotional_baseline=emotional_baseline,
            accent_or_texture="普通话，咬字清晰，尾音收紧，不要夸张播报感",
            dialogue_delivery="优先用短句推进信息，关键处先压低声线再强调重点",
            forbidden_voice_changes=[
                "不要突然变得更尖更幼",
                "不要突然变得更粗更老",
                "不要忽快忽慢或切成喜剧腔",
                "不要切换成明显不同的口音或播音腔",
            ],
        )
