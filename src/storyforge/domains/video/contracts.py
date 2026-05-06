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
    portrait_prompt: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterVisualProfile":
        return cls(
            name=raw["name"],
            role=raw["role"],
            gender=raw.get("gender", "未指定"),
            appearance=raw["appearance"],
            outfit=raw["outfit"],
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
    candidate_generated_url: str = ""
    candidate_output_path: str = ""
    request_info: dict[str, Any] = field(default_factory=dict)
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
            candidate_generated_url=raw.get("candidate_generated_url", ""),
            candidate_output_path=raw.get("candidate_output_path", ""),
            request_info=raw.get("request_info", {}) if isinstance(raw.get("request_info"), dict) else {},
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
class MotionPlan:
    scene_motion: str = ""
    beat_progression: str = ""
    camera_path: str = ""
    character_motion: str = ""
    continuity_guard: str = ""

    @classmethod
    def from_dict(cls, raw: object | None) -> "MotionPlan":
        if raw is None:
            payload: dict[str, Any] = {}
        elif isinstance(raw, dict):
            payload = raw
        elif hasattr(raw, "model_dump"):
            payload = dict(raw.model_dump())
        else:
            payload = {}
        return cls(
            scene_motion=str(payload.get("scene_motion", "") or ""),
            beat_progression=str(payload.get("beat_progression", "") or ""),
            camera_path=str(payload.get("camera_path", "") or ""),
            character_motion=str(payload.get("character_motion", "") or ""),
            continuity_guard=str(payload.get("continuity_guard", "") or ""),
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
class SceneTransitionContract:
    previous_scene_id: str = ""
    transition_mode: str = ""
    scene_spatial_continuity_mode: str = "uncertain"
    previous_scene_exit_state: str = ""
    next_scene_entry_match: str = ""
    shared_environment_anchors: list[str] = field(default_factory=list)
    spatial_relation_to_previous: str = ""
    camera_handoff: str = ""
    bridge_action: str = ""
    carry_over_elements: list[str] = field(default_factory=list)
    screen_direction_policy: str = ""
    visual_bridge: str = ""
    audio_bridge: str = "none"
    prop_bridge: str = ""
    action_bridge: str = ""
    allowed_environment_changes: str = ""
    forbidden_drift: str = ""
    transition_focus_seconds: int = 0

    @classmethod
    def from_dict(cls, raw: object | None) -> "SceneTransitionContract":
        if raw is None:
            payload: dict[str, Any] = {}
        elif isinstance(raw, dict):
            payload = raw
        elif hasattr(raw, "model_dump"):
            payload = dict(raw.model_dump())
        else:
            payload = {}
        return cls(
            previous_scene_id=str(payload.get("previous_scene_id", "") or ""),
            transition_mode=str(payload.get("transition_mode", "") or ""),
            scene_spatial_continuity_mode=str(
                payload.get("scene_spatial_continuity_mode", "")
                or payload.get("spatial_continuity_mode", "")
                or "uncertain"
            ),
            previous_scene_exit_state=str(payload.get("previous_scene_exit_state", "") or ""),
            next_scene_entry_match=str(payload.get("next_scene_entry_match", "") or ""),
            shared_environment_anchors=list(payload.get("shared_environment_anchors", []) or []),
            spatial_relation_to_previous=str(payload.get("spatial_relation_to_previous", "") or ""),
            camera_handoff=str(payload.get("camera_handoff", "") or ""),
            bridge_action=str(payload.get("bridge_action", "") or ""),
            carry_over_elements=list(payload.get("carry_over_elements", [])),
            screen_direction_policy=str(payload.get("screen_direction_policy", "") or ""),
            visual_bridge=str(payload.get("visual_bridge", "") or ""),
            audio_bridge=str(payload.get("audio_bridge", "none") or "none"),
            prop_bridge=str(payload.get("prop_bridge", "") or ""),
            action_bridge=str(payload.get("action_bridge", "") or ""),
            allowed_environment_changes=str(payload.get("allowed_environment_changes", "") or ""),
            forbidden_drift=str(payload.get("forbidden_drift", "") or ""),
            transition_focus_seconds=int(payload.get("transition_focus_seconds", 0) or 0),
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
    duration_seconds: int
    character_voice_notes: list[str] = field(default_factory=list)
    transition_hint: str = "auto"
    source_segment_id: str = ""
    subsegment_index: int = 1
    subsegment_count: int = 1
    scene_bible: SceneBible = field(default_factory=SceneBible)
    shot_state: ShotState = field(default_factory=ShotState)
    continuity_link: ContinuityLink = field(default_factory=ContinuityLink)
    motion_plan: MotionPlan = field(default_factory=MotionPlan)

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
            narration=raw["narration"],
            dialogue_lines=list(raw.get("dialogue_lines", [])),
            subtitle_lines=list(raw.get("subtitle_lines", [])),
            character_voice_notes=list(raw.get("character_voice_notes", [])),
            sound_effects=list(raw.get("sound_effects", [])),
            music_direction=raw.get("music_direction", ""),
            timed_beats=list(raw.get("timed_beats", [])),
            duration_seconds=raw["duration_seconds"],
            transition_hint=raw.get("transition_hint", "auto"),
            source_segment_id=raw.get("source_segment_id", raw["segment_id"]),
            subsegment_index=raw.get("subsegment_index", 1),
            subsegment_count=raw.get("subsegment_count", 1),
            scene_bible=SceneBible.from_dict(raw.get("scene_bible")),
            shot_state=ShotState.from_dict(raw.get("shot_state")),
            continuity_link=ContinuityLink.from_dict(raw.get("continuity_link")),
            motion_plan=MotionPlan.from_dict(raw.get("motion_plan")),
        )


@dataclass(slots=True)
class VideoScene:
    scene_id: str
    chapter_number: int
    title: str
    summary: str
    scene_anchor: str
    involved_characters: list[str]
    covered_event_ids: list[str] = field(default_factory=list)
    covered_event_summaries: list[str] = field(default_factory=list)
    segments: list[VideoSegment] = field(default_factory=list)
    scene_bible: SceneBible = field(default_factory=SceneBible)
    scene_transition_contract: SceneTransitionContract = field(default_factory=SceneTransitionContract)
    scene_master_frame_prompt: str = ""
    scene_master_frame_path: str = ""
    scene_master_frame_url: str = ""
    scene_master_frame_status: str = "planned"
    scene_master_frame_error: str = ""
    scene_master_reference_images: list[str] = field(default_factory=list)
    scene_master_request_info: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VideoScene":
        scene_id = str(raw.get("scene_id", "") or "")
        title = str(raw.get("title", "") or raw.get("scene_title", "") or "")
        summary = str(raw.get("summary", "") or raw.get("scene_summary", "") or title)
        scene_anchor = str(raw.get("scene_anchor", "") or "")
        chapter_number = int(raw.get("chapter_number", 0) or 0)
        scene_bible = SceneBible.from_dict(raw.get("scene_bible"))
        scene_transition_contract = SceneTransitionContract.from_dict(
            raw.get("scene_transition_contract")
        )

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
        covered_event_ids = [
            str(item).strip()
            for item in raw.get("covered_event_ids", [])
            if str(item).strip()
        ]
        covered_event_summaries = [
            str(item).strip()
            for item in raw.get("covered_event_summaries", [])
            if str(item).strip()
        ]

        return cls(
            scene_id=scene_id,
            chapter_number=chapter_number,
            title=title,
            summary=summary,
            scene_anchor=scene_anchor,
            involved_characters=involved_characters,
            covered_event_ids=covered_event_ids,
            covered_event_summaries=covered_event_summaries,
            segments=segments,
            scene_bible=scene_bible,
            scene_transition_contract=scene_transition_contract,
            scene_master_frame_prompt=str(raw.get("scene_master_frame_prompt", "") or ""),
            scene_master_frame_path=str(raw.get("scene_master_frame_path", "") or ""),
            scene_master_frame_url=str(raw.get("scene_master_frame_url", "") or ""),
            scene_master_frame_status=str(raw.get("scene_master_frame_status", "planned") or "planned"),
            scene_master_frame_error=str(raw.get("scene_master_frame_error", "") or ""),
            scene_master_reference_images=list(raw.get("scene_master_reference_images", []) or []),
            scene_master_request_info=dict(raw.get("scene_master_request_info", {}) or {}),
        )


@dataclass(slots=True)
class SceneImageTask:
    segment_id: str
    scene_id: str
    scene_title: str
    scene_master_frame_prompt: str
    scene_master_frame_path: str
    reference_images: list[str]
    provider: str
    involved_characters: list[str] = field(default_factory=list)
    status: str = "planned"
    scene_master_frame_status: str = "planned"
    scene_master_frame_url: str = ""
    scene_master_frame_error: str = ""
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SceneImageTask":
        return cls(
            segment_id=raw["segment_id"],
            scene_id=raw.get("scene_id", ""),
            scene_title=raw.get("scene_title", ""),
            scene_master_frame_prompt=raw.get("scene_master_frame_prompt", ""),
            scene_master_frame_path=raw.get("scene_master_frame_path", ""),
            reference_images=list(raw.get("reference_images", [])),
            involved_characters=list(raw.get("involved_characters", [])),
            provider=raw["provider"],
            status=raw.get("status", "planned"),
            scene_master_frame_status=raw.get("scene_master_frame_status", "planned"),
            scene_master_frame_url=raw.get("scene_master_frame_url", ""),
            scene_master_frame_error=raw.get("scene_master_frame_error", ""),
            error=raw.get("error", ""),
        )


@dataclass(slots=True)
class StoryboardGridTask:
    segment_id: str
    scene_id: str
    title: str
    prompt: str
    output_path: str
    model: str
    size: str = "2K"
    aspect_ratio: str = "16:9"
    reference_images: list[str] = field(default_factory=list)
    reference_bindings: list[dict[str, str]] = field(default_factory=list)
    scene_descriptions: list[str] = field(default_factory=list)
    uses_previous_last_frame: bool = False
    previous_last_frame_url: str = ""
    status: str = "planned"
    generated_url: str = ""
    request_info: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryboardGridTask":
        return cls(
            segment_id=str(raw["segment_id"]),
            scene_id=str(raw.get("scene_id", "") or ""),
            title=str(raw.get("title", "") or ""),
            prompt=str(raw.get("prompt", "") or ""),
            output_path=str(raw.get("output_path", "") or ""),
            model=str(raw.get("model", "") or ""),
            size=str(raw.get("size", "2K") or "2K"),
            aspect_ratio=str(raw.get("aspect_ratio", "16:9") or "16:9"),
            reference_images=list(raw.get("reference_images", []) or []),
            reference_bindings=[
                dict(item)
                for item in raw.get("reference_bindings", [])
                if isinstance(item, dict)
            ],
            scene_descriptions=[
                str(item).strip()
                for item in raw.get("scene_descriptions", [])
                if str(item).strip()
            ],
            uses_previous_last_frame=bool(raw.get("uses_previous_last_frame", False)),
            previous_last_frame_url=str(raw.get("previous_last_frame_url", "") or ""),
            status=str(raw.get("status", "planned") or "planned"),
            generated_url=str(raw.get("generated_url", "") or ""),
            request_info=dict(raw.get("request_info", {}) or {}),
            error=str(raw.get("error", "") or ""),
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
    duration_seconds: int
    aspect_ratio: str
    with_audio: bool
    output_path: str
    scene_id: str = ""
    scene_master_path: str = ""
    scene_master_url: str = ""
    character_image_paths: list[str] = field(default_factory=list)
    character_image_urls: list[str] = field(default_factory=list)
    visible_characters: list[str] = field(default_factory=list)
    video_mode: str = "direct_motion"
    storyboard_grid_path: str = ""
    storyboard_grid_url: str = ""
    storyboard_grid_prompt: str = ""
    storyboard_grid_status: str = "planned"
    storyboard_grid_error: str = ""
    storyboard_grid_request_info: dict[str, Any] = field(default_factory=dict)
    storyboard_scene_descriptions: list[str] = field(default_factory=list)
    motion_contract: dict[str, Any] = field(default_factory=dict)
    submitted_prompt: str = ""
    submit_variant: str = ""
    submitted_reference_bindings: list[dict[str, str]] = field(default_factory=list)
    submitted_request_info: dict[str, Any] = field(default_factory=dict)
    remote_task_id: str = ""
    submit_status: str = "planned"
    remote_status: str = "planned"
    video_url: str = ""
    cover_url: str = ""
    first_frame_url: str = ""
    last_frame_url: str = ""
    last_frame_path: str = ""
    previous_clip_segment_id: str = ""
    previous_clip_video_url: str = ""
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
            scene_id=raw.get("scene_id", ""),
            scene_master_path=raw.get("scene_master_path", ""),
            scene_master_url=raw.get("scene_master_url", ""),
            character_image_paths=list(raw.get("character_image_paths", [])),
            character_image_urls=list(raw.get("character_image_urls", [])),
            visible_characters=list(raw.get("visible_characters", [])),
            video_mode=raw.get("video_mode", "direct_motion"),
            storyboard_grid_path=raw.get("storyboard_grid_path", ""),
            storyboard_grid_url=raw.get("storyboard_grid_url", ""),
            storyboard_grid_prompt=raw.get("storyboard_grid_prompt", ""),
            storyboard_grid_status=raw.get("storyboard_grid_status", "planned"),
            storyboard_grid_error=raw.get("storyboard_grid_error", ""),
            storyboard_grid_request_info=dict(raw.get("storyboard_grid_request_info", {}) or {}),
            storyboard_scene_descriptions=list(raw.get("storyboard_scene_descriptions", [])),
            motion_contract=dict(raw.get("motion_contract", {}) or {}),
            submitted_prompt=raw.get("submitted_prompt", ""),
            submit_variant=raw.get("submit_variant", ""),
            submitted_reference_bindings=list(raw.get("submitted_reference_bindings", [])),
            submitted_request_info=dict(raw.get("submitted_request_info", {}) or {}),
            duration_seconds=raw["duration_seconds"],
            aspect_ratio=raw["aspect_ratio"],
            with_audio=raw.get("with_audio", True),
            output_path=raw["output_path"],
            remote_task_id=raw.get("remote_task_id", ""),
            submit_status=raw.get("submit_status", "planned"),
            remote_status=raw.get("remote_status", "planned"),
            video_url=raw.get("video_url", ""),
            cover_url=raw.get("cover_url", ""),
            first_frame_url=raw.get("first_frame_url", ""),
            last_frame_url=raw.get("last_frame_url", ""),
            last_frame_path=raw.get("last_frame_path", ""),
            previous_clip_segment_id=raw.get("previous_clip_segment_id", ""),
            previous_clip_video_url=raw.get("previous_clip_video_url", ""),
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
class StoryMemoryIdentity:
    project_id: str = ""
    source_task_id: str = ""
    story_title: str = ""
    story_source_revision: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryIdentity":
        return cls(
            project_id=str(raw.get("project_id", "") or ""),
            source_task_id=str(raw.get("source_task_id", "") or ""),
            story_title=str(raw.get("story_title", "") or ""),
            story_source_revision=str(raw.get("story_source_revision", "") or ""),
        )


@dataclass(slots=True)
class StoryMemoryGlobalBible:
    core_theme: str = ""
    world_rules: list[str] = field(default_factory=list)
    narrative_promise: str = ""
    forbidden_deviations: list[str] = field(default_factory=list)
    visual_motifs: list[str] = field(default_factory=list)
    ending_direction: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryGlobalBible":
        return cls(
            core_theme=str(raw.get("core_theme", "") or ""),
            world_rules=list(raw.get("world_rules", [])),
            narrative_promise=str(raw.get("narrative_promise", "") or ""),
            forbidden_deviations=list(raw.get("forbidden_deviations", [])),
            visual_motifs=list(raw.get("visual_motifs", [])),
            ending_direction=str(raw.get("ending_direction", "") or ""),
        )


@dataclass(slots=True)
class StoryMemoryCastEntry:
    name: str
    gender: str = "未指定"
    role: str = ""
    relationships: list[str] = field(default_factory=list)
    appearance_summary: str = ""
    voice_summary: str = ""
    personality_summary: str = ""
    hard_constraints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryCastEntry":
        return cls(
            name=str(raw.get("name", "") or ""),
            gender=str(raw.get("gender", "未指定") or "未指定"),
            role=str(raw.get("role", "") or ""),
            relationships=list(raw.get("relationships", [])),
            appearance_summary=str(raw.get("appearance_summary", "") or ""),
            voice_summary=str(raw.get("voice_summary", "") or ""),
            personality_summary=str(raw.get("personality_summary", "") or ""),
            hard_constraints=list(raw.get("hard_constraints", [])),
        )


@dataclass(slots=True)
class StoryMemoryChapterState:
    chapter_number: int
    chapter_title: str = ""
    chapter_summary: str = ""
    entry_state: dict[str, Any] = field(default_factory=dict)
    exit_state: dict[str, Any] = field(default_factory=dict)
    new_facts: list[str] = field(default_factory=list)
    resolved_threads: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    carry_over_summary: str = ""
    carry_over_visuals: list[str] = field(default_factory=list)
    carry_over_props: list[str] = field(default_factory=list)
    relationship_state: list[str] = field(default_factory=list)
    generated_scene_ids: list[str] = field(default_factory=list)
    generated_segment_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryChapterState":
        return cls(
            chapter_number=int(raw.get("chapter_number", 0) or 0),
            chapter_title=str(raw.get("chapter_title", "") or ""),
            chapter_summary=str(raw.get("chapter_summary", "") or ""),
            entry_state=dict(raw.get("entry_state", {}) or {}),
            exit_state=dict(raw.get("exit_state", {}) or {}),
            new_facts=list(raw.get("new_facts", [])),
            resolved_threads=list(raw.get("resolved_threads", [])),
            unresolved_threads=list(raw.get("unresolved_threads", [])),
            carry_over_summary=str(raw.get("carry_over_summary", "") or ""),
            carry_over_visuals=list(raw.get("carry_over_visuals", [])),
            carry_over_props=list(raw.get("carry_over_props", [])),
            relationship_state=list(raw.get("relationship_state", [])),
            generated_scene_ids=list(raw.get("generated_scene_ids", [])),
            generated_segment_ids=list(raw.get("generated_segment_ids", [])),
        )


@dataclass(slots=True)
class StoryMemoryContinuityState:
    current_time_context: str = ""
    current_location_context: str = ""
    active_props: list[str] = field(default_factory=list)
    active_costume_state: list[str] = field(default_factory=list)
    active_relationship_state: list[str] = field(default_factory=list)
    carry_over_visuals: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryContinuityState":
        return cls(
            current_time_context=str(raw.get("current_time_context", "") or ""),
            current_location_context=str(raw.get("current_location_context", "") or ""),
            active_props=list(raw.get("active_props", [])),
            active_costume_state=list(raw.get("active_costume_state", [])),
            active_relationship_state=list(raw.get("active_relationship_state", [])),
            carry_over_visuals=list(raw.get("carry_over_visuals", [])),
        )


@dataclass(slots=True)
class StoryMemoryPlanningChapterIndex:
    chapter_number: int
    scene_ids: list[str] = field(default_factory=list)
    segment_ids: list[str] = field(default_factory=list)
    scene_count: int = 0
    segment_count: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryPlanningChapterIndex":
        return cls(
            chapter_number=int(raw.get("chapter_number", 0) or 0),
            scene_ids=list(raw.get("scene_ids", [])),
            segment_ids=list(raw.get("segment_ids", [])),
            scene_count=int(raw.get("scene_count", 0) or 0),
            segment_count=int(raw.get("segment_count", 0) or 0),
        )


@dataclass(slots=True)
class StoryMemoryPlanningIndex:
    chapter_count: int = 0
    scene_count: int = 0
    segment_count: int = 0
    chapters: list[StoryMemoryPlanningChapterIndex] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryPlanningIndex":
        return cls(
            chapter_count=int(raw.get("chapter_count", 0) or 0),
            scene_count=int(raw.get("scene_count", 0) or 0),
            segment_count=int(raw.get("segment_count", 0) or 0),
            chapters=[
                StoryMemoryPlanningChapterIndex.from_dict(item)
                for item in raw.get("chapters", [])
            ],
        )


@dataclass(slots=True)
class StoryMemoryGenerationNotes:
    last_planned_chapter: int = 0
    last_successful_stage: str = ""
    planner_warnings: list[str] = field(default_factory=list)
    continuity_risks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryGenerationNotes":
        return cls(
            last_planned_chapter=int(raw.get("last_planned_chapter", 0) or 0),
            last_successful_stage=str(raw.get("last_successful_stage", "") or ""),
            planner_warnings=list(raw.get("planner_warnings", [])),
            continuity_risks=list(raw.get("continuity_risks", [])),
        )


@dataclass(slots=True)
class StoryMemoryPackage:
    story_identity: StoryMemoryIdentity = field(default_factory=StoryMemoryIdentity)
    global_story_bible: StoryMemoryGlobalBible = field(default_factory=StoryMemoryGlobalBible)
    cast_bible: list[StoryMemoryCastEntry] = field(default_factory=list)
    chapter_states: list[StoryMemoryChapterState] = field(default_factory=list)
    continuity_state: StoryMemoryContinuityState = field(default_factory=StoryMemoryContinuityState)
    planning_index: StoryMemoryPlanningIndex = field(default_factory=StoryMemoryPlanningIndex)
    generation_notes: StoryMemoryGenerationNotes = field(default_factory=StoryMemoryGenerationNotes)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoryMemoryPackage":
        return cls(
            story_identity=StoryMemoryIdentity.from_dict(raw.get("story_identity", {}) or {}),
            global_story_bible=StoryMemoryGlobalBible.from_dict(
                raw.get("global_story_bible", {}) or {}
            ),
            cast_bible=[
                StoryMemoryCastEntry.from_dict(item)
                for item in raw.get("cast_bible", [])
            ],
            chapter_states=[
                StoryMemoryChapterState.from_dict(item)
                for item in raw.get("chapter_states", [])
            ],
            continuity_state=StoryMemoryContinuityState.from_dict(
                raw.get("continuity_state", {}) or {}
            ),
            planning_index=StoryMemoryPlanningIndex.from_dict(
                raw.get("planning_index", {}) or {}
            ),
            generation_notes=StoryMemoryGenerationNotes.from_dict(
                raw.get("generation_notes", {}) or {}
            ),
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
    story_memory: StoryMemoryPackage | None = None
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
