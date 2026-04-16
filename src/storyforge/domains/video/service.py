from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackend,
    AgentBackendUnavailableError,
    DryRunAgentBackend,
    PromptRequest,
    UnavailableAgentBackend,
)
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    ContinuityLink,
    SceneBible,
    ShotState,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.planning import VideoPlanningMixin
from storyforge.domains.video.prompting import VideoPromptingMixin
from storyforge.domains.video.repair import VideoRepairMixin
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    VideoSegmentPlanSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class NovelToVideoService(
    VideoPromptingMixin,
    VideoRepairMixin,
    VideoPlanningMixin,
):
    PLANNER_MIN_DURATION_SECONDS = 5
    SEEDANCE_MIN_DURATION_SECONDS = 2
    SEEDANCE_MAX_DURATION_SECONDS = 12
    SPEECH_CHARS_PER_SECOND = 3

    def __init__(
        self,
        backend: AgentBackend | None = None,
        segment_duration_seconds: int = 5,
        aspect_ratio: str = "16:9",
        fps: int = 24,
        character_image_provider: str = "prompt-only",
        scene_image_provider: str = "prompt-only",
        seedance_config: SeedanceConfig | None = None,
    ) -> None:
        self.backend = backend or UnavailableAgentBackend(
            "NovelToVideoService requires a live LLM backend."
        )
        self.segment_duration_seconds = segment_duration_seconds
        self.aspect_ratio = aspect_ratio
        self.fps = fps
        self.character_image_provider = character_image_provider
        self.scene_image_provider = scene_image_provider
        self.seedance_config = seedance_config or SeedanceConfig()

    def build_video_project(self, novel_package: NovelPackage, output_dir: str) -> VideoProjectPackage:
        visual_bible = self._run_structured_agent(
            schema=CharacterVisualBibleSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是影视角色视觉设计 Agent。"
                    "请把小说角色转换成稳定、可复用的角色视觉设定。"
                    "输出要偏风格化概念设计，不要写成真人摄影或现实人物描述。"
                ),
                user_prompt=self._build_visual_bible_user_prompt(novel_package),
                metadata={"task": "video-character-bible"},
            ),
            fallback=self._fallback_character_visual_bible(novel_package),
        )
        visual_bible = self._repair_character_visual_bible(visual_bible, novel_package)

        segments_plan = self._run_structured_agent(
            schema=VideoSegmentPlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是短视频分镜导演 Agent。"
                    "请先按场景拆分，再把每个场景拆成多个能独立成片的视频片段。"
                    "每个片段都要有首尾帧；必要时补充中段锚点帧。"
                    "输出偏镜头分镜和环境调度，避免真人特写描述。"
                ),
                user_prompt=self._build_segment_planner_user_prompt(novel_package),
                metadata={"task": "video-segment-planner"},
            ),
            fallback=self._fallback_segment_plan(novel_package, visual_bible),
        )
        segments_plan = self._repair_segment_plan(segments_plan, novel_package, visual_bible)
        segments_plan = self._normalize_segment_characters(segments_plan, novel_package, visual_bible)
        segments_plan = self._repair_scene_bibles(segments_plan, novel_package)
        segments_plan = self._repair_shot_states(segments_plan, novel_package)
        segments_plan = self._normalize_segments_for_seedance(segments_plan)
        segments_plan = self._repair_scene_bibles(segments_plan, novel_package)
        segments_plan = self._repair_shot_states(segments_plan, novel_package)
        segments_plan = self._repair_continuity_links(segments_plan)

        character_profiles = [
            CharacterVisualProfile(
                name=item.name,
                role=item.role,
                gender=item.gender,
                appearance=item.appearance,
                outfit=item.outfit,
                color_palette=item.color_palette,
                portrait_prompt=self._build_character_sheet_prompt(
                    name=item.name,
                    role=item.role,
                    gender=item.gender,
                    appearance=item.appearance,
                    outfit=item.outfit,
                    source_prompt=item.portrait_prompt,
                ),
            )
            for item in visual_bible.characters
        ]

        profile_map = {item.name: item for item in character_profiles}
        voice_map = {
            item.name: item.voice_profile
            for item in novel_package.outline.characters
        }
        character_images = self._build_character_image_tasks(character_profiles, output_dir)
        scenes = [
            VideoScene.from_dict(item.model_dump())
            for item in segments_plan.scenes
        ]
        scenes = self._prepare_scene_master_frames(scenes, output_dir)
        segments = [
            VideoSegment(
                segment_id=item.segment_id,
                chapter_number=item.chapter_number,
                scene_id=item.scene_id,
                scene_title=item.scene_title,
                scene_summary=item.scene_summary,
                scene_anchor=item.scene_anchor,
                title=item.title,
                summary=item.summary,
                involved_characters=item.involved_characters,
                start_frame_characters=item.start_frame_characters,
                mid_frame_characters=item.mid_frame_characters,
                end_frame_characters=item.end_frame_characters,
                narration=item.narration,
                dialogue_lines=item.dialogue_lines,
                subtitle_lines=item.subtitle_lines
                or self._build_subtitle_lines(
                    narration=item.narration,
                    dialogue_lines=item.dialogue_lines,
                    timed_beats=item.timed_beats,
                ),
                character_voice_notes=self._build_segment_voice_notes(
                    item.involved_characters,
                    voice_map,
                ),
                sound_effects=item.sound_effects,
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                scene_prompt=item.scene_prompt,
                start_frame_prompt=item.start_frame_prompt,
                mid_frame_prompt=item.mid_frame_prompt,
                end_frame_prompt=item.end_frame_prompt,
                duration_seconds=item.duration_seconds,
                requires_mid_frame=item.requires_mid_frame,
                transition_hint=item.transition_hint,
                source_segment_id=item.source_segment_id or item.segment_id,
                subsegment_index=item.subsegment_index,
                subsegment_count=item.subsegment_count,
                reuse_previous_end_frame=item.reuse_previous_end_frame,
                scene_bible=SceneBible.from_dict(item.scene_bible.model_dump()),
                shot_state=ShotState.from_dict(item.shot_state.model_dump()),
                continuity_link=ContinuityLink.from_dict(item.continuity_link.model_dump()),
            )
            for item in segments_plan.segments
        ]
        scene_images = self._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            output_dir,
        )
        manifest = self._build_seedance_manifest(
            novel_package.outline.title,
            segments,
            scene_images,
            output_dir,
        )

        return VideoProjectPackage(
            title=novel_package.outline.title,
            character_profiles=character_profiles,
            character_images=character_images,
            scenes=scenes,
            segments=segments,
            scene_images=scene_images,
            seedance_manifest=manifest,
            workflow_trace={
                "character_visual_bible": visual_bible.model_dump(),
                "scene_plan": segments_plan.model_dump(),
                "segment_plan": [
                    item.model_dump()
                    for item in segments_plan.segments
                ],
            },
        )

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        fallback: StructuredModelT,
    ) -> StructuredModelT:
        if isinstance(self.backend, DryRunAgentBackend):
            return fallback
        try:
            response = self.backend.generate_structured(request, schema)
            if isinstance(response, schema):
                return response
            return schema.model_validate(response)
        except AgentBackendUnavailableError:
            raise
        except Exception:
            return fallback
