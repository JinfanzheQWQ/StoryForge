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
class SceneBible:
    location: str = ""
    time_window: str = ""
    weather: str = ""
    lighting: str = ""
    dominant_palette: list[str] = field(default_factory=list)
    background_anchors: list[str] = field(default_factory=list)
    fixed_props: list[str] = field(default_factory=list)
    spatial_layout: str = ""
    character_blocking: str = ""
    continuity_notes: str = ""

    @classmethod
    def from_dict(cls, raw: object | None) -> "SceneBible":
        if raw is None:
            payload: dict[str, Any] = {}
        elif isinstance(raw, dict):
            payload = raw
        elif hasattr(raw, "model_dump"):
            payload = dict(raw.model_dump())
        else:
            payload = {}
        return cls(
            location=str(payload.get("location", "") or ""),
            time_window=str(payload.get("time_window", "") or ""),
            weather=str(payload.get("weather", "") or ""),
            lighting=str(payload.get("lighting", "") or ""),
            dominant_palette=list(payload.get("dominant_palette", [])),
            background_anchors=list(payload.get("background_anchors", [])),
            fixed_props=list(payload.get("fixed_props", [])),
            spatial_layout=str(payload.get("spatial_layout", "") or ""),
            character_blocking=str(payload.get("character_blocking", "") or ""),
            continuity_notes=str(payload.get("continuity_notes", "") or ""),
        )


@dataclass(slots=True)
class ShotState:
    framing: str = ""
    camera_motion: str = ""
    blocking: str = ""
    action_progression: str = ""
    emotion_progression: str = ""
    prop_continuity: str = ""
    screen_direction: str = ""
    end_state_lock: str = ""

    @classmethod
    def from_dict(cls, raw: object | None) -> "ShotState":
        if raw is None:
            payload: dict[str, Any] = {}
        elif isinstance(raw, dict):
            payload = raw
        elif hasattr(raw, "model_dump"):
            payload = dict(raw.model_dump())
        else:
            payload = {}
        return cls(
            framing=str(payload.get("framing", "") or ""),
            camera_motion=str(payload.get("camera_motion", "") or ""),
            blocking=str(payload.get("blocking", "") or ""),
            action_progression=str(payload.get("action_progression", "") or ""),
            emotion_progression=str(payload.get("emotion_progression", "") or ""),
            prop_continuity=str(payload.get("prop_continuity", "") or ""),
            screen_direction=str(payload.get("screen_direction", "") or ""),
            end_state_lock=str(payload.get("end_state_lock", "") or ""),
        )


@dataclass(slots=True)
class ContinuityLink:
    previous_segment_id: str = ""
    transition_mode: str = "start"
    opening_match: str = ""
    carry_over_elements: list[str] = field(default_factory=list)
    allowed_changes: str = ""
    transition_reason: str = ""

    @classmethod
    def from_dict(cls, raw: object | None) -> "ContinuityLink":
        if raw is None:
            payload: dict[str, Any] = {}
        elif isinstance(raw, dict):
            payload = raw
        elif hasattr(raw, "model_dump"):
            payload = dict(raw.model_dump())
        else:
            payload = {}
        return cls(
            previous_segment_id=str(payload.get("previous_segment_id", "") or ""),
            transition_mode=str(payload.get("transition_mode", "start") or "start"),
            opening_match=str(payload.get("opening_match", "") or ""),
            carry_over_elements=list(payload.get("carry_over_elements", [])),
            allowed_changes=str(payload.get("allowed_changes", "") or ""),
            transition_reason=str(payload.get("transition_reason", "") or ""),
        )


@dataclass(slots=True)
class VideoSegment:
    segment_id: str
    chapter_number: int
    scene_id: str
    scene_title: str
    scene_summary: str
    scene_anchor: str
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
    scene_bible: SceneBible = field(default_factory=SceneBible)
    shot_state: ShotState = field(default_factory=ShotState)
    continuity_link: ContinuityLink = field(default_factory=ContinuityLink)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoSegment":
        return cls(
            segment_id=raw["segment_id"],
            chapter_number=raw["chapter_number"],
            scene_id=raw.get("scene_id", ""),
            scene_title=raw.get("scene_title", ""),
            scene_summary=raw.get("scene_summary", ""),
            scene_anchor=raw.get("scene_anchor", ""),
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
            scene_bible=SceneBible.from_dict(raw.get("scene_bible")),
            shot_state=ShotState.from_dict(raw.get("shot_state")),
            continuity_link=ContinuityLink.from_dict(raw.get("continuity_link")),
        )


@dataclass(slots=True)
class VideoScene:
    scene_id: str
    chapter_number: int
    title: str
    summary: str
    scene_anchor: str
    involved_characters: list[str]
    segments: list[VideoSegment]
    scene_bible: SceneBible = field(default_factory=SceneBible)
    scene_master_frame_prompt: str = ""
    scene_master_frame_path: str = ""
    scene_master_frame_url: str = ""
    scene_master_frame_status: str = "planned"
    scene_master_frame_error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoScene":
        scene_id = str(raw.get("scene_id", "") or "")
        title = str(raw.get("title", "") or raw.get("scene_title", "") or "")
        summary = str(raw.get("summary", "") or raw.get("scene_summary", "") or title)
        scene_anchor = str(raw.get("scene_anchor", "") or "")
        chapter_number = int(raw.get("chapter_number", 0) or 0)
        scene_bible = SceneBible.from_dict(raw.get("scene_bible"))

        segments: list[VideoSegment] = []
        for index, item in enumerate(raw.get("segments", []), start=1):
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload.setdefault("scene_id", scene_id)
            payload.setdefault("scene_title", title)
            payload.setdefault("scene_summary", summary)
            payload.setdefault("scene_anchor", scene_anchor)
            payload.setdefault("scene_bible", raw.get("scene_bible", {}))
            payload.setdefault("chapter_number", chapter_number)
            payload.setdefault("segment_id", f"{scene_id}-seg{index:02d}")
            segments.append(VideoSegment.from_dict(payload))

        if not scene_bible.continuity_notes and segments:
            scene_bible = segments[0].scene_bible

        involved_characters = list(raw.get("involved_characters", []))
        if not involved_characters:
            for segment in segments:
                for name in segment.involved_characters:
                    if name not in involved_characters:
                        involved_characters.append(name)

        return cls(
            scene_id=scene_id,
            chapter_number=chapter_number,
            title=title,
            summary=summary,
            scene_anchor=scene_anchor,
            involved_characters=involved_characters,
            segments=segments,
            scene_bible=scene_bible,
            scene_master_frame_prompt=str(raw.get("scene_master_frame_prompt", "") or ""),
            scene_master_frame_path=str(raw.get("scene_master_frame_path", "") or ""),
            scene_master_frame_url=str(raw.get("scene_master_frame_url", "") or ""),
            scene_master_frame_status=str(raw.get("scene_master_frame_status", "planned") or "planned"),
            scene_master_frame_error=str(raw.get("scene_master_frame_error", "") or ""),
        )


@dataclass(slots=True)
class SceneImageTask:
    segment_id: str
    scene_id: str
    scene_title: str
    scene_prompt: str
    scene_master_frame_prompt: str
    scene_master_frame_path: str
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
    scene_master_frame_status: str = "planned"
    scene_master_frame_url: str = ""
    start_frame_url: str = ""
    mid_frame_url: str = ""
    end_frame_url: str = ""
    scene_master_frame_error: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SceneImageTask":
        return cls(
            segment_id=raw["segment_id"],
            scene_id=raw.get("scene_id", ""),
            scene_title=raw.get("scene_title", ""),
            scene_prompt=raw["scene_prompt"],
            scene_master_frame_prompt=raw.get("scene_master_frame_prompt", ""),
            scene_master_frame_path=raw.get("scene_master_frame_path", ""),
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
            scene_master_frame_status=raw.get("scene_master_frame_status", "planned"),
            scene_master_frame_url=raw.get("scene_master_frame_url", ""),
            start_frame_url=raw.get("start_frame_url", ""),
            mid_frame_url=raw.get("mid_frame_url", ""),
            end_frame_url=raw.get("end_frame_url", ""),
            scene_master_frame_error=raw.get("scene_master_frame_error", ""),
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
    scenes: list[VideoScene]
    segments: list[VideoSegment]
    scene_images: list[SceneImageTask]
    seedance_manifest: SeedanceManifest
    workflow_trace: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoProjectPackage":
        raw_scenes = raw.get("scenes", [])
        raw_segments = raw.get("segments", [])
        scenes = [VideoScene.from_dict(item) for item in raw_scenes]
        if not scenes and raw_segments:
            scenes = _scenes_from_flat_segments(raw_segments)
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
            scenes=scenes,
            segments=[VideoSegment.from_dict(item) for item in raw_segments],
            scene_images=[SceneImageTask.from_dict(item) for item in raw.get("scene_images", [])],
            seedance_manifest=SeedanceManifest.from_dict(raw["seedance_manifest"]),
            workflow_trace=dict(raw.get("workflow_trace", {})),
        )


def _scenes_from_flat_segments(raw_segments: list[Any]) -> list[VideoScene]:
    scenes: dict[tuple[int, str], dict[str, Any]] = {}
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            continue
        chapter_number = int(raw.get("chapter_number", 0) or 0)
        scene_id = str(raw.get("scene_id", "") or "")
        if not scene_id:
            scene_id = (
                f"ch{chapter_number:02d}-sc{index:02d}"
                if chapter_number > 0
                else f"scene-{index:02d}"
            )
        scene_key = (chapter_number, scene_id)
        scene = scenes.setdefault(
            scene_key,
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "title": raw.get("scene_title", "") or raw.get("title", "") or f"场景 {index}",
                "summary": raw.get("scene_summary", "") or raw.get("summary", "") or f"场景 {index}",
                "scene_anchor": raw.get("scene_anchor", "") or "",
                "scene_bible": raw.get("scene_bible", {}) or {},
                "involved_characters": [],
                "segments": [],
            },
        )
        scene["segments"].append(raw)
        for name in raw.get("involved_characters", []):
            if name and name not in scene["involved_characters"]:
                scene["involved_characters"].append(name)
    return [VideoScene.from_dict(item) for item in scenes.values()]
