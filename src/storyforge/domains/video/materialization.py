from __future__ import annotations

from storyforge.core.io import to_jsonable
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    ContinuityLink,
    MotionPlan,
    SceneBible,
    ShotState,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.schemas import (
    ChapterSceneSchema,
    CharacterVisualBibleSchema,
    SceneContinuityRepairSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    SegmentContinuityRepairSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


class VideoMaterializationMixin:
    def _require_contract_frame_characters(
        self,
        *,
        field_name: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> list[str]:
        if not involved_characters:
            raise ValueError(f"{field_name} 无法校验，因为 involved_characters 为空。")
        normalized = [
            name for name in frame_characters if name and name in involved_characters
        ]
        if not normalized:
            raise ValueError(f"{field_name} 不能为空，且只能使用 involved_characters 内角色。")
        return normalized

    def _materialize_chapter_scene(
        self,
        *,
        raw_scene: ChapterSceneSchema,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> ChapterSceneSchema:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        involved_characters = list(raw_scene.involved_characters)
        if not involved_characters:
            involved_characters = list(chapter_outline.featured_characters)
        if not involved_characters:
            involved_characters = [
                item.name for item in novel_package.outline.characters[:2]
            ]
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=chapter_number,
            scene_title=raw_scene.title,
            scene_summary=raw_scene.summary,
            scene_anchor=raw_scene.scene_anchor,
            scene_bible=raw_scene.scene_bible,
            involved_characters=involved_characters,
        )
        scene_anchor = raw_scene.scene_anchor.strip() or "；".join(
            part
            for part in (
                repaired_scene_bible.location,
                repaired_scene_bible.time_window,
                raw_scene.summary,
            )
            if str(part).strip()
        )[:120]
        return raw_scene.model_copy(
            update={
                "chapter_number": chapter_number,
                "scene_anchor": scene_anchor,
                "involved_characters": involved_characters,
                "scene_bible": repaired_scene_bible,
            }
        )

    def _materialize_scene_segments(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        contracts: SceneSegmentContractBatchSchema,
    ) -> list[VideoSegmentSchema]:
        segments: list[VideoSegmentSchema] = []
        for contract in contracts.segments:
            materialized = self._materialize_scene_segment(
                novel_package=novel_package,
                scene=scene,
                contract=contract,
            )
            segments.append(materialized)
        return segments

    def _materialize_scene_segment(
        self,
        *,
        novel_package: NovelPackage,
        scene: ChapterSceneSchema,
        contract: SceneSegmentContractSchema,
    ) -> VideoSegmentSchema:
        involved_characters = list(contract.involved_characters)
        timed_beats = list(contract.timed_beats)
        narration, dialogue_lines, subtitle_lines = self._sanitize_segment_audio_tracks(
            narration=contract.narration,
            dialogue_lines=contract.dialogue_lines,
            subtitle_lines=contract.subtitle_lines,
            summary=contract.summary,
            timed_beats=timed_beats,
            involved_characters=involved_characters,
        )
        subtitle_lines = subtitle_lines or self._build_subtitle_lines(
            narration=narration,
            dialogue_lines=dialogue_lines,
            timed_beats=timed_beats,
        )
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=involved_characters,
            duration_seconds=contract.duration_seconds,
            dialogue_lines=dialogue_lines,
            timed_beats=timed_beats,
            requested=contract.requires_mid_frame,
        )
        start_frame_characters = self._require_contract_frame_characters(
            field_name="start_frame_characters",
            frame_characters=contract.start_frame_characters,
            involved_characters=involved_characters,
        )
        end_frame_characters = self._require_contract_frame_characters(
            field_name="end_frame_characters",
            frame_characters=contract.end_frame_characters,
            involved_characters=involved_characters,
        )
        mid_frame_characters = (
            self._require_contract_frame_characters(
                field_name="mid_frame_characters",
                frame_characters=contract.mid_frame_characters,
                involved_characters=involved_characters,
            )
            if requires_mid_frame
            else []
        )
        mid_frame_mode = self._normalize_mid_frame_mode(contract.mid_frame_mode)
        base_segment = VideoSegmentSchema.model_validate(
            {
                "segment_id": contract.segment_id,
                "chapter_number": contract.chapter_number,
                "scene_id": scene.scene_id,
                "scene_title": scene.title,
                "scene_summary": scene.summary,
                "scene_anchor": scene.scene_anchor,
                "scene_bible": scene.scene_bible.model_dump(),
                "shot_state": contract.shot_state.model_dump(),
                "continuity_link": contract.continuity_link.model_dump(),
                "title": contract.title,
                "summary": contract.summary,
                "involved_characters": involved_characters,
                "start_frame_characters": start_frame_characters,
                "mid_frame_characters": mid_frame_characters,
                "mid_frame_mode": mid_frame_mode if requires_mid_frame else "continuous",
                "end_frame_characters": end_frame_characters,
                "narration": narration,
                "dialogue_lines": dialogue_lines,
                "subtitle_lines": subtitle_lines,
                "timed_beats": timed_beats,
                "sound_effects": self._build_local_sound_effects(scene.scene_bible, timed_beats),
                "music_direction": self._build_local_music_direction(
                    novel_package=novel_package,
                    scene=scene,
                    segment_summary=contract.summary,
                ),
                "start_frame_prompt": "",
                "mid_frame_prompt": "",
                "end_frame_prompt": "",
                "duration_seconds": contract.duration_seconds,
                "requires_mid_frame": requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(contract.transition_hint),
            }
        )
        start_frame_prompt = self._build_local_start_frame_prompt(scene, base_segment)
        end_frame_prompt = self._build_local_end_frame_prompt(scene, base_segment)
        enriched_segment = base_segment.model_copy(
            update={
                "start_frame_prompt": start_frame_prompt,
                "end_frame_prompt": end_frame_prompt,
            }
        )
        mid_frame_prompt = (
            self._build_default_mid_frame_prompt(enriched_segment)
            if requires_mid_frame
            else ""
        )
        return enriched_segment.model_copy(
            update={
                "mid_frame_prompt": mid_frame_prompt,
                "character_voice_notes": [],
            }
        )

    def _build_character_profiles(
        self,
        visual_bible: CharacterVisualBibleSchema,
    ) -> list[CharacterVisualProfile]:
        return [
            CharacterVisualProfile(
                name=item.name,
                role=item.role,
                gender=item.gender,
                appearance=item.appearance,
                outfit=item.outfit,
                color_palette=item.color_palette,
                portrait_prompt=self._build_character_sheet_prompt(
                    name=item.name,
                    gender=item.gender,
                    appearance=item.appearance,
                    outfit=item.outfit,
                ),
            )
            for item in visual_bible.characters
        ]

    def _build_voice_map(self, novel_package: NovelPackage) -> dict[str, object]:
        return {
            item.name: item.voice_profile
            for item in novel_package.outline.characters
        }

    def _build_runtime_scenes(
        self,
        segments_plan: VideoSegmentPlanSchema,
        output_dir: str,
    ) -> list[VideoScene]:
        scenes = [
            VideoScene.from_dict(item.model_dump())
            for item in segments_plan.scenes
        ]
        return self._prepare_scene_master_frames(scenes, output_dir)

    def _build_runtime_segments(
        self,
        segments_plan: VideoSegmentPlanSchema,
        voice_map: dict[str, object],
    ) -> list[VideoSegment]:
        return [
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
                sound_effects=self._sanitize_segment_sound_effects(
                    item.sound_effects,
                    scene_bible=item.scene_bible,
                    prop_continuity=item.shot_state.prop_continuity,
                ),
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
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
                motion_plan=MotionPlan.from_dict(item.motion_plan.model_dump()),
            )
            for item in segments_plan.segments
        ]

    def _materialize_repaired_segment(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        target_segment: VideoSegment,
        target_scene: VideoScene,
        previous_segment: VideoSegment | None,
        repair_patch: SegmentContinuityRepairSchema,
    ) -> VideoSegmentSchema:
        target_schema = VideoSegmentSchema.model_validate(to_jsonable(target_segment))
        character_visual_bible = CharacterVisualBibleSchema(
            characters=[
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                    "appearance": item.appearance,
                    "outfit": item.outfit,
                    "color_palette": list(item.color_palette),
                    "portrait_prompt": item.portrait_prompt,
                }
                for item in project_package.character_profiles
            ]
        )
        candidate = target_schema.model_copy(
            update={
                "start_frame_prompt": repair_patch.start_frame_prompt.strip(),
                "mid_frame_prompt": repair_patch.mid_frame_prompt.strip(),
                "end_frame_prompt": repair_patch.end_frame_prompt.strip(),
                "start_frame_characters": list(repair_patch.start_frame_characters),
                "mid_frame_characters": list(repair_patch.mid_frame_characters),
                "mid_frame_mode": self._normalize_mid_frame_mode(repair_patch.mid_frame_mode),
                "end_frame_characters": list(repair_patch.end_frame_characters),
                "narration": repair_patch.narration.strip(),
                "dialogue_lines": list(repair_patch.dialogue_lines),
                "subtitle_lines": list(repair_patch.subtitle_lines),
                "timed_beats": list(repair_patch.timed_beats),
                "duration_seconds": repair_patch.duration_seconds,
                "requires_mid_frame": repair_patch.requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(repair_patch.transition_hint),
                "shot_state": repair_patch.shot_state,
                "continuity_link": repair_patch.continuity_link,
                "motion_plan": repair_patch.motion_plan,
            }
        )
        single_plan = self._normalize_segment_characters(
            VideoSegmentPlanSchema.model_validate({"segments": [candidate.model_dump()]}),
            novel_package,
            character_visual_bible,
        )
        normalized_segment = single_plan.segments[0]
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=normalized_segment.involved_characters,
            duration_seconds=normalized_segment.duration_seconds,
            dialogue_lines=normalized_segment.dialogue_lines,
            timed_beats=normalized_segment.timed_beats,
            requested=normalized_segment.requires_mid_frame,
        )
        normalized_segment = normalized_segment.model_copy(
            update={
                "requires_mid_frame": requires_mid_frame,
                "mid_frame_prompt": (
                    normalized_segment.mid_frame_prompt
                    if requires_mid_frame
                    else ""
                ),
                "mid_frame_characters": (
                    normalized_segment.mid_frame_characters
                    if requires_mid_frame
                    else []
                ),
                "mid_frame_mode": (
                    self._normalize_mid_frame_mode(normalized_segment.mid_frame_mode)
                    if requires_mid_frame
                    else "continuous"
                ),
                "subtitle_lines": (
                    normalized_segment.subtitle_lines
                    or self._build_subtitle_lines(
                        narration=normalized_segment.narration,
                        dialogue_lines=normalized_segment.dialogue_lines,
                        timed_beats=normalized_segment.timed_beats,
                    )
                ),
                "source_segment_id": normalized_segment.source_segment_id or normalized_segment.segment_id,
            }
        )
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=normalized_segment.chapter_number,
            scene_title=target_scene.title,
            scene_summary=target_scene.summary,
            scene_anchor=target_scene.scene_anchor,
            scene_bible=normalized_segment.scene_bible,
            involved_characters=normalized_segment.involved_characters,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"scene_bible": repaired_scene_bible}
        )
        repaired_shot_state = self._repair_shot_state(
            novel_package=novel_package,
            segment=normalized_segment,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"shot_state": repaired_shot_state}
        )
        previous_schema = (
            VideoSegmentSchema.model_validate(to_jsonable(previous_segment))
            if previous_segment is not None
            else None
        )
        repaired_continuity_link = self._repair_continuity_link(
            segment=normalized_segment,
            previous_segment=previous_schema,
        )
        return normalized_segment.model_copy(
            update={
                "continuity_link": repaired_continuity_link,
                "transition_hint": self._normalize_transition_hint(normalized_segment.transition_hint),
                "reuse_previous_end_frame": bool(
                    previous_schema is not None
                    and repaired_continuity_link.transition_mode == "continue"
                    and repaired_continuity_link.previous_segment_id == previous_schema.segment_id
                ),
            }
        )

    def _materialize_repaired_scene(
        self,
        *,
        novel_package: NovelPackage,
        target_scene: VideoScene,
        repair_patch: SceneContinuityRepairSchema,
    ) -> VideoScene:
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=target_scene.chapter_number,
            scene_title=target_scene.title,
            scene_summary=target_scene.summary,
            scene_anchor=repair_patch.scene_anchor.strip() or target_scene.scene_anchor,
            scene_bible=repair_patch.scene_bible,
            involved_characters=target_scene.involved_characters,
        )
        candidate_scene = VideoScene.from_dict(
            {
                **to_jsonable(target_scene),
                "scene_anchor": repair_patch.scene_anchor.strip() or target_scene.scene_anchor,
                "scene_bible": repaired_scene_bible.model_dump(),
                "scene_master_frame_url": "",
                "scene_master_frame_status": "planned",
                "scene_master_frame_error": "",
            }
        )
        return self._prepare_scene_master_frame(candidate_scene, "")
