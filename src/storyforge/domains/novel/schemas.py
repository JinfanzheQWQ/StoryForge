from __future__ import annotations

from pydantic import BaseModel, Field


class StoryArchitectureSchema(BaseModel):
    title: str = Field(description="小说标题")
    premise: str = Field(description="一句话 premise")
    theme: str = Field(description="故事主题")
    setting: str = Field(description="世界与场景设定")
    story_engine: str = Field(description="推动情节持续发展的核心机制")
    visual_motifs: list[str] = Field(description="视觉母题")
    tone_notes: list[str] = Field(description="语气与文风控制点")


class CastSlotSchema(BaseModel):
    slot_id: str = Field(description="角色槽位 ID，例如 lead_1 / core_support_1")
    tier: str = Field(description="角色层级，例如 lead / core_support / supporting / minor")
    story_function: str = Field(
        description="剧情功能，例如 protagonist / love_interest / ally / antagonist / witness"
    )
    brief_label: str = Field(description="基于 brief 的角色指代，不要凭空扩写成正式角色名")
    source_evidence: list[str] = Field(
        default_factory=list,
        description="支撑该槽位存在的 brief 原文线索，用于后续 repair 和人工审查",
    )
    gender_hint: str = Field(
        default="未指定",
        description="从 brief 中解析出的性别线索，例如 男 / 女 / 未指定",
    )
    objective: str = Field(description="该槽位角色在当前故事里的直接目标")
    must_appear_in: list[str] = Field(
        default_factory=list,
        description="必须参与的结构节点，例如 opening / midpoint / climax / ending",
    )
    order_priority: int = Field(description="角色生成和章节规划时的优先级排序，越小越靠前")
    notes: str = Field(default="", description="给角色生成阶段的额外说明")


class CastRelationshipSchema(BaseModel):
    source_slot_id: str = Field(description="关系起点槽位 ID")
    target_slot_id: str = Field(description="关系终点槽位 ID")
    relationship_type: str = Field(
        description="关系类型，例如 romantic_tension / rivalry / alliance / family_bond"
    )
    priority: int = Field(description="关系重要性排序，越小越重要")
    summary: str = Field(description="这段关系对故事的具体作用")


class CastAnalysisSchema(BaseModel):
    story_shape: str = Field(
        description="故事形态，例如 single_lead / dual_relationship / dual_lead_with_supporting_cast / ensemble"
    )
    recommended_core_cast_count: int = Field(description="当前篇幅建议稳定展开的核心角色数")
    requires_dual_leads: bool = Field(description="是否明确需要两位主导角色")
    explicit_counterpart: bool = Field(description="brief 是否明确存在关系双方或互动对位")
    prefers_male_female_pair: bool = Field(description="是否默认偏向一男一女主关系")
    cast_strategy: str = Field(description="后续角色生成必须遵守的 cast 结构策略")
    chapter_participation_rule: str = Field(description="关键章节中各层级角色的出场规则")
    ordering_rule: str = Field(description="后续角色表的排序规则")
    slots: list[CastSlotSchema] = Field(description="角色槽位定义")
    relationships: list[CastRelationshipSchema] = Field(description="核心关系图")

    def ordered_slots(self) -> list[CastSlotSchema]:
        return sorted(self.slots, key=lambda item: (item.order_priority, item.slot_id))

    def primary_slots(self, limit: int | None = None) -> list[CastSlotSchema]:
        ordered = self.ordered_slots()
        if limit is None:
            return ordered
        return ordered[:limit]


class CharacterVoiceProfileSchema(BaseModel):
    voice_style: str = Field(description="一句话总结角色整体声音气质")
    timbre: str = Field(description="核心音色特征，如清冷、低沉、沙哑、轻亮")
    speaking_rate: str = Field(description="常态语速与紧张时变化")
    emotional_baseline: str = Field(description="常态情绪底色")
    accent_or_texture: str = Field(
        default="",
        description="口音、咬字习惯或声音颗粒感",
    )
    dialogue_delivery: str = Field(
        default="",
        description="常见的说话方式、停顿习惯或句式习惯",
    )
    forbidden_voice_changes: list[str] = Field(
        default_factory=list,
        description="必须避免的声音漂移或变声情况",
    )


class CharacterSheetSchema(BaseModel):
    cast_slot_id: str = Field(default="", description="该角色对应的 cast 槽位 ID")
    name: str = Field(description="角色名")
    role: str = Field(description="角色功能")
    gender: str = Field(default="未指定", description="角色性别，例如 男 / 女 / 非二元 / 未指定")
    desire: str = Field(description="角色欲望")
    conflict: str = Field(description="主要冲突")
    arc: str = Field(description="角色弧光")
    visual_signature: list[str] = Field(description="视觉特征")
    voice_style: str = Field(description="对白和叙事声音的一句话总结")
    voice_profile: CharacterVoiceProfileSchema = Field(description="结构化角色音色卡")
    image_prompt: str = Field(description="后续角色图生成提示词")


class CharacterRosterSchema(BaseModel):
    characters: list[CharacterSheetSchema] = Field(description="主角色名单")


class ChapterBlueprintSchema(BaseModel):
    number: int = Field(description="章节序号")
    title: str = Field(description="章节标题")
    goal: str = Field(description="本章叙事目标")
    summary: str = Field(description="本章摘要")
    key_conflict: str = Field(description="关键冲突")
    beats: list[str] = Field(description="场景节拍")
    cliffhanger: str = Field(description="章末悬念")
    featured_characters: list[str] = Field(description="本章重点角色")


class ChapterPlanSetSchema(BaseModel):
    chapters: list[ChapterBlueprintSchema] = Field(description="完整章节规划")


class ChapterDraftSchema(BaseModel):
    number: int = Field(description="章节序号")
    title: str = Field(description="章节标题")
    summary: str = Field(description="章节摘要")
    markdown: str = Field(description="章节 Markdown 草稿")
    visual_hooks: list[str] = Field(description="后续影视化可利用的视觉抓手")
    continuity_refs: list[str] = Field(description="需要后续章节继续承接的信息")


class StoryDraftSetSchema(BaseModel):
    chapters: list[ChapterDraftSchema] = Field(description="先行生成的整部小说草稿")


class EditorialReviewSchema(BaseModel):
    overall_verdict: str = Field(description="整体编辑判断")
    strengths: list[str] = Field(description="当前强项")
    continuity_risks: list[str] = Field(description="连续性风险")
    revision_notes: list[str] = Field(description="建议修订点")
