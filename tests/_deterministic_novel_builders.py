from __future__ import annotations

from itertools import cycle
from typing import Any

from storyforge.domains.novel.contracts import ChapterPlan, DraftChapter, StoryBrief, StoryOutline
from storyforge.domains.novel.heuristics import (
    brief_prefers_male_female_pair,
    brief_requires_dual_leads,
    brief_requires_explicit_counterpart,
    count_role_labels_in_text,
    extract_role_labels_from_brief,
    extract_role_labels_from_text,
    infer_primary_character_genders,
)
from storyforge.domains.novel.schemas import (
    CastAnalysisSchema,
    CastRelationshipSchema,
    CastSlotSchema,
    ChapterDraftSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    CharacterVoiceProfileSchema,
    EditorialReviewSchema,
    StoryDraftSetSchema,
    StoryArchitectureSchema,
)
from storyforge.domains.novel.rules import NovelRuleMixin


DEFAULT_CHARACTER_NAMES = ["林雾", "沈砚", "周遥", "许舟", "秦岚", "顾屿"]


class DeterministicNovelBuilder(NovelRuleMixin):
    """Test-only deterministic builders for novel-domain fixtures."""

    def __init__(self, chapter_scene_count: int = 3) -> None:
        self.chapter_scene_count = chapter_scene_count

    def build_architecture(self, brief: StoryBrief) -> StoryArchitectureSchema:
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

    def build_story_draft_set(
        self,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
    ) -> StoryDraftSetSchema:
        anchors = brief.must_include or architecture.visual_motifs or ["秘密", "旧档案", "夜雨"]
        anchor_cycle = cycle(anchors)
        chapters: list[ChapterDraftSchema] = []
        for index in range(1, brief.chapter_count + 1):
            anchor = next(anchor_cycle)
            title = f"第 {index} 章：{anchor}"
            summary = (
                f"围绕“{anchor}”展开关键事件，主角在 {architecture.setting} 中推进主线，"
                "并让局势比上一章更危险。"
            )
            markdown = (
                f"# {title}\n\n"
                f"{brief.idea} 的故事在这一章真正向前推动。主角带着“{anchor}”相关线索进入新的场景，"
                f"在 {architecture.setting} 的压迫氛围里不断逼近真相。"
                f"环境中的 {'、'.join(architecture.visual_motifs)} 反复出现，使这一章同时具备小说阅读感和可视化空间。\n\n"
                "事件推进过程中，主角遇到新的阻力与新的信息来源，人物关系因此发生改变。"
                "这一章既完成当章冲突，也在收束处留下更强的悬念，便于后续继续拆成视频片段。"
            )
            chapters.append(
                ChapterDraftSchema(
                    number=index,
                    title=title,
                    summary=summary,
                    markdown=markdown,
                    visual_hooks=[
                        f"{architecture.setting} 中与“{anchor}”相关的视觉节点",
                        *architecture.visual_motifs[:2],
                    ],
                    continuity_refs=[
                        f"围绕“{anchor}”留下的新问题",
                        architecture.story_engine,
                    ],
                )
            )
        return StoryDraftSetSchema(chapters=chapters)

    def build_cast_analysis(
        self,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> CastAnalysisSchema:
        story_draft_text = self._story_draft_text(story_draft_set)
        explicit_counterpart = (
            self._text_requires_explicit_counterpart(story_draft_text)
            if story_draft_text
            else brief_requires_explicit_counterpart(brief)
        )
        requires_dual_leads = (
            self._text_requires_multiple_core_characters(story_draft_text)
            if story_draft_text
            else brief_requires_dual_leads(brief)
        )
        prefers_pair = brief_prefers_male_female_pair(brief)
        inferred_pair = infer_primary_character_genders(brief)
        first_gender = inferred_pair[0] if inferred_pair is not None else ("男" if prefers_pair else "未指定")
        second_gender = inferred_pair[1] if inferred_pair is not None else ("女" if prefers_pair else "未指定")
        role_labels = (
            extract_role_labels_from_text(story_draft_text, limit=6)
            if story_draft_text
            else extract_role_labels_from_brief(brief, limit=6)
        )
        if not explicit_counterpart and len(role_labels) >= 4:
            requires_dual_leads = False
            prefers_pair = False
        recommended_count = self._recommended_core_cast_count(
            brief,
            explicit_counterpart=explicit_counterpart,
            requires_dual_leads=requires_dual_leads,
            story_draft_text=story_draft_text,
        )

        slots: list[CastSlotSchema] = []
        relationships: list[CastRelationshipSchema] = []

        if explicit_counterpart:
            lead_1_label = role_labels[0] if role_labels else "brief 中主动发起关系动作的一方"
            lead_2_label = (
                role_labels[1]
                if len(role_labels) >= 2
                else "brief 中接收关系动作的一方"
            )
            slots.extend(
                [
                    CastSlotSchema(
                        slot_id="lead_1",
                        tier="lead",
                        story_function="protagonist",
                        brief_label=lead_1_label,
                        source_evidence=[lead_1_label],
                        gender_hint=self._gender_hint_from_label(lead_1_label, first_gender),
                        objective="主动推动关系跨过关键门槛。",
                        must_appear_in=["opening", "midpoint", "climax", "ending"],
                        order_priority=1,
                        notes="必须最先展开成正式角色卡。",
                    ),
                    CastSlotSchema(
                        slot_id="lead_2",
                        tier="lead",
                        story_function="love_interest",
                        brief_label=lead_2_label,
                        source_evidence=[lead_2_label],
                        gender_hint=self._gender_hint_from_label(lead_2_label, second_gender),
                        objective="接住对方的动作，并决定是否回应或反转局势。",
                        must_appear_in=["opening", "climax", "ending"],
                        order_priority=2,
                        notes="必须作为第一关系对象稳定存在。",
                    ),
                ]
            )
            relationships.append(
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="lead_2",
                    relationship_type="core_relationship",
                    priority=1,
                    summary="这是一段驱动主线的核心关系，双方顺序不可互换。",
                )
            )
            if recommended_count >= 3:
                support_label = (
                    role_labels[2]
                    if len(role_labels) >= 3
                    else "关系见证者或情绪支点"
                )
                slots.append(
                    CastSlotSchema(
                        slot_id="core_support_1",
                        tier="core_support",
                        story_function=self._story_function_from_role_label(
                            support_label,
                            default="ally",
                        ),
                        brief_label=support_label,
                        source_evidence=[support_label],
                        gender_hint=self._gender_hint_from_label(support_label),
                        objective="放大主角情绪或推动关系迈出下一步。",
                        must_appear_in=["opening", "midpoint"],
                        order_priority=3,
                        notes="不要抢走 lead 的戏剧功能。",
                    )
                )
            if recommended_count >= 4:
                pressure_label = (
                    role_labels[3]
                    if len(role_labels) >= 4
                    else "制造外部阻力的人"
                )
                slots.append(
                    CastSlotSchema(
                        slot_id="core_support_2",
                        tier="core_support",
                        story_function=self._story_function_from_role_label(
                            pressure_label,
                            default="obstacle",
                        ),
                        brief_label=pressure_label,
                        source_evidence=[pressure_label],
                        gender_hint=self._gender_hint_from_label(pressure_label),
                        objective="制造误会、时间压力或现实阻力。",
                        must_appear_in=["midpoint", "climax"],
                        order_priority=4,
                        notes="负责增加现实层面的冲突。",
                    )
                )
                relationships.append(
                    CastRelationshipSchema(
                        source_slot_id="core_support_2",
                        target_slot_id="lead_1",
                        relationship_type="pressure",
                        priority=2,
                        summary="该角色负责向 lead_1 施加现实压力。",
                    )
                )
            recommended_count = min(recommended_count, len(slots))
            return CastAnalysisSchema(
                story_shape="dual_relationship_with_supporting_cast",
                recommended_core_cast_count=recommended_count,
                requires_dual_leads=True,
                explicit_counterpart=True,
                prefers_male_female_pair=prefers_pair,
                cast_strategy="先稳定关系双方，再按需要补充情绪支点和阻力角色；高优先级 slots 不可丢失或换序。",
                chapter_participation_rule="涉及关系推进、误会升级、摊牌和结局的章节，lead_1 与 lead_2 必须共同参与；core_support 角色按节点出现。",
                ordering_rule="角色表先展开 lead_1、lead_2，再展开 core_support，最后才考虑 supporting。",
                slots=slots,
                relationships=relationships,
            )

        if requires_dual_leads:
            lead_1_label = role_labels[0] if role_labels else "第一核心人物"
            lead_2_label = role_labels[1] if len(role_labels) >= 2 else "第二核心人物"
            slots.extend(
                [
                    CastSlotSchema(
                        slot_id="lead_1",
                        tier="lead",
                        story_function="protagonist",
                        brief_label=lead_1_label,
                        source_evidence=[lead_1_label],
                        gender_hint=self._gender_hint_from_label(lead_1_label, first_gender),
                        objective="推动主线事件向前。",
                        must_appear_in=["opening", "midpoint", "climax", "ending"],
                        order_priority=1,
                        notes="承担主要视角或主推动功能。",
                    ),
                    CastSlotSchema(
                        slot_id="lead_2",
                        tier="lead",
                        story_function=self._story_function_from_role_label(
                            lead_2_label,
                            default="counterpart",
                        ),
                        brief_label=lead_2_label,
                        source_evidence=[lead_2_label],
                        gender_hint=self._gender_hint_from_label(lead_2_label, second_gender),
                        objective="与第一核心人物形成对冲、互补或牵引。",
                        must_appear_in=["opening", "midpoint", "climax"],
                        order_priority=2,
                        notes="必须具备独立目标，不能是背景板。",
                    ),
                ]
            )
            relationships.append(
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="lead_2",
                    relationship_type="primary_dynamic",
                    priority=1,
                    summary="双主导角色共同承担主要剧情推动。",
                )
            )
            if recommended_count >= 3:
                support_label = (
                    role_labels[2]
                    if len(role_labels) >= 3
                    else "主角侧的稳定支点"
                )
                slots.append(
                    CastSlotSchema(
                        slot_id="core_support_1",
                        tier="core_support",
                        story_function=self._story_function_from_role_label(
                            support_label,
                            default="ally",
                        ),
                        brief_label=support_label,
                        source_evidence=[support_label],
                        gender_hint=self._gender_hint_from_label(support_label),
                        objective="帮助主线推进或提供关键资源。",
                        must_appear_in=["opening", "midpoint"],
                        order_priority=3,
                        notes="作为高频配角存在。",
                    )
                )
            recommended_count = min(recommended_count, len(slots))
            return CastAnalysisSchema(
                story_shape="dual_lead_with_supporting_cast",
                recommended_core_cast_count=recommended_count,
                requires_dual_leads=True,
                explicit_counterpart=False,
                prefers_male_female_pair=prefers_pair,
                cast_strategy="先固定两位 lead，再按剧情需要补 core_support；不要把所有 supporting 都挤进核心阵容。",
                chapter_participation_rule="关键推进章节尽量覆盖两位 lead，core_support 在需要时加入，不要求全程跟随。",
                ordering_rule="角色表先展开 lead，再展开 core_support。",
                slots=slots,
                relationships=relationships,
            )

        lead_label = role_labels[0] if role_labels else "主角"
        slots.append(
            CastSlotSchema(
                slot_id="lead_1",
                tier="lead",
                story_function="protagonist",
                brief_label=lead_label,
                source_evidence=[lead_label],
                gender_hint=self._gender_hint_from_label(lead_label),
                objective="推动主线事件。",
                must_appear_in=["opening", "midpoint", "climax", "ending"],
                order_priority=1,
                notes="必须保持叙事中心地位。",
            )
        )
        if recommended_count >= 2:
            support_label = (
                role_labels[1]
                if len(role_labels) >= 2
                else "主角的高频互动对象"
            )
            slots.append(
                CastSlotSchema(
                    slot_id="core_support_1",
                    tier="core_support",
                    story_function=self._story_function_from_role_label(
                        support_label,
                        default="ally",
                    ),
                    brief_label=support_label,
                    source_evidence=[support_label],
                    gender_hint=self._gender_hint_from_label(support_label),
                    objective="协助、阻拦或映照主角。",
                    must_appear_in=["opening", "midpoint"],
                    order_priority=2,
                    notes="高频配角，不是一次性路人。",
                )
            )
            relationships.append(
                CastRelationshipSchema(
                    source_slot_id="lead_1",
                    target_slot_id="core_support_1",
                    relationship_type="support_dynamic",
                    priority=1,
                    summary="高频互动对象负责映照主角状态。",
                )
            )
        if recommended_count >= 3:
            pressure_label = (
                role_labels[2]
                if len(role_labels) >= 3
                else "主角的外部阻力来源"
            )
            slots.append(
                CastSlotSchema(
                    slot_id="core_support_2",
                    tier="core_support",
                    story_function=self._story_function_from_role_label(
                        pressure_label,
                        default="antagonist",
                    ),
                    brief_label=pressure_label,
                    source_evidence=[pressure_label],
                    gender_hint=self._gender_hint_from_label(pressure_label),
                    objective="制造明确冲突或限制条件。",
                    must_appear_in=["midpoint", "climax"],
                    order_priority=3,
                    notes="承担主要对抗压力。",
                )
            )
        recommended_count = min(recommended_count, len(slots))
        return CastAnalysisSchema(
            story_shape="single_lead_with_supporting_cast",
            recommended_core_cast_count=recommended_count,
            requires_dual_leads=False,
            explicit_counterpart=False,
            prefers_male_female_pair=False,
            cast_strategy="以 lead_1 为中心构建核心 cast，再补充 1 到 2 位高频配角承担支撑和阻力功能。",
            chapter_participation_rule="lead_1 必须贯穿始终；core_support 角色按关键节点出场，不要求每章齐全。",
            ordering_rule="角色表第一位永远是 lead_1，其后再按 core_support 优先级展开。",
            slots=slots,
            relationships=relationships,
        )

    def _recommended_core_cast_count(
        self,
        brief: StoryBrief,
        *,
        explicit_counterpart: bool,
        requires_dual_leads: bool,
        story_draft_text: str = "",
    ) -> int:
        extracted_role_count = (
            count_role_labels_in_text(story_draft_text, limit=6)
            if story_draft_text
            else len(extract_role_labels_from_brief(brief, limit=6))
        )
        if extracted_role_count <= 0:
            extracted_role_count = 0
        if brief.chapter_count <= 1:
            if explicit_counterpart or requires_dual_leads:
                if extracted_role_count <= 2:
                    return 2
                return min(extracted_role_count, 3)
            if extracted_role_count <= 1:
                return 1
            return min(extracted_role_count, 2)
        if brief.chapter_count <= 3:
            base_count = 2 if explicit_counterpart or requires_dual_leads else 1
            if extracted_role_count <= 0:
                return base_count
            return max(base_count, min(extracted_role_count, 4))
        base_count = 3 if requires_dual_leads else 2
        if extracted_role_count <= 0:
            return base_count
        return max(base_count, min(extracted_role_count, 5))

    def build_character_roster(
        self,
        brief: StoryBrief,
        architecture: StoryArchitectureSchema,
        cast_analysis: CastAnalysisSchema | None = None,
    ) -> CharacterRosterSchema:
        names = cycle(DEFAULT_CHARACTER_NAMES)
        analysis = cast_analysis or self.build_cast_analysis(brief, architecture)
        slots = analysis.primary_slots(max(1, analysis.recommended_core_cast_count))
        characters = []
        for index, slot in enumerate(slots):
            name = next(names)
            role = self._role_from_cast_slot(slot)
            gender = self._resolved_cast_slot_gender(slot, brief, index)
            voice_profile = self._build_voice_profile(
                brief=brief,
                role=role,
            )
            desire = slot.objective.strip() or f"解开与《{brief.title_hint}》主线相关的真相"
            conflict = self._conflict_from_cast_slot(slot)
            arc = self._arc_from_cast_slot(slot)
            image_prompt = (
                f"{name}，{gender}，{role}，青年到中青年年龄段，体型稳定，{brief.tone}，"
                f"{'、'.join(architecture.visual_motifs)}，电影感角色肖像，槽位：{slot.slot_id}"
            )
            characters.append(
                {
                    "cast_slot_id": slot.slot_id,
                    "name": name,
                    "role": role,
                    "gender": gender,
                    "desire": desire,
                    "conflict": conflict,
                    "arc": arc,
                    "visual_signature": list(architecture.visual_motifs[:2]) + [brief.genre],
                    "voice_style": voice_profile.voice_style,
                    "voice_profile": voice_profile.model_dump(),
                    "image_prompt": image_prompt,
                }
            )
        return CharacterRosterSchema.model_validate({"characters": characters})

    def build_chapter_plan_set(
        self,
        brief: StoryBrief,
        character_roster: CharacterRosterSchema,
        cast_analysis: CastAnalysisSchema | None = None,
        story_draft_set: StoryDraftSetSchema | None = None,
    ) -> ChapterPlanSetSchema:
        anchors = brief.must_include or ["关键线索", "失控夜晚", "旧档案"]
        anchor_cycle = cycle(anchors)
        lead_names = [item.name for item in character_roster.characters]
        analysis = cast_analysis
        chapters: list[dict[str, Any]] = []
        draft_by_number = {
            item.number: item for item in (story_draft_set.chapters if story_draft_set is not None else [])
        }

        for index in range(1, brief.chapter_count + 1):
            anchor = next(anchor_cycle)
            source_chapter = draft_by_number.get(index)
            title = source_chapter.title if source_chapter is not None else f"第 {index} 章：{anchor}"
            summary = (
                source_chapter.summary
                if source_chapter is not None
                else f"围绕“{anchor}”展开调查，主角距离真相更近，但局势更加危险。"
            )
            featured_count = 2 if analysis is not None and analysis.requires_dual_leads else 1
            chapters.append(
                {
                    "number": index,
                    "title": title,
                    "goal": f"让主角围绕“{anchor}”推进调查并升级人物关系。",
                    "summary": summary,
                    "key_conflict": f"主角必须在保留底牌和立刻行动之间作出选择，以处理“{anchor}”带来的风险。",
                    "beats": [
                        f"主角抵达与“{anchor}”相关的地点，确认异样。",
                        "信息交换引发新的误判或背叛风险。",
                        "一个更直接的危险事件迫使主角改变策略。",
                    ][: self.chapter_scene_count],
                    "cliffhanger": f"与“{anchor}”直接相关的人或证据突然出现，改变整个局势。",
                    "featured_characters": lead_names[
                        : min(max(1, featured_count), len(lead_names))
                    ],
                }
            )

        return ChapterPlanSetSchema.model_validate({"chapters": chapters})

    def _role_from_cast_slot(self, slot: CastSlotSchema) -> str:
        if slot.story_function == "protagonist":
            return "主角"
        if slot.story_function == "love_interest":
            return "关系对位角色 / 情感对象"
        if slot.story_function == "counterpart":
            return "关键对位角色"
        if slot.story_function == "ally":
            return "盟友 / 情感支点"
        if slot.story_function == "mentor":
            return "导师 / 信息引路人"
        if slot.story_function == "handler":
            return "情报联络人 / 执行支点"
        if slot.story_function == "witness":
            return "见证者 / 关键知情人"
        if slot.story_function == "antagonist":
            return "对手 / 外部阻力"
        if slot.story_function == "obstacle":
            return "外部阻力 / 误会制造者"
        return "支持角色"

    def _resolved_cast_slot_gender(
        self,
        slot: CastSlotSchema,
        brief: StoryBrief,
        index: int,
    ) -> str:
        if slot.gender_hint in {"男", "女"}:
            return slot.gender_hint
        label_gender = self._gender_hint_from_label(slot.brief_label)
        if label_gender in {"男", "女"}:
            return label_gender
        inferred_pair = infer_primary_character_genders(brief)
        if inferred_pair is not None and index < 2:
            return inferred_pair[index]
        return "未指定"

    def _story_function_from_role_label(
        self,
        label: str,
        *,
        default: str,
    ) -> str:
        if any(token in label for token in ("恋人", "前任", "未婚妻", "未婚夫", "丈夫", "妻子")):
            return "love_interest" if default in {"love_interest", "counterpart"} else "ally"
        if any(token in label for token in ("线人", "搭档", "朋友", "室友", "同学", "助理")):
            return "handler" if "线人" in label else "ally"
        if any(token in label for token in ("警察", "警探", "侦探", "证人", "医生", "律师", "父亲", "母亲")):
            return "witness"
        if any(token in label for token in ("继承人", "嫌疑人", "老板", "总监", "投资人", "保镖")):
            return "antagonist" if default == "antagonist" else "obstacle"
        if any(token in label for token in ("老师", "教授")):
            return "mentor"
        return default

    def _gender_hint_from_label(
        self,
        label: str,
        default_value: str = "未指定",
    ) -> str:
        if any(token in label for token in ("女生", "女人", "少女", "妻子", "女儿", "姐姐", "妹妹", "未婚妻")):
            return "女"
        if any(token in label for token in ("男生", "男人", "少年", "丈夫", "儿子", "哥哥", "弟弟", "未婚夫")):
            return "男"
        return default_value

    def _conflict_from_cast_slot(self, slot: CastSlotSchema) -> str:
        if slot.story_function == "protagonist":
            return "想主动推进局势，却要付出更高代价。"
        if slot.story_function in {"love_interest", "counterpart"}:
            return "既被主线牵引，又在保护自己。"
        if slot.story_function in {"ally", "witness"}:
            return "想帮助主角，但也会被局势反噬。"
        if slot.story_function in {"antagonist", "obstacle"}:
            return "通过施压或阻拦改变主线走向。"
        return "和主线发生交叉时必须站队。"

    def _arc_from_cast_slot(self, slot: CastSlotSchema) -> str:
        if slot.tier == "lead":
            return "从试探和保留，逐步走向主动承担。"
        if slot.tier == "core_support":
            return "从辅助或阻拦，逐步暴露更真实的立场。"
        return "在有限出场中完成明确功能。"

    def build_chapter_draft(
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

    def build_editorial_review(
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

    def _build_voice_profile(
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
