from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from storyforge.core.io import read_toml


@dataclass(slots=True)
class StoryBrief:
    idea: str
    genre: str = "通用"
    tone: str = "电影感"
    target_audience: str = "大众读者"
    title_hint: str = "未命名故事"
    chapter_count: int = 8
    total_word_target: int = 20000
    must_include: list[str] = field(default_factory=list)
    style_keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "StoryBrief":
        raw = read_toml(path)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryBrief":
        return cls(
            idea=raw["idea"],
            genre=raw.get("genre", "通用"),
            tone=raw.get("tone", "电影感"),
            target_audience=raw.get("target_audience", "大众读者"),
            title_hint=raw.get("title_hint", "未命名故事"),
            chapter_count=raw.get("chapter_count", 8),
            total_word_target=raw.get("total_word_target", 20000),
            must_include=list(raw.get("must_include", [])),
            style_keywords=list(raw.get("style_keywords", [])),
        )


@dataclass(slots=True)
class CharacterVoiceProfile:
    voice_style: str = ""
    timbre: str = ""
    speaking_rate: str = ""
    emotional_baseline: str = ""
    accent_or_texture: str = ""
    dialogue_delivery: str = ""
    forbidden_voice_changes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterVoiceProfile":
        return cls(
            voice_style=raw.get("voice_style", ""),
            timbre=raw.get("timbre", ""),
            speaking_rate=raw.get("speaking_rate", ""),
            emotional_baseline=raw.get("emotional_baseline", ""),
            accent_or_texture=raw.get("accent_or_texture", ""),
            dialogue_delivery=raw.get("dialogue_delivery", ""),
            forbidden_voice_changes=list(raw.get("forbidden_voice_changes", [])),
        )

    def resolved_voice_style(self) -> str:
        if self.voice_style.strip():
            return self.voice_style.strip()
        parts = [self.timbre.strip(), self.emotional_baseline.strip()]
        return "，".join(item for item in parts if item) or "稳定、可识别的角色音色"


@dataclass(slots=True)
class CharacterProfile:
    cast_slot_id: str
    name: str
    role: str
    gender: str
    desire: str
    conflict: str
    arc: str
    visual_signature: list[str] = field(default_factory=list)
    voice_style: str = ""
    voice_profile: CharacterVoiceProfile = field(default_factory=CharacterVoiceProfile)
    image_prompt: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterProfile":
        voice_profile_raw = raw.get("voice_profile")
        if not isinstance(voice_profile_raw, dict) or not voice_profile_raw:
            raise ValueError(
                "CharacterProfile.from_dict 需要结构化 voice_profile；旧版仅 voice_style 数据已不再支持。"
            )
        voice_profile = CharacterVoiceProfile.from_dict(voice_profile_raw)
        voice_style = str(raw.get("voice_style", "") or "").strip()
        if not voice_style:
            voice_style = voice_profile.resolved_voice_style()
        return cls(
            cast_slot_id=raw.get("cast_slot_id", ""),
            name=raw["name"],
            role=raw["role"],
            gender=raw.get("gender", "未指定"),
            desire=raw["desire"],
            conflict=raw["conflict"],
            arc=raw["arc"],
            visual_signature=list(raw.get("visual_signature", [])),
            voice_style=voice_style,
            voice_profile=voice_profile,
            image_prompt=raw.get("image_prompt", ""),
        )


@dataclass(slots=True)
class ChapterPlan:
    number: int
    title: str
    summary: str
    key_conflict: str
    beats: list[str]
    cliffhanger: str
    goal: str = ""
    featured_characters: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChapterPlan":
        return cls(
            number=raw["number"],
            title=raw["title"],
            summary=raw["summary"],
            key_conflict=raw["key_conflict"],
            beats=list(raw.get("beats", [])),
            cliffhanger=raw["cliffhanger"],
            goal=raw.get("goal", ""),
            featured_characters=list(raw.get("featured_characters", [])),
        )


@dataclass(slots=True)
class StoryOutline:
    title: str
    premise: str
    theme: str
    visual_motifs: list[str]
    characters: list[CharacterProfile]
    chapters: list[ChapterPlan]
    agent_notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryOutline":
        return cls(
            title=raw["title"],
            premise=raw.get("premise", ""),
            theme=raw.get("theme", ""),
            visual_motifs=list(raw.get("visual_motifs", [])),
            characters=[CharacterProfile.from_dict(item) for item in raw.get("characters", [])],
            chapters=[ChapterPlan.from_dict(item) for item in raw.get("chapters", [])],
            agent_notes=raw.get("agent_notes", ""),
        )


@dataclass(slots=True)
class DraftChapter:
    number: int
    title: str
    markdown: str
    summary: str
    agent_notes: str = ""
    visual_hooks: list[str] = field(default_factory=list)
    continuity_refs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DraftChapter":
        return cls(
            number=raw["number"],
            title=raw["title"],
            markdown=raw["markdown"],
            summary=raw["summary"],
            agent_notes=raw.get("agent_notes", ""),
            visual_hooks=list(raw.get("visual_hooks", [])),
            continuity_refs=list(raw.get("continuity_refs", [])),
        )


@dataclass(slots=True)
class StorySourcePackage:
    brief: StoryBrief
    title: str
    chapters: list[DraftChapter]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StorySourcePackage":
        return cls(
            brief=StoryBrief.from_dict(raw["brief"]),
            title=raw.get("title", raw.get("brief", {}).get("title_hint", "未命名故事")),
            chapters=[DraftChapter.from_dict(item) for item in raw.get("chapters", [])],
        )


@dataclass(slots=True)
class EditorialReview:
    overall_verdict: str
    strengths: list[str]
    continuity_risks: list[str]
    revision_notes: list[str]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EditorialReview":
        return cls(
            overall_verdict=raw.get("overall_verdict", ""),
            strengths=list(raw.get("strengths", [])),
            continuity_risks=list(raw.get("continuity_risks", [])),
            revision_notes=list(raw.get("revision_notes", [])),
        )


@dataclass(slots=True)
class NovelPackage:
    brief: StoryBrief
    outline: StoryOutline
    chapters: list[DraftChapter]
    review: EditorialReview | None = None
    workflow_trace: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NovelPackage":
        review_raw = raw.get("review")
        return cls(
            brief=StoryBrief.from_dict(raw["brief"]),
            outline=StoryOutline.from_dict(raw["outline"]),
            chapters=[DraftChapter.from_dict(item) for item in raw.get("chapters", [])],
            review=EditorialReview.from_dict(review_raw) if isinstance(review_raw, dict) else None,
            workflow_trace=dict(raw.get("workflow_trace", {})),
        )
