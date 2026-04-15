from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CharacterVisualProfile:
    name: str
    role: str
    gender: str
    appearance: str
    outfit: str
    color_palette: list[str]
    portrait_prompt: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterVisualProfile":
        return cls(
            name=raw["name"],
            role=raw["role"],
            gender=raw.get("gender", "未指定"),
            appearance=raw["appearance"],
            outfit=raw["outfit"],
            color_palette=list(raw.get("color_palette", [])),
            portrait_prompt=raw["portrait_prompt"],
        )


@dataclass(slots=True)
class CharacterImageTask:
    character_name: str
    prompt: str
    output_path: str
    provider: str
    image_kind: str = "turnaround_sheet"
    consistency_notes: str = ""
    use_as_reference: bool = True
    status: str = "planned"
    generated_url: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterImageTask":
        return cls(
            character_name=raw["character_name"],
            prompt=raw["prompt"],
            output_path=raw["output_path"],
            provider=raw["provider"],
            image_kind=raw.get("image_kind", "turnaround_sheet"),
            consistency_notes=raw.get("consistency_notes", ""),
            use_as_reference=raw.get("use_as_reference", True),
            status=raw.get("status", "planned"),
            generated_url=raw.get("generated_url", ""),
            error=raw.get("error", ""),
        )


@dataclass(slots=True)
class VideoSegment:
    segment_id: str
    chapter_number: int
    title: str
    summary: str
    involved_characters: list[str]
    narration: str
    dialogue_lines: list[str]
    subtitle_lines: list[str]
    sound_effects: list[str]
    music_direction: str
    timed_beats: list[str]
    scene_prompt: str
    start_frame_prompt: str
    end_frame_prompt: str
    duration_seconds: int
    start_frame_characters: list[str] = field(default_factory=list)
    mid_frame_characters: list[str] = field(default_factory=list)
    end_frame_characters: list[str] = field(default_factory=list)
    character_voice_notes: list[str] = field(default_factory=list)
    mid_frame_prompt: str = ""
    requires_mid_frame: bool = False
    transition_hint: str = "auto"
    source_segment_id: str = ""
    subsegment_index: int = 1
    subsegment_count: int = 1
    reuse_previous_end_frame: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoSegment":
        return cls(
            segment_id=raw["segment_id"],
            chapter_number=raw["chapter_number"],
            title=raw["title"],
            summary=raw["summary"],
            involved_characters=list(raw.get("involved_characters", [])),
            start_frame_characters=list(raw.get("start_frame_characters", [])),
            mid_frame_characters=list(raw.get("mid_frame_characters", [])),
            end_frame_characters=list(raw.get("end_frame_characters", [])),
            narration=raw["narration"],
            dialogue_lines=list(raw.get("dialogue_lines", [])),
            subtitle_lines=list(raw.get("subtitle_lines", [])),
            character_voice_notes=list(raw.get("character_voice_notes", [])),
            sound_effects=list(raw.get("sound_effects", [])),
            music_direction=raw.get("music_direction", ""),
            timed_beats=list(raw.get("timed_beats", [])),
            scene_prompt=raw["scene_prompt"],
            start_frame_prompt=raw["start_frame_prompt"],
            mid_frame_prompt=raw.get("mid_frame_prompt", ""),
            end_frame_prompt=raw["end_frame_prompt"],
            duration_seconds=raw["duration_seconds"],
            requires_mid_frame=raw.get("requires_mid_frame", False),
            transition_hint=raw.get("transition_hint", "auto"),
            source_segment_id=raw.get("source_segment_id", raw["segment_id"]),
            subsegment_index=raw.get("subsegment_index", 1),
            subsegment_count=raw.get("subsegment_count", 1),
            reuse_previous_end_frame=raw.get("reuse_previous_end_frame", False),
        )


@dataclass(slots=True)
class SceneImageTask:
    segment_id: str
    scene_prompt: str
    start_frame_prompt: str
    end_frame_prompt: str
    reference_images: list[str]
    start_frame_path: str
    end_frame_path: str
    provider: str
    involved_characters: list[str] = field(default_factory=list)
    start_frame_characters: list[str] = field(default_factory=list)
    mid_frame_characters: list[str] = field(default_factory=list)
    end_frame_characters: list[str] = field(default_factory=list)
    mid_frame_prompt: str = ""
    mid_frame_path: str = ""
    requires_mid_frame: bool = False
    reuse_previous_end_frame: bool = False
    continuity_source_segment_id: str = ""
    status: str = "planned"
    start_frame_url: str = ""
    mid_frame_url: str = ""
    end_frame_url: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SceneImageTask":
        return cls(
            segment_id=raw["segment_id"],
            scene_prompt=raw["scene_prompt"],
            start_frame_prompt=raw["start_frame_prompt"],
            mid_frame_prompt=raw.get("mid_frame_prompt", ""),
            end_frame_prompt=raw["end_frame_prompt"],
            reference_images=list(raw.get("reference_images", [])),
            involved_characters=list(raw.get("involved_characters", [])),
            start_frame_characters=list(raw.get("start_frame_characters", [])),
            mid_frame_characters=list(raw.get("mid_frame_characters", [])),
            end_frame_characters=list(raw.get("end_frame_characters", [])),
            start_frame_path=raw["start_frame_path"],
            mid_frame_path=raw.get("mid_frame_path", ""),
            end_frame_path=raw["end_frame_path"],
            provider=raw["provider"],
            requires_mid_frame=raw.get("requires_mid_frame", False),
            reuse_previous_end_frame=raw.get("reuse_previous_end_frame", False),
            continuity_source_segment_id=raw.get("continuity_source_segment_id", ""),
            status=raw.get("status", "planned"),
            start_frame_url=raw.get("start_frame_url", ""),
            mid_frame_url=raw.get("mid_frame_url", ""),
            end_frame_url=raw.get("end_frame_url", ""),
            error=raw.get("error", ""),
        )


@dataclass(slots=True)
class SeedanceClipTask:
    segment_id: str
    title: str
    prompt: str
    narration: str
    dialogue_lines: list[str]
    subtitle_lines: list[str]
    sound_effects: list[str]
    music_direction: str
    timed_beats: list[str]
    start_frame_path: str
    end_frame_path: str
    duration_seconds: int
    aspect_ratio: str
    with_audio: bool
    output_path: str
    mid_frame_path: str = ""
    start_frame_url: str = ""
    mid_frame_url: str = ""
    end_frame_url: str = ""
    reference_image_paths: list[str] = field(default_factory=list)
    reference_image_urls: list[str] = field(default_factory=list)
    remote_task_id: str = ""
    submit_status: str = "planned"
    remote_status: str = "planned"
    video_url: str = ""
    cover_url: str = ""
    downloaded_path: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SeedanceClipTask":
        return cls(
            segment_id=raw["segment_id"],
            title=raw["title"],
            prompt=raw["prompt"],
            narration=raw.get("narration", ""),
            dialogue_lines=list(raw.get("dialogue_lines", [])),
            subtitle_lines=list(raw.get("subtitle_lines", [])),
            sound_effects=list(raw.get("sound_effects", [])),
            music_direction=raw.get("music_direction", ""),
            timed_beats=list(raw.get("timed_beats", [])),
            start_frame_path=raw["start_frame_path"],
            end_frame_path=raw["end_frame_path"],
            mid_frame_path=raw.get("mid_frame_path", ""),
            start_frame_url=raw.get("start_frame_url", ""),
            mid_frame_url=raw.get("mid_frame_url", ""),
            end_frame_url=raw.get("end_frame_url", ""),
            reference_image_paths=list(raw.get("reference_image_paths", [])),
            reference_image_urls=list(raw.get("reference_image_urls", [])),
            duration_seconds=raw["duration_seconds"],
            aspect_ratio=raw["aspect_ratio"],
            with_audio=raw.get("with_audio", True),
            output_path=raw["output_path"],
            remote_task_id=raw.get("remote_task_id", ""),
            submit_status=raw.get("submit_status", "planned"),
            remote_status=raw.get("remote_status", "planned"),
            video_url=raw.get("video_url", ""),
            cover_url=raw.get("cover_url", ""),
            downloaded_path=raw.get("downloaded_path", ""),
            error=raw.get("error", ""),
        )


@dataclass(slots=True)
class SeedanceManifest:
    title: str
    model: str
    base_url: str
    clips: list[SeedanceClipTask]
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SeedanceManifest":
        return cls(
            title=raw["title"],
            model=raw["model"],
            base_url=raw.get("base_url", ""),
            clips=[SeedanceClipTask.from_dict(item) for item in raw.get("clips", [])],
            notes=list(raw.get("notes", [])),
        )


@dataclass(slots=True)
class VideoProjectPackage:
    title: str
    character_profiles: list[CharacterVisualProfile]
    character_images: list[CharacterImageTask]
    segments: list[VideoSegment]
    scene_images: list[SceneImageTask]
    seedance_manifest: SeedanceManifest
    workflow_trace: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoProjectPackage":
        return cls(
            title=raw["title"],
            character_profiles=[
                CharacterVisualProfile.from_dict(item)
                for item in raw.get("character_profiles", [])
            ],
            character_images=[
                CharacterImageTask.from_dict(item)
                for item in raw.get("character_images", [])
            ],
            segments=[VideoSegment.from_dict(item) for item in raw.get("segments", [])],
            scene_images=[SceneImageTask.from_dict(item) for item in raw.get("scene_images", [])],
            seedance_manifest=SeedanceManifest.from_dict(raw["seedance_manifest"]),
            workflow_trace=dict(raw.get("workflow_trace", {})),
        )
