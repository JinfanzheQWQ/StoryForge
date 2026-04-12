from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterVisualProfileSchema(BaseModel):
    name: str = Field(description="角色名")
    role: str = Field(description="角色职责")
    gender: str = Field(default="未指定", description="角色性别，必须从小说角色卡继承")
    appearance: str = Field(description="外观描述")
    outfit: str = Field(description="服装设定")
    color_palette: list[str] = Field(description="主色板")
    portrait_prompt: str = Field(description="角色图生成 prompt")


class CharacterVisualBibleSchema(BaseModel):
    characters: list[CharacterVisualProfileSchema] = Field(description="角色视觉圣经")


class VideoSegmentSchema(BaseModel):
    segment_id: str = Field(description="片段 ID")
    chapter_number: int = Field(description="所属章节")
    title: str = Field(description="片段标题")
    summary: str = Field(description="片段摘要")
    involved_characters: list[str] = Field(description="涉及角色")
    narration: str = Field(description="视频自带音频的旁白内容")
    dialogue_lines: list[str] = Field(
        default_factory=list,
        description="适合直接驱动视频模型音频的角色对白列表",
    )
    subtitle_lines: list[str] = Field(
        default_factory=list,
        description="硬字幕文本列表",
    )
    character_voice_notes: list[str] = Field(
        default_factory=list,
        description="角色音色与说话方式锁定说明",
    )
    sound_effects: list[str] = Field(
        default_factory=list,
        description="环境音与拟音列表",
    )
    music_direction: str = Field(default="", description="背景音乐方向")
    timed_beats: list[str] = Field(
        default_factory=list,
        description="按时间组织的镜头、对白和音效节拍",
    )
    scene_prompt: str = Field(description="生图总 prompt")
    start_frame_prompt: str = Field(description="首帧 prompt")
    end_frame_prompt: str = Field(description="尾帧 prompt")
    duration_seconds: int = Field(description="建议时长")
    transition_hint: str = Field(
        default="auto",
        description="与上一片段的转场关系，可取 continue / cut / auto",
    )
    source_segment_id: str = Field(default="", description="拆分前的原始片段 ID")
    subsegment_index: int = Field(default=1, description="当前子片段序号")
    subsegment_count: int = Field(default=1, description="当前原始片段拆出的总子片段数")
    reuse_previous_end_frame: bool = Field(
        default=False,
        description="是否直接沿用上一子片段的尾帧作为当前片段首帧",
    )


class VideoSegmentPlanSchema(BaseModel):
    segments: list[VideoSegmentSchema] = Field(description="完整片段规划")
