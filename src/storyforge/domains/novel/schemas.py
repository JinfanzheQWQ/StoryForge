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


class EditorialReviewSchema(BaseModel):
    overall_verdict: str = Field(description="整体编辑判断")
    strengths: list[str] = Field(description="当前强项")
    continuity_risks: list[str] = Field(description="连续性风险")
    revision_notes: list[str] = Field(description="建议修订点")
