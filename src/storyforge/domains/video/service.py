from __future__ import annotations

from math import ceil
import re
from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import AgentBackend, DryRunAgentBackend, PromptRequest
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import (
    CharacterVoiceProfile,
    NovelPackage,
)
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneImageTask,
    SeedanceClipTask,
    SeedanceManifest,
    VideoProjectPackage,
    VideoSegment,
)
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    VideoSegmentSchema,
    VideoSegmentPlanSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class NovelToVideoService:
    PLANNER_MIN_DURATION_SECONDS = 5
    SEEDANCE_MIN_DURATION_SECONDS = 2
    SEEDANCE_MAX_DURATION_SECONDS = 12

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
        self.backend = backend or DryRunAgentBackend()
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
                    "你是短视频分段导演 Agent。"
                    "请把小说章节拆成多个能独立成片的视频片段，每个片段都要有首尾帧和统一场景 prompt。"
                    "输出偏镜头分镜和环境调度，避免真人特写描述。"
                ),
                user_prompt=self._build_segment_planner_user_prompt(novel_package),
                metadata={"task": "video-segment-planner"},
            ),
            fallback=self._fallback_segment_plan(novel_package, visual_bible),
        )
        segments_plan = self._normalize_segment_characters(segments_plan, novel_package, visual_bible)
        segments_plan = self._repair_segment_plan(segments_plan, novel_package, visual_bible)
        segments_plan = self._normalize_segment_characters(segments_plan, novel_package, visual_bible)
        segments_plan = self._normalize_segments_for_seedance(segments_plan)

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
                    color_palette=item.color_palette,
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
        segments = [
            VideoSegment(
                segment_id=item.segment_id,
                chapter_number=item.chapter_number,
                title=item.title,
                summary=item.summary,
                involved_characters=item.involved_characters,
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
                end_frame_prompt=item.end_frame_prompt,
                duration_seconds=item.duration_seconds,
                transition_hint=item.transition_hint,
                source_segment_id=item.source_segment_id or item.segment_id,
                subsegment_index=item.subsegment_index,
                subsegment_count=item.subsegment_count,
                reuse_previous_end_frame=item.reuse_previous_end_frame,
            )
            for item in segments_plan.segments
        ]
        scene_images = self._build_scene_image_tasks(
            segments,
            character_images,
            profile_map,
            output_dir,
        )
        manifest = self._build_seedance_manifest(segments, scene_images, output_dir)

        return VideoProjectPackage(
            title=novel_package.outline.title,
            character_profiles=character_profiles,
            character_images=character_images,
            segments=segments,
            scene_images=scene_images,
            seedance_manifest=manifest,
            workflow_trace={
                "character_visual_bible": visual_bible.model_dump(),
                "segment_plan": segments_plan.model_dump(),
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
        except Exception:
            return fallback

    def _build_visual_bible_user_prompt(self, novel_package: NovelPackage) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        character_blocks = "\n".join(
            (
                f"- 角色名：{item.name}\n"
                f"  性别：{item.gender}\n"
                f"  身份：{item.role}\n"
                f"  欲望：{item.desire}\n"
                f"  冲突：{item.conflict}\n"
                f"  视觉锚点：{'、'.join(item.visual_signature) or '无'}\n"
                f"  角色图提示：{item.image_prompt or '无'}"
            )
            for item in novel_package.outline.characters
        )
        motifs = "、".join(novel_package.outline.visual_motifs) or "无"
        return f"""
请基于以下小说角色资料输出角色视觉卡。

- 小说标题：{novel_package.outline.title}
- 视觉母题：{motifs}
- 角色原名白名单：{allowed_names}
- 角色资料：
{character_blocks}

硬性要求：
1. `characters` 数量必须与角色原名白名单一致
2. `name` 字段只能从白名单中选择，不得改名，不得把角色写成新名字
3. 不得新增、合并或删除主要角色
4. 输出必须能直接用于角色定妆卡生成，强调稳定年龄感、稳定体型和稳定服装轮廓
5. 不要把角色写成“主角 / 男主 / 女主 / 神秘人”等泛称
6. 每个角色必须继承小说角色卡中的性别，`gender` 不得凭空改写
7. `appearance` 和 `portrait_prompt` 必须明确写出性别、年龄段、身高体态和服装轮廓
""".strip()

    def _build_segment_planner_user_prompt(self, novel_package: NovelPackage) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        chapter_blocks = "\n\n".join(
            self._build_chapter_segment_directive(novel_package, chapter_number=item.number)
            for item in novel_package.outline.chapters
        )
        return f"""
请基于以下小说大纲和章节草稿，拆出多个视频片段。

- 小说标题：{novel_package.outline.title}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色
- 每个章节都必须至少产出 1 个片段
- 视频“段”是章节内部的叙事切片，不是章节本身；同一章节可以拆成 1 段、2 段、3 段或更多
- 每章拆成几段必须由你根据该章正文内容自行判断，依据包括：事件推进、场景切换、时间跳跃、情绪转折、镜头密度、对白密度
- 不要把章节硬压成固定段数，也不要为了凑平均数机械切段
- 每个片段除画面字段外，还必须输出可直接给 Seedance 使用的旁白、角色对白、环境音、音乐方向和时间节拍
- 每个片段的 `duration_seconds` 必须由你根据剧情密度自行判断，范围限定在 {self.PLANNER_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒
- 不要把所有片段都机械写成同一个时长；对白密集、动作更复杂、信息量更大的片段可以更长
- 如果你无法判断，就优先接近 {self.segment_duration_seconds} 秒
- 每个片段必须输出 `transition_hint`，取值只能是 `continue` / `cut` / `auto`
- 片段必须覆盖全部章节，`chapter_number` 必须与来源章节一致
- 必须严格复刻章节正文已经发生的事件、情绪和对白关系，不得自行改写关键情节、改变角色关系或新增冲突
- 如果正文是告白、表白、对峙、争吵、谈判、审问、双人对话，`involved_characters` 必须同时包含对话/关系双方，不能只写一个角色
- `dialogue_lines` 中出现的所有角色，都必须进入 `involved_characters`
- `scene_prompt`、`start_frame_prompt`、`end_frame_prompt` 必须写清每个出镜角色的位置、动作和相互关系

章节拆分依据：
{chapter_blocks}
""".strip()

    def _build_chapter_segment_directive(
        self,
        novel_package: NovelPackage,
        chapter_number: int,
    ) -> str:
        chapter = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        featured = "、".join(chapter.featured_characters) or "无"
        beats = "；".join(chapter.beats) or chapter.summary
        excerpt = self._excerpt_text(draft.markdown if draft else chapter.summary, max_chars=1400)
        return (
            f"- 第 {chapter.number} 章《{chapter.title}》\n"
            "  该章应由模型自行判断拆成几段\n"
            f"  章节目标：{chapter.goal}\n"
            f"  章节摘要：{chapter.summary}\n"
            f"  关键冲突：{chapter.key_conflict}\n"
            f"  重点角色：{featured}\n"
            f"  场景节拍：{beats}\n"
            f"  正文摘录：{excerpt}"
        )

    def _excerpt_text(self, text: str, max_chars: int = 220) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    def _repair_character_visual_bible(
        self,
        visual_bible: CharacterVisualBibleSchema,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        canonical_characters = list(novel_package.outline.characters)
        canonical_names = [item.name for item in canonical_characters]
        role_map = {item.name: item.role for item in canonical_characters}
        gender_map = {item.name: item.gender for item in canonical_characters}
        fallback_map = {
            item.name: item
            for item in self._fallback_character_visual_bible(novel_package).characters
        }
        repaired: dict[str, object] = {}

        for item in visual_bible.characters:
            resolved_name = self._resolve_character_name(
                raw_name=item.name,
                canonical_names=canonical_names,
                role_map=role_map,
            ) or self._resolve_character_name(
                raw_name=item.role,
                canonical_names=canonical_names,
                role_map=role_map,
            )
            if not resolved_name or resolved_name in repaired:
                continue
            repaired_item = item.model_copy(
                update={
                    "name": resolved_name,
                    "role": role_map.get(resolved_name, item.role),
                    "gender": gender_map.get(resolved_name, item.gender),
                    "portrait_prompt": self._replace_character_aliases(
                        item.portrait_prompt,
                        {item.name: resolved_name},
                    ),
                }
            )
            repaired[resolved_name] = repaired_item

        for name in canonical_names:
            repaired.setdefault(name, fallback_map[name])

        return CharacterVisualBibleSchema(
            characters=[repaired[name] for name in canonical_names]
        )

    def _resolve_character_name(
        self,
        raw_name: str,
        canonical_names: list[str],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token
        if len(canonical_names) == 1:
            return canonical_names[0]

        generic_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主角团",
            "神秘人",
            "录音师",
            "修复师",
        }
        if token in generic_aliases:
            return canonical_names[0]

        fuzzy_matches = [
            name for name in canonical_names if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name for name, role in role_map.items() if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]
        return ""

    def _repair_segment_plan(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        fallback_plan = self._fallback_segment_plan(novel_package, visual_bible)
        fallback_by_chapter = self._group_segments_by_chapter(fallback_plan.segments)
        valid_chapters = {chapter.number for chapter in novel_package.outline.chapters}
        original_by_chapter = self._group_segments_by_chapter(
            [
                item
                for item in plan.segments
                if item.chapter_number in valid_chapters
            ]
        )

        repaired_segments: list[VideoSegmentSchema] = []
        for chapter in novel_package.outline.chapters:
            chosen = list(original_by_chapter.get(chapter.number, []))
            if chosen:
                repaired_segments.extend(chosen)
                continue

            fallback_segments = fallback_by_chapter.get(chapter.number, [])
            if fallback_segments:
                repaired_segments.append(fallback_segments[0])

        return VideoSegmentPlanSchema(segments=repaired_segments)

    def _group_segments_by_chapter(
        self,
        segments: list[VideoSegmentSchema],
    ) -> dict[int, list[VideoSegmentSchema]]:
        grouped: dict[int, list[VideoSegmentSchema]] = {}
        for item in segments:
            grouped.setdefault(item.chapter_number, []).append(item)
        return grouped

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
                # Fail closed: if the planner still returns generic labels, keep at
                # least one anchor image in the request instead of silently falling
                # back to pure text-to-image generation.
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

    def _normalize_segment_characters(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        canonical_names = [item.name for item in novel_package.outline.characters] or [
            item.name for item in visual_bible.characters
        ]
        chapter_feature_map = {
            item.number: list(item.featured_characters)
            for item in novel_package.outline.chapters
        }
        role_map = {
            item.name: item.role
            for item in novel_package.outline.characters
        }

        normalized_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            alias_map: dict[str, str] = {}
            resolved_names: list[str] = []
            for raw_name in segment.involved_characters:
                resolved = self._resolve_character_alias(
                    raw_name=raw_name,
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                    role_map=role_map,
                )
                if resolved:
                    alias_map[raw_name] = resolved
                    if resolved not in resolved_names:
                        resolved_names.append(resolved)

            if not resolved_names:
                resolved_names = self._fallback_segment_characters(
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                )
            resolved_names = self._augment_segment_characters_from_text(
                segment=segment,
                resolved_names=resolved_names,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )

            normalized_segments.append(
                segment.model_copy(
                    update={
                        "title": self._replace_character_aliases(segment.title, alias_map),
                        "involved_characters": resolved_names,
                        "summary": self._replace_character_aliases(segment.summary, alias_map),
                        "narration": self._replace_character_aliases(segment.narration, alias_map),
                        "dialogue_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.dialogue_lines
                        ],
                        "subtitle_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.subtitle_lines
                        ],
                        "character_voice_notes": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.character_voice_notes
                        ],
                        "sound_effects": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.sound_effects
                        ],
                        "music_direction": self._replace_character_aliases(
                            segment.music_direction,
                            alias_map,
                        ),
                        "timed_beats": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.timed_beats
                        ],
                        "scene_prompt": self._replace_character_aliases(segment.scene_prompt, alias_map),
                        "start_frame_prompt": self._replace_character_aliases(
                            segment.start_frame_prompt,
                            alias_map,
                        ),
                        "end_frame_prompt": self._replace_character_aliases(
                            segment.end_frame_prompt,
                            alias_map,
                        ),
                    }
                )
            )

        return VideoSegmentPlanSchema(segments=normalized_segments)

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

    def _chunk_text(self, text: str, chunk_count: int) -> list[str]:
        units = self._split_text_units(text)
        if not units:
            return ["" for _ in range(chunk_count)]
        return [
            "".join(chunk).strip()
            for chunk in self._chunk_list(units, chunk_count)
        ]

    def _split_text_units(self, text: str) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        units = re.split(r"(?<=[。！？!?；;])", cleaned)
        normalized = [item.strip() for item in units if item.strip()]
        return normalized or [cleaned]

    def _extract_beat_descriptions(self, beats: list[str]) -> list[str]:
        descriptions: list[str] = []
        for beat in beats:
            if not beat.strip():
                continue
            _, separator, remainder = beat.partition("：")
            if not separator:
                _, separator, remainder = beat.partition(":")
            descriptions.append((remainder if separator else beat).strip())
        return descriptions

    def _retime_beat_descriptions(
        self,
        descriptions: list[str],
        duration_seconds: int,
    ) -> list[str]:
        if not descriptions:
            return [f"0-{duration_seconds}秒：保持当前片段的核心动作与情绪推进。"]

        grouped_descriptions = descriptions
        if len(descriptions) > duration_seconds:
            grouped_descriptions = [
                "；".join(chunk)
                for chunk in self._chunk_list(descriptions, duration_seconds)
                if chunk
            ]

        beat_count = len(grouped_descriptions)
        timed_beats: list[str] = []
        for index, description in enumerate(grouped_descriptions):
            start = round(index * duration_seconds / beat_count)
            end = round((index + 1) * duration_seconds / beat_count)
            if index == beat_count - 1:
                end = duration_seconds
            if end <= start:
                end = min(duration_seconds, start + 1)
            if start == end:
                start = max(0, end - 1)
            timed_beats.append(f"{start}-{end}秒：{description}")
        return timed_beats

    def _fallback_subsegment_narration(
        self,
        summary: str,
        segment_index: int,
        segment_count: int,
    ) -> str:
        return f"{summary}（当前为第 {segment_index}/{segment_count} 段）"

    def _stylize_character_prompt(self, prompt: str) -> str:
        return (
            "原创虚构角色设定图，风格化概念插画，非真人摄影，动画电影质感，"
            "角色一致性强，服装和配色清晰，"
            f"{prompt}"
        )

    def _build_character_sheet_prompt(
        self,
        name: str,
        role: str,
        gender: str,
        appearance: str,
        outfit: str,
        color_palette: list[str],
        source_prompt: str,
    ) -> str:
        palette = "、".join(color_palette) if color_palette else "按人物设定控制"
        source_hint = source_prompt.strip()
        extra_hint = f"补充参考：{source_hint}。" if source_hint else ""
        return (
            "原创虚构角色定妆卡 / 三视图设定板，单角色，非真人摄影，非写实照片，"
            "偏影视概念设定与动画电影角色设计。"
            f"角色名：{name}。性别：{gender}。角色身份：{role}。"
            f"外观特征：{appearance}。"
            f"服装设定：{outfit}。"
            f"主配色：{palette}。"
            "同一张图内展示正面半身、侧面头像、全身站姿和一个表情小样，"
            "必须保持同一张脸、同一发型、同一服装、同一年龄感、同一身材比例，"
            "锁定肩宽、头身比、四肢比例和体脂观感，不要随机改设定。"
            "背景使用简洁灰底或设计板，不要复杂场景。"
            "不要因为镜头或姿势变化把角色画得更老、更幼、更胖、更瘦、更壮或更矮。"
            "只保留设定中明确出现的道具，不要额外添加盔甲、外骨骼、枪械、刀剑、奇幻饰品或科幻装备。"
            f"{extra_hint}"
        )

    def _resolve_character_alias(
        self,
        raw_name: str,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token

        generic_lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主人物",
            "lead",
            "hero",
            "protagonist",
        }
        if token.lower() in generic_lead_aliases or token in generic_lead_aliases:
            featured = self._fallback_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            return featured[0] if featured else ""

        fuzzy_matches = [
            name
            for name in canonical_names
            if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name
            for name, role in role_map.items()
            if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]

        return ""

    def _fallback_segment_characters(
        self,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
    ) -> list[str]:
        featured = [
            name
            for name in chapter_feature_map.get(chapter_number, [])
            if name in canonical_names
        ]
        if featured:
            return featured
        return canonical_names[:1]

    def _augment_segment_characters_from_text(
        self,
        segment: VideoSegmentSchema,
        resolved_names: list[str],
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> list[str]:
        combined_text = " ".join(
            [
                segment.title,
                segment.summary,
                segment.narration,
                segment.scene_prompt,
                segment.start_frame_prompt,
                segment.end_frame_prompt,
                " ".join(segment.dialogue_lines),
                " ".join(segment.subtitle_lines),
                " ".join(segment.timed_beats),
            ]
        )
        augmented = list(resolved_names)
        for name in canonical_names:
            if name in combined_text and name not in augmented:
                augmented.append(name)

        alias_candidates = list(segment.involved_characters)
        alias_candidates.extend(self._extract_dialogue_speakers(segment.dialogue_lines))
        for raw_name in alias_candidates:
            resolved = self._resolve_character_alias(
                raw_name=raw_name,
                chapter_number=segment.chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )
            if resolved and resolved not in augmented:
                augmented.append(resolved)

        if self._looks_like_two_person_scene(combined_text) and len(augmented) < 2:
            for name in chapter_feature_map.get(segment.chapter_number, []):
                if name not in augmented and name in canonical_names:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break
            for name in canonical_names:
                if len(augmented) >= 2:
                    break
                if name not in augmented:
                    augmented.append(name)

        if len(augmented) < 2 and self._dialogue_implies_two_speakers(segment.dialogue_lines):
            for name in canonical_names:
                if name not in augmented:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break

        return augmented

    def _extract_dialogue_speakers(self, dialogue_lines: list[str]) -> list[str]:
        speakers: list[str] = []
        for line in dialogue_lines:
            speaker, separator, _ = line.partition("：")
            if not separator:
                speaker, separator, _ = line.partition(":")
            if not separator:
                continue
            normalized = re.sub(r"[（(].*?[）)]", "", speaker).strip()
            if normalized and normalized not in speakers:
                speakers.append(normalized)
        return speakers

    def _looks_like_two_person_scene(self, text: str) -> bool:
        keywords = (
            "告白",
            "表白",
            "对视",
            "对话",
            "争吵",
            "质问",
            "审问",
            "谈判",
            "拥抱",
            "牵手",
            "亲吻",
            "并肩",
            "对峙",
        )
        return any(keyword in text for keyword in keywords)

    def _dialogue_implies_two_speakers(self, dialogue_lines: list[str]) -> bool:
        if len(dialogue_lines) >= 2:
            return True
        if not dialogue_lines:
            return False
        line = dialogue_lines[0]
        return "你" in line or "她" in line or "他" in line

    def _replace_character_aliases(self, text: str, alias_map: dict[str, str]) -> str:
        updated = text
        for alias, actual_name in alias_map.items():
            if alias and actual_name:
                updated = updated.replace(alias, actual_name)
        return updated

    def _build_character_consistency_notes(
        self,
        profile: CharacterVisualProfile,
    ) -> str:
        palette = "、".join(profile.color_palette) if profile.color_palette else "未指定"
        return (
            f"{profile.name} | 性别：{profile.gender} | 外观：{profile.appearance} | 服装：{profile.outfit} | "
            f"主配色：{palette} | 年龄感、脸型、肩宽、头身比、四肢比例和体型必须稳定，"
            "不要忽老忽幼、忽胖忽瘦、忽高忽矮、忽壮忽弱"
        )

    def _build_scene_character_lock(
        self,
        segment: VideoSegment,
        profile_map: dict[str, CharacterVisualProfile],
    ) -> str:
        locked_profiles: list[str] = []
        for name in segment.involved_characters:
            profile = profile_map.get(name)
            if profile is None:
                continue
            palette = "、".join(profile.color_palette) if profile.color_palette else "按设定控制"
            locked_profiles.append(
                f"{name}：性别 {profile.gender}；外观 {profile.appearance}；服装 {profile.outfit}；主配色 {palette}；"
                "同一年龄感、同一体型、同一肩宽、同一头身比、同一四肢比例、同一脸型轮廓"
            )

        if not locked_profiles:
            return (
                "若角色出镜，保持与参考设定图一致的人脸结构、发型、服装层次、主配色、"
                "年龄感、体型、肩宽和四肢比例，不要忽胖忽瘦、忽老忽幼。"
            )

        return (
            "角色锁定要求："
            + " | ".join(locked_profiles)
            + "。严格保持与参考设定图一致的人脸结构、发型、服装层次、主配色、年龄感、体型、肩宽、头身比和四肢比例，"
            "多人同屏时不得省略任何一个 involved_characters，"
            "不要把角色画得更老、更幼、更胖、更瘦、更壮、更矮或比例失真，"
            "不要新增盔甲、额外武器、外骨骼、奇幻饰品或不相关时代元素。"
        )

    def _stylize_scene_prompt(
        self,
        prompt: str,
        segment: VideoSegment,
        character_lock: str,
    ) -> str:
        characters = "、".join(segment.involved_characters) or "环境为主"
        return (
            "原创虚构场景分镜，风格化概念插画，非真人摄影，"
            "优先展示环境、光线和镜头调度，避免近景人像特写，"
            "若 involved_characters 有 2 人或以上，则这些角色必须同时出镜，不要只画一个人，"
            "每个 involved_characters 都必须按对应参考设定图还原，"
            "若角色出镜，必须保持稳定年龄感、稳定体型、稳定肩宽、稳定四肢比例和稳定脸型轮廓，"
            f"角色：{characters}，{character_lock}，{prompt}"
        )

    def _stylize_frame_prompt(
        self,
        prompt: str,
        segment: VideoSegment,
        frame_type: str,
        character_lock: str,
    ) -> str:
        characters = "、".join(segment.involved_characters) or "环境为主"
        return (
            f"{frame_type}，原创虚构电影分镜，风格化概念插画，非真人摄影，"
            f"角色：{characters}，若有双人或多人出镜要求则必须全部画出，且全部按对应参考设定图还原，{character_lock}，"
            f"保持场景连续性、稳定年龄感、稳定体型、稳定肩宽和稳定四肢比例，{prompt}"
        )

    def _build_default_timed_beats(
        self,
        beat: str,
        chapter_summary: str,
        narration: str,
        dialogue_lines: list[str],
        sound_effects: list[str],
        duration_seconds: int | None = None,
    ) -> list[str]:
        effective_duration = max(
            duration_seconds or self.segment_duration_seconds,
            self.PLANNER_MIN_DURATION_SECONDS,
        )
        dialogue = dialogue_lines[0] if dialogue_lines else "本段无明确对白，以旁白和动作推进。"
        ambience = "、".join(sound_effects[:2]) if sound_effects else "低频环境氛围声"
        return [
            f"[0s-2s] 建立环境与角色位置，画面先交代 {beat}，音频先铺 {ambience}。",
            f"[2s-4s] 旁白推进：{narration}",
            f"[4s-{effective_duration}s] 角色动作或情绪收束，关键对白：{dialogue}；结尾回到 {chapter_summary} 的悬念感。",
        ]

    def _build_seedance_clip_prompt(self, segment: VideoSegment) -> str:
        lines = [
            "请生成带原生音频的中文剧情短视频片段。",
            f"片段标题：{segment.title}",
            f"时长：{segment.duration_seconds} 秒。",
            f"角色：{'、'.join(segment.involved_characters) or '环境为主'}。",
            f"画面主提示：{segment.scene_prompt}",
            f"旁白：{segment.narration}",
        ]
        if segment.dialogue_lines:
            lines.append("角色对白：")
            lines.extend(f"- {line}" for line in segment.dialogue_lines)
        if segment.character_voice_notes:
            lines.append("角色音色锁定：")
            lines.extend(f"- {item}" for item in segment.character_voice_notes)
        if segment.sound_effects:
            lines.append("环境音/拟音：")
            lines.extend(f"- {item}" for item in segment.sound_effects)
        if segment.music_direction:
            lines.append(f"音乐方向：{segment.music_direction}")
        if segment.timed_beats:
            lines.append("时间节拍：")
            lines.extend(f"- {item}" for item in segment.timed_beats)
        if self.seedance_config.subtitle_mode == "burned_in":
            lines.append(f"硬字幕样式：{self.seedance_config.subtitle_style}")
            subtitle_lines = segment.subtitle_lines or self._build_subtitle_lines(
                narration=segment.narration,
                dialogue_lines=segment.dialogue_lines,
                timed_beats=segment.timed_beats,
            )
            if subtitle_lines:
                lines.append("硬字幕文案：")
                lines.extend(f"- {item}" for item in subtitle_lines)
            lines.append("请把上述字幕直接烧录到画面底部，不要输出外挂字幕文件。")
            lines.append("要求口播、对白、环境音与镜头动作自然同步。")
        else:
            lines.append("要求口播、对白、环境音与镜头动作自然同步，不要额外添加字幕。")
        lines.append(
            "同一角色跨镜头保持稳定音色、说话节奏、年龄感、体型、肩宽和四肢比例，不要忽老忽胖、忽瘦忽壮或突然变声。"
        )
        return "\n".join(lines)

    def _build_segment_voice_notes(
        self,
        involved_characters: list[str],
        voice_map: dict[str, CharacterVoiceProfile],
        existing_notes: list[str] | None = None,
    ) -> list[str]:
        if existing_notes:
            return list(existing_notes)
        notes: list[str] = []
        for name in involved_characters:
            voice_profile = voice_map.get(name)
            if voice_profile is not None:
                notes.append(self._format_voice_note(name, voice_profile))
            else:
                notes.append(
                    f"{name}：跨片段保持相同音色、说话速度、情绪基调和年龄感，不要突然变声"
                )
        return notes

    def _format_voice_note(
        self,
        name: str,
        voice_profile: CharacterVoiceProfile,
    ) -> str:
        parts = [
            f"整体声音：{voice_profile.resolved_voice_style()}",
            f"音色：{voice_profile.timbre or '保持已建立音色'}",
            f"语速：{voice_profile.speaking_rate or '稳定中速'}",
            f"情绪基线：{voice_profile.emotional_baseline or '稳定克制'}",
        ]
        if voice_profile.accent_or_texture:
            parts.append(f"口音/质感：{voice_profile.accent_or_texture}")
        if voice_profile.dialogue_delivery:
            parts.append(f"说话方式：{voice_profile.dialogue_delivery}")
        if voice_profile.forbidden_voice_changes:
            parts.append(
                "禁止变化：" + "、".join(voice_profile.forbidden_voice_changes)
            )
        parts.append("跨片段保持同一角色音色身份，不要突然换腔、变调或变成年龄感明显不同的声音")
        return f"{name}：" + "；".join(parts)

    def _build_subtitle_lines(
        self,
        narration: str,
        dialogue_lines: list[str],
        timed_beats: list[str],
    ) -> list[str]:
        subtitle_lines: list[str] = []
        subtitle_lines.extend(dialogue_lines[:2])
        if narration:
            subtitle_lines.append(narration)
        if not subtitle_lines and timed_beats:
            subtitle_lines.extend(timed_beats[:2])
        # Keep hard subtitles concise enough for short clips.
        return subtitle_lines[:3]
