from __future__ import annotations

from math import ceil

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneImageTask,
    SeedanceClipTask,
    SeedanceManifest,
    VideoSegment,
)
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


class VideoPlanningMixin:
    def _fallback_character_visual_bible(
        self,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        return CharacterVisualBibleSchema.model_validate(
            {
                "characters": [
                    {
                        "name": item.name,
                        "role": item.role,
                        "gender": item.gender,
                        "appearance": (
                            f"{item.gender}，具有明确轮廓、情绪感和电影感的角色外观，"
                            "年龄段和体态稳定"
                        ),
                        "outfit": "带有故事气味的功能性服装，适合持续出镜",
                        "color_palette": item.visual_signature or novel_package.outline.visual_motifs[:2],
                        "portrait_prompt": self._stylize_character_prompt(
                            item.image_prompt
                            or f"{item.name}，{item.role}，电影级肖像，{novel_package.brief.tone}"
                        ),
                    }
                    for item in novel_package.outline.characters
                ]
            }
        )

    def _fallback_segment_plan(
        self,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        segments: list[dict[str, object]] = []
        references = {item.name: item for item in visual_bible.characters}

        for chapter in novel_package.outline.chapters:
            for scene_index, beat in enumerate(chapter.beats, start=1):
                segment_id = f"ch{chapter.number:02d}-seg{scene_index:02d}"
                focus_characters = chapter.featured_characters or [
                    item.name for item in novel_package.outline.characters[:2]
                ]
                prompt_suffix = "、".join(
                    references[name].color_palette[0]
                    for name in focus_characters
                    if name in references and references[name].color_palette
                )
                segments.append(
                    {
                        "segment_id": segment_id,
                        "chapter_number": chapter.number,
                        "title": f"{chapter.title} / 片段 {scene_index}",
                        "summary": beat,
                        "involved_characters": focus_characters,
                        "narration": (
                            f"{chapter.summary} 当前片段聚焦：{beat}。"
                            f"结尾要保留 {chapter.cliffhanger} 的余波。"
                        ),
                        "dialogue_lines": [
                            f"{focus_characters[0]}（压低声音）：“{chapter.key_conflict}”"
                        ]
                        if focus_characters
                        else [],
                        "subtitle_lines": self._build_subtitle_lines(
                            narration=(
                                f"{chapter.summary} 当前片段聚焦：{beat}。"
                                f"结尾要保留 {chapter.cliffhanger} 的余波。"
                            ),
                            dialogue_lines=[
                                f"{focus_characters[0]}（压低声音）：“{chapter.key_conflict}”"
                            ]
                            if focus_characters
                            else [],
                            timed_beats=self._build_default_timed_beats(
                                beat=beat,
                                chapter_summary=chapter.summary,
                                narration=(
                                    f"{chapter.summary} 当前片段聚焦：{beat}。"
                                    f"结尾要保留 {chapter.cliffhanger} 的余波。"
                                ),
                                dialogue_lines=[
                                    f"{focus_characters[0]}（压低声音）：“{chapter.key_conflict}”"
                                ]
                                if focus_characters
                                else [],
                                sound_effects=[
                                    "环境底噪保持低频压迫感",
                                    f"突出 {'、'.join(novel_package.outline.visual_motifs[:2])} 对应的环境音",
                                ],
                            ),
                        ),
                        "sound_effects": [
                            "环境底噪保持低频压迫感",
                            f"突出 {'、'.join(novel_package.outline.visual_motifs[:2])} 对应的环境音",
                        ],
                        "music_direction": (
                            f"延续 {novel_package.brief.tone} 的悬疑氛围音乐，"
                            "结尾轻微上扬并留下悬念。"
                        ),
                        "timed_beats": self._build_default_timed_beats(
                            beat=beat,
                            chapter_summary=chapter.summary,
                            narration=(
                                f"{chapter.summary} 当前片段聚焦：{beat}。"
                                f"结尾要保留 {chapter.cliffhanger} 的余波。"
                            ),
                            dialogue_lines=[
                                f"{focus_characters[0]}（压低声音）：“{chapter.key_conflict}”"
                            ]
                            if focus_characters
                            else [],
                            sound_effects=[
                                "环境底噪保持低频压迫感",
                                f"突出 {'、'.join(novel_package.outline.visual_motifs[:2])} 对应的环境音",
                            ],
                        ),
                        "scene_prompt": (
                            f"{novel_package.outline.title}，{beat}，"
                            f"视觉母题：{'、'.join(novel_package.outline.visual_motifs)}，"
                            f"角色色彩：{prompt_suffix or novel_package.brief.tone}"
                        ),
                        "start_frame_prompt": f"首帧，{beat} 的起始瞬间，情绪压低，镜头建立环境。",
                        "end_frame_prompt": f"尾帧，指向 {chapter.cliffhanger} 的情绪或动作定格。",
                        "duration_seconds": self.segment_duration_seconds,
                        "transition_hint": "auto",
                    }
                )
        return VideoSegmentPlanSchema.model_validate({"segments": segments})

    def _build_character_image_tasks(
        self,
        character_profiles: list[CharacterVisualProfile],
        output_dir: str,
    ) -> list[CharacterImageTask]:
        return [
            CharacterImageTask(
                character_name=item.name,
                prompt=item.portrait_prompt,
                output_path=f"{output_dir}/assets/characters/{item.name}_sheet.png",
                provider=self.character_image_provider,
                image_kind="turnaround_sheet",
                consistency_notes=self._build_character_consistency_notes(item),
                use_as_reference=True,
            )
            for item in character_profiles
        ]

    def _build_scene_image_tasks(
        self,
        segments: list[VideoSegment],
        character_images: list[CharacterImageTask],
        profile_map: dict[str, CharacterVisualProfile],
        output_dir: str,
    ) -> list[SceneImageTask]:
        reference_map: dict[str, list[str]] = {}
        for item in character_images:
            if not item.use_as_reference:
                continue
            reference_map.setdefault(item.character_name, []).append(item.output_path)
        tasks: list[SceneImageTask] = []
        previous_segment: VideoSegment | None = None
        for segment in segments:
            character_lock = self._build_scene_character_lock(segment, profile_map)
            reference_images = [
                path
                for name in segment.involved_characters
                for path in reference_map.get(name, [])
            ]
            if not reference_images and character_images:
                reference_images = [character_images[0].output_path]
            continuity_source_segment_id = self._resolve_continuity_source_segment_id(
                current_segment=segment,
                previous_segment=previous_segment,
            )
            tasks.append(
                SceneImageTask(
                    segment_id=segment.segment_id,
                    scene_prompt=self._stylize_scene_prompt(
                        segment.scene_prompt,
                        segment,
                        character_lock,
                    ),
                    start_frame_prompt=self._stylize_frame_prompt(
                        segment.start_frame_prompt,
                        segment,
                        "首帧",
                        character_lock,
                    ),
                    end_frame_prompt=self._stylize_frame_prompt(
                        segment.end_frame_prompt,
                        segment,
                        "尾帧",
                        character_lock,
                    ),
                    reference_images=reference_images,
                    start_frame_path=f"{output_dir}/assets/frames/{segment.segment_id}_start.png",
                    end_frame_path=f"{output_dir}/assets/frames/{segment.segment_id}_end.png",
                    provider=self.scene_image_provider,
                    reuse_previous_end_frame=bool(continuity_source_segment_id),
                    continuity_source_segment_id=continuity_source_segment_id,
                )
            )
            previous_segment = segment
        return tasks

    def _build_seedance_manifest(
        self,
        segments: list[VideoSegment],
        scene_images: list[SceneImageTask],
        output_dir: str,
    ) -> SeedanceManifest:
        scene_map = {item.segment_id: item for item in scene_images}
        clips = [
            SeedanceClipTask(
                segment_id=item.segment_id,
                title=item.title,
                prompt=self._build_seedance_clip_prompt(item),
                narration=item.narration,
                dialogue_lines=item.dialogue_lines,
                subtitle_lines=item.subtitle_lines,
                sound_effects=item.sound_effects,
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                start_frame_path=scene_map[item.segment_id].start_frame_path,
                end_frame_path=scene_map[item.segment_id].end_frame_path,
                duration_seconds=item.duration_seconds,
                aspect_ratio=self.aspect_ratio,
                with_audio=self.seedance_config.with_audio,
                output_path=f"{output_dir}/rendered/{item.segment_id}.mp4",
            )
            for item in segments
        ]
        return SeedanceManifest(
            title="segment_video_manifest",
            model=self.seedance_config.model,
            base_url=self.seedance_config.base_url,
            clips=clips,
            notes=[
                "先生成角色图，再让场景生图阶段引用角色图作为 reference。",
                "每个视频片段使用首尾帧 prompt 约束视觉连续性。",
                "每个片段都会输出旁白、对白、音效和音乐方向，再编译成 Seedance 音视频 prompt。",
                "Seedance 负责生成视频与自带音频，无需单独 TTS。",
            ],
        )

    def _normalize_segments_for_seedance(
        self,
        plan: VideoSegmentPlanSchema,
    ) -> VideoSegmentPlanSchema:
        normalized_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            normalized_segments.extend(self._expand_segment_for_seedance(segment))
        return VideoSegmentPlanSchema(segments=normalized_segments)

    def _expand_segment_for_seedance(
        self,
        segment: VideoSegmentSchema,
    ) -> list[VideoSegmentSchema]:
        requested_duration = max(segment.duration_seconds, self.PLANNER_MIN_DURATION_SECONDS)
        normalized_duration = min(requested_duration, self.SEEDANCE_MAX_DURATION_SECONDS)
        timed_beats = segment.timed_beats or self._build_default_timed_beats(
            beat=segment.summary,
            chapter_summary=segment.summary,
            narration=segment.narration,
            dialogue_lines=segment.dialogue_lines,
            sound_effects=segment.sound_effects,
            duration_seconds=requested_duration,
        )

        if requested_duration <= self.SEEDANCE_MAX_DURATION_SECONDS:
            narration = segment.narration.strip() or segment.summary
            subtitle_lines = segment.subtitle_lines or self._build_subtitle_lines(
                narration=narration,
                dialogue_lines=segment.dialogue_lines,
                timed_beats=timed_beats,
            )
            return [
                segment.model_copy(
                    update={
                        "duration_seconds": normalized_duration,
                        "narration": narration,
                        "timed_beats": timed_beats,
                        "subtitle_lines": subtitle_lines,
                        "transition_hint": self._normalize_transition_hint(segment.transition_hint),
                        "source_segment_id": segment.source_segment_id or segment.segment_id,
                        "subsegment_index": 1,
                        "subsegment_count": 1,
                        "reuse_previous_end_frame": False,
                    }
                )
            ]

        split_count = ceil(requested_duration / self.SEEDANCE_MAX_DURATION_SECONDS)
        source_segment_id = segment.source_segment_id or segment.segment_id
        split_durations = self._distribute_duration(requested_duration, split_count)
        beat_chunks = self._chunk_list(self._extract_beat_descriptions(timed_beats), split_count)
        dialogue_chunks = self._chunk_list(segment.dialogue_lines, split_count)
        subtitle_source = segment.subtitle_lines or self._split_text_units(segment.narration)
        subtitle_chunks = self._chunk_list(subtitle_source, split_count)
        sound_effect_chunks = self._chunk_list(segment.sound_effects, split_count)
        narration_chunks = self._chunk_text(segment.narration, split_count)

        expanded_segments: list[VideoSegmentSchema] = []
        for index, clip_duration in enumerate(split_durations, start=1):
            beat_descriptions = beat_chunks[index - 1] or [segment.summary]
            dialogue_lines = dialogue_chunks[index - 1]
            narration = (
                narration_chunks[index - 1]
                or self._fallback_subsegment_narration(segment.summary, index, split_count)
            )
            timed_beats_chunk = self._retime_beat_descriptions(beat_descriptions, clip_duration)
            subtitle_lines = subtitle_chunks[index - 1] or self._build_subtitle_lines(
                narration=narration,
                dialogue_lines=dialogue_lines,
                timed_beats=timed_beats_chunk,
            )
            focus_summary = "；".join(beat_descriptions[:2]) or segment.summary
            expanded_segments.append(
                segment.model_copy(
                    update={
                        "segment_id": f"{segment.segment_id}_{index:02d}",
                        "title": f"{segment.title} / 第{index}段",
                        "summary": f"{segment.summary} 当前小段聚焦：{focus_summary}",
                        "narration": narration,
                        "dialogue_lines": dialogue_lines,
                        "subtitle_lines": subtitle_lines,
                        "character_voice_notes": self._build_segment_voice_notes(
                            segment.involved_characters,
                            {},
                            existing_notes=segment.character_voice_notes,
                        ),
                        "sound_effects": sound_effect_chunks[index - 1],
                        "timed_beats": timed_beats_chunk,
                        "scene_prompt": (
                            f"{segment.scene_prompt}，同一剧情片段的第{index}/{split_count}段，"
                            f"本段重点：{focus_summary}"
                        ),
                        "start_frame_prompt": (
                            f"{segment.start_frame_prompt} 当前子片段：第{index}/{split_count}段，"
                            f"开场重点：{beat_descriptions[0]}"
                        ),
                        "end_frame_prompt": (
                            f"{segment.end_frame_prompt} 当前子片段：第{index}/{split_count}段，"
                            f"收束重点：{beat_descriptions[-1]}"
                        ),
                        "duration_seconds": clip_duration,
                        "transition_hint": (
                            self._normalize_transition_hint(segment.transition_hint)
                            if index == 1
                            else "continue"
                        ),
                        "source_segment_id": source_segment_id,
                        "subsegment_index": index,
                        "subsegment_count": split_count,
                        "reuse_previous_end_frame": index > 1,
                    }
                )
            )

        return expanded_segments

    def _resolve_continuity_source_segment_id(
        self,
        current_segment: VideoSegment,
        previous_segment: VideoSegment | None,
    ) -> str:
        if previous_segment is None:
            return ""
        if not self._should_reuse_previous_end_frame(current_segment, previous_segment):
            return ""
        return previous_segment.segment_id

    def _should_reuse_previous_end_frame(
        self,
        current_segment: VideoSegment,
        previous_segment: VideoSegment,
    ) -> bool:
        if current_segment.chapter_number != previous_segment.chapter_number:
            return False

        if current_segment.reuse_previous_end_frame:
            return (
                current_segment.source_segment_id == previous_segment.source_segment_id
                and current_segment.subsegment_index == previous_segment.subsegment_index + 1
            )

        transition_hint = self._normalize_transition_hint(current_segment.transition_hint)
        if transition_hint == "cut":
            return False
        if transition_hint == "continue":
            return True

        if self._contains_hard_cut_hint(current_segment):
            return False
        if not self._segments_share_visual_anchor(current_segment, previous_segment):
            return False
        return True

    def _normalize_transition_hint(self, transition_hint: str) -> str:
        value = transition_hint.strip().lower()
        if value in {"continue", "cut", "auto"}:
            return value
        return "auto"

    def _contains_hard_cut_hint(self, segment: VideoSegment) -> bool:
        combined = " ".join(
            [
                segment.summary,
                segment.scene_prompt,
                segment.start_frame_prompt,
                segment.end_frame_prompt,
                segment.narration,
            ]
        )
        hard_cut_keywords = (
            "切换到",
            "转场",
            "另一边",
            "与此同时",
            "另一处",
            "数小时后",
            "第二天",
            "次日",
            "回忆",
            "闪回",
            "梦境",
            "新场景",
            "镜头切到",
            "时间跳转",
            "场景切换",
        )
        return any(keyword in combined for keyword in hard_cut_keywords)

    def _segments_share_visual_anchor(
        self,
        current_segment: VideoSegment,
        previous_segment: VideoSegment,
    ) -> bool:
        current_characters = set(current_segment.involved_characters)
        previous_characters = set(previous_segment.involved_characters)
        if current_characters & previous_characters:
            return True
        return current_segment.source_segment_id == previous_segment.source_segment_id

    def _normalize_seedance_duration(self, duration_seconds: int) -> int:
        return min(
            self.SEEDANCE_MAX_DURATION_SECONDS,
            max(duration_seconds, self.SEEDANCE_MIN_DURATION_SECONDS),
        )

    def _distribute_duration(self, total_duration: int, chunk_count: int) -> list[int]:
        base, remainder = divmod(total_duration, chunk_count)
        return [
            base + (1 if index < remainder else 0)
            for index in range(chunk_count)
        ]

    def _chunk_list(self, items: list[str], chunk_count: int) -> list[list[str]]:
        if chunk_count <= 1:
            return [list(items)]
        if not items:
            return [[] for _ in range(chunk_count)]

        base, remainder = divmod(len(items), chunk_count)
        chunks: list[list[str]] = []
        cursor = 0
        for index in range(chunk_count):
            size = base + (1 if index < remainder else 0)
            chunks.append(list(items[cursor: cursor + size]))
            cursor += size
        return chunks
