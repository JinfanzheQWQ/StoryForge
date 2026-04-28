from __future__ import annotations

import hashlib
from math import ceil
from pathlib import Path
import re

from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneBible,
    SceneImageTask,
    SeedanceClipTask,
    SeedanceManifest,
    StoryMemoryCastEntry,
    StoryMemoryChapterState,
    StoryMemoryContinuityState,
    StoryMemoryGenerationNotes,
    StoryMemoryGlobalBible,
    StoryMemoryIdentity,
    StoryMemoryPackage,
    StoryMemoryPlanningChapterIndex,
    StoryMemoryPlanningIndex,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    ContinuityLinkSchema,
    ShotStateSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


class VideoPlanningMixin:
    DESCRIPTIVE_NARRATION_ACTION_KEYWORDS = (
        "停下脚步",
        "转身",
        "抬头",
        "低头",
        "看向",
        "望向",
        "走近",
        "递上",
        "伸手",
        "深吸一口气",
        "稍作停顿",
        "开始说话",
        "轻声说出",
        "轻声诉说",
        "继续轻声诉说",
    )
    NARRATION_FIRST_PERSON_MARKERS = (
        "我",
        "我们",
        "自己",
        "心里",
        "想起",
        "记得",
        "忽然觉得",
    )
    SCENE_MASTER_TIME_KEYWORDS = [
        "清晨",
        "早晨",
        "上午",
        "中午",
        "正午",
        "午后",
        "下午",
        "黄昏",
        "傍晚",
        "夜晚",
        "深夜",
        "凌晨",
        "次日",
        "雨夜",
    ]
    SCENE_MASTER_WEATHER_KEYWORDS = [
        "暴雨",
        "大雨",
        "雨",
        "雪",
        "雾",
        "阴天",
        "晴天",
        "晚风",
        "大风",
        "潮湿",
        "闷热",
    ]
    SCENE_MASTER_LIGHTING_KEYWORDS = [
        "霓虹",
        "逆光",
        "暖光",
        "冷光",
        "昏暗",
        "月光",
        "夕阳",
        "斜阳",
        "背光",
        "顶光",
        "窗光",
        "窗侧斜切入室内",
    ]
    SCENE_MASTER_LOCATION_KEYWORDS = [
        "紫藤花廊",
        "紫藤花架",
        "大学中心花园",
        "候车站台",
        "火车站台",
        "月台",
        "考场",
        "教室",
        "图书馆",
        "实验室",
        "礼堂",
        "宿舍",
        "走廊",
        "楼梯间",
        "天台",
        "咖啡馆",
        "餐厅",
        "酒吧",
        "病房",
        "医院",
        "办公室",
        "会议室",
        "车厢",
        "站台",
        "巷道",
        "小巷",
        "街道",
        "广场",
        "花园",
        "花廊",
        "操场",
        "教堂",
        "商场",
        "公园",
        "海边",
        "沙滩",
        "码头",
        "桥上",
        "房间",
        "客厅",
        "卧室",
    ]
    SCENE_MASTER_ENVIRONMENT_SIGNAL_KEYWORDS = [
        "考场",
        "教室",
        "花架",
        "花廊",
        "花园",
        "花海",
        "站台",
        "车厢",
        "走廊",
        "天台",
        "病房",
        "巷道",
        "街道",
        "广场",
        "窗",
        "门",
        "墙",
        "桌",
        "椅",
        "路灯",
        "长椅",
        "黑板",
        "讲台",
        "栏杆",
        "藤蔓",
        "花瓣",
        "树影",
        "夕阳",
        "斜阳",
        "月光",
        "霓虹",
        "湖",
        "湖面",
        "湖边",
        "岸边",
        "雨",
        "雪",
        "雾",
        "风",
        "空气",
        "光线",
        "小径",
        "石径",
        "石板路",
        "步道",
        "栈道",
        "入口",
        "尽头",
        "铁轨",
        "钟楼",
        "喷泉",
        "教学楼",
        "课桌",
        "答题卡",
        "画架",
        "拱门",
        "平台",
    ]
    SCENE_MASTER_PROP_KEYWORDS = [
        "长椅",
        "路灯",
        "栏杆",
        "课桌",
        "讲台",
        "黑板",
        "答题卡",
        "试卷",
        "伞",
        "雨伞",
        "对讲机",
        "广播喇叭",
        "磁带机",
        "控制台",
        "路牌",
        "石桥",
        "画架",
        "花架",
        "藤蔓",
        "铁轨",
        "行李箱",
        "书包",
        "纪念册",
        "手机",
        "台灯",
        "窗帘",
        "桌椅",
    ]
    SCENE_MASTER_PALETTE_KEYWORDS = [
        "暖金",
        "暖黄",
        "橙红",
        "深蓝",
        "灰蓝",
        "冷蓝",
        "墨绿",
        "青绿",
        "藤紫",
        "米白",
        "银灰",
        "炭黑",
        "霓虹粉",
        "猩红",
        "琥珀",
    ]

    def _build_story_memory(
        self,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
        output_dir: str,
    ) -> StoryMemoryPackage:
        visual_map = {item.name: item for item in visual_bible.characters}
        chapter_states = [
            StoryMemoryChapterState(
                chapter_number=item.number,
                chapter_title=item.title,
                chapter_summary=item.summary,
                new_facts=list(item.beats[:3]),
                resolved_threads=[item.goal] if item.goal else [],
                unresolved_threads=[item.cliffhanger] if item.cliffhanger else [],
                carry_over_summary=self._compact_story_memory_text(
                    item.summary or item.title,
                    limit=100,
                ),
                carry_over_visuals=list(novel_package.outline.visual_motifs[:3]),
            )
            for item in novel_package.outline.chapters
        ]
        planning_chapters = [
            StoryMemoryPlanningChapterIndex(chapter_number=item.number)
            for item in novel_package.outline.chapters
        ]
        return StoryMemoryPackage(
            story_identity=StoryMemoryIdentity(
                project_id=Path(output_dir).name,
                story_title=novel_package.outline.title,
                story_source_revision=self._build_story_source_revision(novel_package),
            ),
            global_story_bible=StoryMemoryGlobalBible(
                core_theme=novel_package.outline.theme or novel_package.brief.tone,
                world_rules=[
                    f"类型气质：{novel_package.brief.genre}",
                    "角色、事件与关系必须以当前小说正文为准",
                    "跨章节规划必须保持角色身份、场景时空和事件先后顺序稳定",
                ],
                narrative_promise=(
                    novel_package.outline.premise
                    or novel_package.brief.idea
                ),
                forbidden_deviations=[
                    "不得改名或新增正文里不存在的核心角色",
                    "不得把后续章节事件提前到当前章节",
                    "不得改写关键关系、关键对白和章节既定结果",
                ],
                visual_motifs=list(novel_package.outline.visual_motifs),
                ending_direction=(
                    novel_package.outline.chapters[-1].cliffhanger
                    if novel_package.outline.chapters
                    else ""
                ),
            ),
            cast_bible=[
                StoryMemoryCastEntry(
                    name=item.name,
                    gender=item.gender,
                    role=item.role,
                    relationships=[],
                    appearance_summary=self._compact_story_memory_text(
                        "；".join(
                            part
                            for part in (
                                getattr(visual_map.get(item.name), "appearance", ""),
                                getattr(visual_map.get(item.name), "outfit", ""),
                            )
                            if part
                        ),
                        limit=120,
                    ),
                    voice_summary=self._compact_story_memory_text(
                        item.voice_profile.resolved_voice_style(),
                        limit=80,
                    ),
                    personality_summary=self._compact_story_memory_text(
                        "；".join(
                            part
                            for part in (
                                item.desire,
                                item.conflict,
                                item.arc,
                            )
                            if part
                        ),
                        limit=140,
                    ),
                    hard_constraints=[
                        f"角色名固定为 {item.name}",
                        f"性别固定为 {item.gender or '未指定'}",
                        "镜头中维持稳定年龄感、体态和服装轮廓",
                    ],
                )
                for item in novel_package.outline.characters
            ],
            chapter_states=chapter_states,
            continuity_state=StoryMemoryContinuityState(
                carry_over_visuals=list(novel_package.outline.visual_motifs[:3]),
            ),
            planning_index=StoryMemoryPlanningIndex(
                chapter_count=len(novel_package.outline.chapters),
                chapters=planning_chapters,
            ),
            generation_notes=StoryMemoryGenerationNotes(
                last_successful_stage="video-character-bible",
            ),
        )

    def _build_story_source_revision(
        self,
        novel_package: NovelPackage,
    ) -> str:
        digest_source = "\n".join(
            item.markdown.strip()
            for item in novel_package.chapters
        )
        if not digest_source.strip():
            digest_source = novel_package.outline.title
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()
        return digest[:12]

    def _update_story_memory_after_chapter(
        self,
        story_memory: StoryMemoryPackage,
        *,
        novel_package: NovelPackage,
        chapter_plan: VideoSegmentPlanSchema,
        chapter_number: int,
    ) -> StoryMemoryPackage:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        chapter_state = next(
            item for item in story_memory.chapter_states if item.chapter_number == chapter_number
        )
        planning_entry = next(
            item for item in story_memory.planning_index.chapters if item.chapter_number == chapter_number
        )
        previous_chapter_state = next(
            (
                item
                for item in story_memory.chapter_states
                if item.chapter_number < chapter_number and item.generated_segment_ids
            ),
            None,
        )
        previous_exit_state = (
            dict(previous_chapter_state.exit_state)
            if previous_chapter_state is not None
            else {}
        )
        first_segment = chapter_plan.segments[0] if chapter_plan.segments else None
        last_segment = chapter_plan.segments[-1] if chapter_plan.segments else None

        chapter_state.entry_state = previous_exit_state or {
            "story_opening": chapter_outline.summary or chapter_outline.title,
        }
        chapter_state.generated_scene_ids = [item.scene_id for item in chapter_plan.scenes]
        chapter_state.generated_segment_ids = [item.segment_id for item in chapter_plan.segments]
        chapter_state.new_facts = self._unique_story_memory_items(
            [chapter_outline.summary, *chapter_outline.beats[:3]],
            limit=4,
        )
        chapter_state.resolved_threads = self._unique_story_memory_items(
            [chapter_outline.goal],
            limit=2,
        )
        chapter_state.unresolved_threads = self._unique_story_memory_items(
            [chapter_outline.cliffhanger],
            limit=2,
        )
        chapter_state.exit_state = self._build_story_memory_exit_state(last_segment)
        chapter_state.carry_over_summary = self._build_story_memory_chapter_carry_over_summary(
            chapter_plan=chapter_plan,
            chapter_state=chapter_state,
        )
        chapter_state.carry_over_visuals = self._build_story_memory_chapter_carry_over_visuals(
            chapter_plan=chapter_plan,
        )
        chapter_state.carry_over_props = self._build_story_memory_chapter_carry_over_props(
            chapter_plan=chapter_plan,
        )
        chapter_state.relationship_state = self._build_story_memory_chapter_relationship_state(
            chapter_plan=chapter_plan,
        )

        planning_entry.scene_ids = list(chapter_state.generated_scene_ids)
        planning_entry.segment_ids = list(chapter_state.generated_segment_ids)
        planning_entry.scene_count = len(planning_entry.scene_ids)
        planning_entry.segment_count = len(planning_entry.segment_ids)

        story_memory.planning_index.scene_count = sum(
            item.scene_count for item in story_memory.planning_index.chapters
        )
        story_memory.planning_index.segment_count = sum(
            item.segment_count for item in story_memory.planning_index.chapters
        )
        story_memory.generation_notes.last_planned_chapter = chapter_number
        story_memory.generation_notes.last_successful_stage = "video-segment-planner"
        if first_segment is not None and last_segment is not None:
            story_memory.continuity_state = self._build_story_memory_continuity_state(
                chapter_plan=chapter_plan,
                opening_segment=first_segment,
                ending_segment=last_segment,
            )
        return story_memory

    def _sync_story_memory_with_plan(
        self,
        story_memory: StoryMemoryPackage,
        *,
        novel_package: NovelPackage,
        plan: VideoSegmentPlanSchema,
    ) -> StoryMemoryPackage:
        scenes_by_chapter: dict[int, list[object]] = {}
        segments_by_chapter: dict[int, list[VideoSegmentSchema]] = {}
        for scene in plan.scenes:
            scenes_by_chapter.setdefault(scene.chapter_number, []).append(scene)
        for segment in plan.segments:
            segments_by_chapter.setdefault(segment.chapter_number, []).append(segment)

        for chapter_outline in novel_package.outline.chapters:
            chapter_number = chapter_outline.number
            chapter_state = next(
                item for item in story_memory.chapter_states if item.chapter_number == chapter_number
            )
            planning_entry = next(
                item for item in story_memory.planning_index.chapters if item.chapter_number == chapter_number
            )
            chapter_scenes = scenes_by_chapter.get(chapter_number, [])
            chapter_segments = segments_by_chapter.get(chapter_number, [])
            previous_segments = segments_by_chapter.get(chapter_number - 1, [])
            previous_last_segment = previous_segments[-1] if previous_segments else None
            chapter_state.entry_state = (
                self._build_story_memory_exit_state(previous_last_segment)
                if previous_last_segment is not None
                else {"story_opening": chapter_outline.summary or chapter_outline.title}
            )
            chapter_state.exit_state = self._build_story_memory_exit_state(
                chapter_segments[-1] if chapter_segments else None
            )
            chapter_state.carry_over_summary = self._build_story_memory_chapter_carry_over_summary(
                chapter_plan=VideoSegmentPlanSchema.model_validate(
                    {"scenes": [item.model_dump() for item in chapter_scenes]}
                )
                if chapter_scenes
                else VideoSegmentPlanSchema.model_validate({"scenes": []}),
                chapter_state=chapter_state,
            )
            chapter_state.carry_over_visuals = self._build_story_memory_chapter_carry_over_visuals(
                chapter_plan=VideoSegmentPlanSchema.model_validate(
                    {"scenes": [item.model_dump() for item in chapter_scenes]}
                )
                if chapter_scenes
                else VideoSegmentPlanSchema.model_validate({"scenes": []}),
            )
            chapter_state.carry_over_props = self._build_story_memory_chapter_carry_over_props(
                chapter_plan=VideoSegmentPlanSchema.model_validate(
                    {"scenes": [item.model_dump() for item in chapter_scenes]}
                )
                if chapter_scenes
                else VideoSegmentPlanSchema.model_validate({"scenes": []}),
            )
            chapter_state.relationship_state = self._build_story_memory_chapter_relationship_state(
                chapter_plan=VideoSegmentPlanSchema.model_validate(
                    {"scenes": [item.model_dump() for item in chapter_scenes]}
                )
                if chapter_scenes
                else VideoSegmentPlanSchema.model_validate({"scenes": []}),
            )
            chapter_state.generated_scene_ids = [item.scene_id for item in chapter_scenes]
            chapter_state.generated_segment_ids = [item.segment_id for item in chapter_segments]
            planning_entry.scene_ids = list(chapter_state.generated_scene_ids)
            planning_entry.segment_ids = list(chapter_state.generated_segment_ids)
            planning_entry.scene_count = len(planning_entry.scene_ids)
            planning_entry.segment_count = len(planning_entry.segment_ids)

        story_memory.planning_index.scene_count = sum(
            item.scene_count for item in story_memory.planning_index.chapters
        )
        story_memory.planning_index.segment_count = sum(
            item.segment_count for item in story_memory.planning_index.chapters
        )
        if plan.segments:
            story_memory.continuity_state = self._build_story_memory_continuity_state(
                chapter_plan=plan,
                opening_segment=plan.segments[0],
                ending_segment=plan.segments[-1],
            )
            story_memory.generation_notes.last_planned_chapter = plan.segments[-1].chapter_number
        story_memory.generation_notes.last_successful_stage = "video-segment-plan-merged"
        return story_memory

    def _build_story_memory_exit_state(
        self,
        segment: VideoSegmentSchema | None,
    ) -> dict[str, object]:
        if segment is None:
            return {}
        return {
            "segment_id": segment.segment_id,
            "scene_id": segment.scene_id,
            "scene_title": segment.scene_title,
            "summary": self._compact_story_memory_text(segment.summary, limit=100),
            "carry_over_characters": list(segment.involved_characters),
            "end_state_lock": self._compact_story_memory_text(
                segment.shot_state.end_state_lock,
                limit=100,
            ),
            "transition_hint": segment.transition_hint,
        }

    def _build_story_memory_continuity_state(
        self,
        *,
        chapter_plan: VideoSegmentPlanSchema,
        opening_segment: VideoSegmentSchema,
        ending_segment: VideoSegmentSchema,
    ) -> StoryMemoryContinuityState:
        active_relationship_state = self._unique_story_memory_items(
            [
                self._compact_story_memory_text(opening_segment.summary, limit=80),
                self._compact_story_memory_text(ending_segment.summary, limit=80),
            ],
            limit=2,
        )
        active_costume_state = [
            f"{name} 保持既定服装轮廓"
            for name in ending_segment.involved_characters[:2]
        ]
        carry_over_visuals = self._unique_story_memory_items(
            [
                *ending_segment.scene_bible.background_anchors,
                *ending_segment.scene_bible.dominant_palette,
                *chapter_plan.scenes[-1].involved_characters[:2],
            ],
            limit=6,
        )
        return StoryMemoryContinuityState(
            current_time_context=ending_segment.scene_bible.time_window,
            current_location_context=ending_segment.scene_bible.location,
            active_props=list(ending_segment.scene_bible.fixed_props[:4]),
            active_costume_state=active_costume_state,
            active_relationship_state=active_relationship_state,
            carry_over_visuals=carry_over_visuals,
        )

    def _build_story_memory_chapter_carry_over_summary(
        self,
        *,
        chapter_plan: VideoSegmentPlanSchema,
        chapter_state: StoryMemoryChapterState,
    ) -> str:
        if not chapter_plan.segments:
            return self._compact_story_memory_text(
                chapter_state.chapter_summary or chapter_state.chapter_title,
                limit=100,
            )
        last_segment = chapter_plan.segments[-1]
        summary_parts = [
            self._compact_story_memory_text(last_segment.summary, limit=60),
            self._compact_story_memory_text(last_segment.shot_state.end_state_lock, limit=60),
        ]
        scene_location = self._compact_story_memory_text(last_segment.scene_bible.location, limit=40)
        if scene_location:
            summary_parts.append(f"停留场域：{scene_location}")
        return self._compact_story_memory_text(
            "；".join(part for part in summary_parts if part),
            limit=140,
        )

    def _build_story_memory_chapter_carry_over_visuals(
        self,
        *,
        chapter_plan: VideoSegmentPlanSchema,
    ) -> list[str]:
        if not chapter_plan.segments:
            return []
        last_segment = chapter_plan.segments[-1]
        return self._unique_story_memory_items(
            [
                *last_segment.scene_bible.background_anchors,
                *last_segment.scene_bible.dominant_palette,
                self._compact_story_memory_text(last_segment.scene_anchor, limit=50),
            ],
            limit=5,
        )

    def _build_story_memory_chapter_carry_over_props(
        self,
        *,
        chapter_plan: VideoSegmentPlanSchema,
    ) -> list[str]:
        if not chapter_plan.segments:
            return []
        last_segment = chapter_plan.segments[-1]
        return self._unique_story_memory_items(
            [
                *last_segment.scene_bible.fixed_props,
                self._compact_story_memory_text(last_segment.shot_state.prop_continuity, limit=50),
            ],
            limit=4,
        )

    def _build_story_memory_chapter_relationship_state(
        self,
        *,
        chapter_plan: VideoSegmentPlanSchema,
    ) -> list[str]:
        if not chapter_plan.segments:
            return []
        opening_segment = chapter_plan.segments[0]
        ending_segment = chapter_plan.segments[-1]
        return self._unique_story_memory_items(
            [
                self._compact_story_memory_text(opening_segment.summary, limit=60),
                self._compact_story_memory_text(ending_segment.summary, limit=60),
                self._compact_story_memory_text(ending_segment.shot_state.emotion_progression, limit=60),
            ],
            limit=3,
        )

    def _merge_chapter_segment_plans(
        self,
        chapter_plans: list[VideoSegmentPlanSchema],
    ) -> VideoSegmentPlanSchema:
        merged_scenes: list[dict[str, object]] = []
        for plan in chapter_plans:
            merged_scenes.extend(
                item.model_dump()
                for item in plan.scenes
            )
        return VideoSegmentPlanSchema.model_validate({"scenes": merged_scenes})


    def _compact_story_memory_text(
        self,
        text: str,
        *,
        limit: int,
    ) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1].rstrip() + "…"

    def _unique_story_memory_items(
        self,
        values: list[str],
        *,
        limit: int,
    ) -> list[str]:
        items: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value or value in items:
                continue
            items.append(value)
            if len(items) >= limit:
                break
        return items

    def _derive_scene_bible_defaults(
        self,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        scene_title: str,
        scene_summary: str,
        scene_anchor: str,
        focus_characters: list[str],
    ) -> dict[str, object]:
        chapter = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        combined_text = " ".join(
            [
                scene_title,
                scene_summary,
                scene_anchor,
                chapter.summary,
                chapter.goal,
                chapter.key_conflict,
                chapter.cliffhanger,
            ]
        )
        return {
            "location": self._pick_scene_location(scene_anchor, scene_summary, chapter.title),
            "time_window": self._match_scene_keyword(
                combined_text,
                ["清晨", "早晨", "上午", "正午", "午后", "黄昏", "傍晚", "夜晚", "深夜", "凌晨", "次日", "雨夜"],
            ),
            "weather": self._match_scene_keyword(
                combined_text,
                ["暴雨", "雨", "雪", "雾", "阴天", "晴天", "晚风", "大风", "潮湿"],
            ),
            "lighting": self._match_scene_keyword(
                combined_text,
                ["霓虹", "逆光", "暖光", "冷光", "昏暗", "月光", "夕阳", "背光", "顶光"],
            ),
            "dominant_palette": list(novel_package.outline.visual_motifs[:3]),
            "background_anchors": self._extract_anchor_list(scene_anchor or scene_summary, max_items=4),
            "fixed_props": self._extract_anchor_list(chapter.key_conflict or chapter.cliffhanger, max_items=3),
            "spatial_layout": (
                scene_anchor
                or f"{scene_summary}；同一场景内保持机位方向、前后景层次与角色相对空间关系稳定。"
            ),
            "character_blocking": (
                f"{'、'.join(focus_characters) or '出镜角色'}在同一场景内保持稳定站位、出入口方向和运动路径。"
            ),
            "continuity_notes": (
                f"保持 {scene_title} 的地点、时间、光线、背景锚点与人物站位连续；"
                "若没有明确转场，不要改成新场景。"
            ),
        }

    def _derive_shot_state_defaults(
        self,
        *,
        summary: str,
        scene_anchor: str,
        scene_bible: object,
        focus_characters: list[str],
    ) -> dict[str, object]:
        focus_names = "、".join(focus_characters) or "当前出镜角色"
        scene_brief = self._scene_bible_brief(scene_bible)
        return {
            "framing": "以中景或能清楚交代人物关系与环境的镜头建立本段主体。",
            "camera_motion": "镜头按情绪和动作自然推进，保持同一场景内部方向稳定。",
            "blocking": (
                scene_anchor
                or f"{focus_names} 保持稳定站位、朝向、进出场路径和相互距离。"
            ),
            "action_progression": summary or "保持当前片段的核心动作推进。",
            "emotion_progression": f"{focus_names} 的情绪围绕当前片段自然递进，不要突然跳变。",
            "prop_continuity": "保持手部动作、持物、服装轮廓和关键道具状态连续。",
            "screen_direction": "保持人物运动方向、视线方向和镜头轴线一致，避免突然反轴。",
            "end_state_lock": f"尾部定格需能继续承接下一段；场景基线：{scene_brief}。",
        }

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

    def _prepare_scene_master_frames(
        self,
        scenes: list[VideoScene],
        output_dir: str,
    ) -> list[VideoScene]:
        return [
            self._prepare_scene_master_frame(scene, output_dir)
            for scene in scenes
        ]

    def _prepare_scene_master_frame(
        self,
        scene: VideoScene,
        output_dir: str,
    ) -> VideoScene:
        enriched_scene_bible = self._enrich_scene_bible_for_scene_master(scene)
        prepared_scene = VideoScene(
            scene_id=scene.scene_id,
            chapter_number=scene.chapter_number,
            title=scene.title,
            summary=scene.summary,
            scene_anchor=scene.scene_anchor,
            involved_characters=list(scene.involved_characters),
            covered_event_ids=list(scene.covered_event_ids),
            covered_event_summaries=list(scene.covered_event_summaries),
            segments=list(scene.segments),
            scene_bible=enriched_scene_bible,
            scene_transition_contract=scene.scene_transition_contract,
            scene_master_frame_path=(
                scene.scene_master_frame_path.strip()
                or f"{output_dir}/assets/frames/{scene.scene_id}_master.png"
            ),
            scene_master_frame_url=scene.scene_master_frame_url,
            scene_master_frame_status=scene.scene_master_frame_status or "planned",
            scene_master_frame_error=scene.scene_master_frame_error,
            scene_master_reference_images=list(scene.scene_master_reference_images),
            scene_master_request_info=dict(scene.scene_master_request_info),
        )
        prepared_scene.scene_master_frame_prompt = (
            scene.scene_master_frame_prompt.strip()
            or self._build_scene_master_frame_prompt(prepared_scene)
        )
        return prepared_scene

    def _enrich_scene_bible_for_scene_master(
        self,
        scene: VideoScene,
    ) -> SceneBible:
        source_scene_bible = (
            scene.scene_bible
            if isinstance(scene.scene_bible, SceneBible)
            else SceneBible.from_dict(scene.scene_bible)
        )
        source_environment_texts = self._collect_scene_master_source_texts(scene)
        environment_clauses = self._extract_scene_master_environment_clauses(scene)
        if not environment_clauses:
            return source_scene_bible

        location = self._scene_bible_value(source_scene_bible, "location").strip()
        if self._contains_scene_master_human_signal(location, scene.involved_characters):
            location = ""

        time_window = self._scene_bible_value(source_scene_bible, "time_window").strip()
        weather = self._scene_bible_value(source_scene_bible, "weather").strip()
        lighting = self._scene_bible_value(source_scene_bible, "lighting").strip()
        dominant_palette = list(source_scene_bible.dominant_palette)
        raw_spatial_layout = self._scene_bible_value(source_scene_bible, "spatial_layout").strip()
        raw_character_blocking = self._scene_bible_value(source_scene_bible, "character_blocking").strip()
        spatial_layout = self._derive_scene_master_spatial_contract(
            raw_spatial_layout,
            raw_character_blocking,
            scene.scene_anchor,
            *source_environment_texts,
            involved_characters=scene.involved_characters,
            max_clauses=3,
        )
        if not spatial_layout and not self._contains_scene_master_human_signal(
            raw_spatial_layout,
            scene.involved_characters,
        ):
            spatial_layout = raw_spatial_layout

        scene_anchor_tokens = [
            item
            for item in self._extract_anchor_list(scene.scene_anchor, max_items=4)
            if not self._contains_scene_master_human_signal(item, scene.involved_characters)
        ]
        spatial_anchor_tokens = self._extract_anchor_list(spatial_layout, max_items=4)
        background_anchors = [
            item
            for item in self._scene_bible_list(source_scene_bible, "background_anchors")
            if not self._contains_scene_master_human_signal(item, scene.involved_characters)
        ]
        fixed_props = [
            item
            for item in self._scene_bible_list(source_scene_bible, "fixed_props")
            if not self._contains_scene_master_human_signal(item, scene.involved_characters)
        ]
        fixed_props = self._filter_environment_fixed_props(fixed_props)
        environment_text = "；".join(environment_clauses)
        inferred_fixed_props = self._extract_scene_master_keyword_hits(
            [*source_environment_texts, *environment_clauses, *scene_anchor_tokens],
            self.SCENE_MASTER_PROP_KEYWORDS,
            max_items=4,
        )
        inferred_fixed_props = self._filter_environment_fixed_props(inferred_fixed_props)
        inferred_palette = self._extract_scene_master_keyword_hits(
            [*source_environment_texts, environment_text, *environment_clauses, *scene_anchor_tokens],
            self.SCENE_MASTER_PALETTE_KEYWORDS,
            max_items=3,
        )
        if not location:
            location = self._infer_scene_master_location(scene, environment_clauses)
        if not time_window:
            time_window = self._infer_scene_master_time_window(
                environment_text,
                *source_environment_texts,
                *environment_clauses,
                *scene_anchor_tokens,
            )
        if not weather:
            weather = self._match_scene_keyword(
                environment_text,
                self.SCENE_MASTER_WEATHER_KEYWORDS,
            )
        if not lighting:
            lighting = self._match_scene_keyword(
                "；".join([environment_text, *source_environment_texts, *environment_clauses, *scene_anchor_tokens]),
                self.SCENE_MASTER_LIGHTING_KEYWORDS,
            )
        if not spatial_layout:
            spatial_layout = "；".join(environment_clauses[:2])

        background_anchors = self._merge_unique_strings(
            background_anchors,
            scene_anchor_tokens,
            spatial_anchor_tokens,
            environment_clauses,
        )[:4]
        fixed_props = self._merge_unique_strings(
            fixed_props,
            inferred_fixed_props,
            self._extract_scene_master_keyword_hits(
                [spatial_layout],
                self.SCENE_MASTER_PROP_KEYWORDS,
                max_items=2,
            ),
        )[:4]
        if not dominant_palette:
            dominant_palette = inferred_palette[:3]
        continuity_notes = source_scene_bible.continuity_notes.strip() or (
            f"保持 {location or scene.title or scene.scene_id} 的地点、时间、光线、背景锚点、固定道具与空间透视稳定；"
            "不要把后续视频画面拍成另一个新场景。"
        )

        return SceneBible(
            location=location,
            time_window=time_window,
            weather=weather,
            lighting=lighting,
            dominant_palette=dominant_palette,
            background_anchors=background_anchors,
            fixed_props=fixed_props,
            spatial_layout=spatial_layout,
            character_blocking=source_scene_bible.character_blocking,
            continuity_notes=continuity_notes,
        )

    def _extract_scene_master_environment_clauses(
        self,
        scene: VideoScene,
    ) -> list[str]:
        clauses: list[str] = []
        source_texts = self._collect_scene_master_source_texts(scene)

        for source_text in source_texts:
            normalized_text = self._sanitize_image_prompt_text(source_text)
            for clause in re.split(r"[；;。！？!?]+", normalized_text):
                candidate = self._normalize_scene_master_environment_clause(
                    clause,
                    scene.involved_characters,
                )
                if not candidate or candidate in clauses:
                    continue
                clauses.append(candidate)
                if len(clauses) >= 4:
                    return clauses

        if clauses:
            return clauses

        for source_text in (scene.summary, scene.title):
            normalized_text = self._sanitize_image_prompt_text(source_text)
            for clause in re.split(r"[；;。！？!?]+", normalized_text):
                candidate = self._normalize_scene_master_environment_clause(
                    clause,
                    scene.involved_characters,
                )
                if not candidate or candidate in clauses:
                    continue
                clauses.append(candidate)
                if len(clauses) >= 4:
                    return clauses
        return clauses

    def _collect_scene_master_source_texts(
        self,
        scene: VideoScene,
    ) -> list[str]:
        source_texts: list[str] = []
        for segment in scene.segments:
            source_texts.extend(
                [
                    segment.summary,
                    segment.shot_state.framing,
                    segment.shot_state.blocking,
                    segment.continuity_link.opening_match,
                    segment.shot_state.end_state_lock,
                ]
            )
        source_texts.extend([scene.scene_anchor, scene.summary, scene.title])
        return [str(item or "").strip() for item in source_texts if str(item or "").strip()]

    def _normalize_scene_master_environment_clause(
        self,
        text: str,
        involved_characters: list[str],
    ) -> str:
        normalized = re.sub(
            r"^(场景主提示|场景提示|画面主提示|开场|尾部|推进锚点|重点呈现)\s*[：:,， ]*",
            "",
            text.strip(),
        )
        normalized = re.sub(r"\s+", " ", normalized).strip(" ，。；;")
        if len(normalized) < 4:
            return ""
        if self._contains_scene_master_human_signal(normalized, involved_characters):
            return ""
        if not any(keyword in normalized for keyword in self.SCENE_MASTER_ENVIRONMENT_SIGNAL_KEYWORDS):
            return ""
        return normalized

    def _infer_scene_master_location(
        self,
        scene: VideoScene,
        environment_clauses: list[str],
    ) -> str:
        for clause in environment_clauses:
            for keyword in self.SCENE_MASTER_LOCATION_KEYWORDS:
                if keyword in clause:
                    return keyword
        for text in (scene.scene_anchor, scene.title, scene.summary):
            normalized = str(text or "").strip(" ，。；;")
            if not normalized:
                continue
            if self._contains_scene_master_human_signal(normalized, scene.involved_characters):
                continue
            for keyword in self.SCENE_MASTER_LOCATION_KEYWORDS:
                if keyword in normalized:
                    return keyword
        for clause in environment_clauses:
            normalized = clause.strip(" ，。；;")
            if normalized:
                return normalized[:24]
        return ""

    def _infer_scene_master_time_window(self, *texts: str) -> str:
        combined = "；".join(str(item or "").strip() for item in texts if str(item or "").strip())
        if not combined:
            return ""
        direct = self._match_scene_keyword(combined, self.SCENE_MASTER_TIME_KEYWORDS)
        if direct:
            return direct
        inferred_pairs = [
            ("晨光", "清晨"),
            ("晨雾", "清晨"),
            ("朝阳", "早晨"),
            ("夕阳", "下午"),
            ("斜阳", "下午"),
            ("日落", "傍晚"),
            ("暮色", "傍晚"),
            ("夜色", "夜晚"),
            ("月光", "夜晚"),
            ("霓虹", "夜晚"),
        ]
        for cue, value in inferred_pairs:
            if cue in combined:
                return value
        return ""

    def _extract_scene_master_keyword_hits(
        self,
        texts: list[str],
        keywords: list[str],
        *,
        max_items: int,
    ) -> list[str]:
        hits: list[str] = []
        for text in texts:
            normalized = str(text or "").strip()
            if not normalized:
                continue
            for keyword in keywords:
                if keyword in normalized and keyword not in hits:
                    hits.append(keyword)
                    if len(hits) >= max_items:
                        return hits
        return hits

    def _build_scene_image_tasks(
        self,
        scenes: list[VideoScene],
        segments: list[VideoSegment],
        character_images: list[CharacterImageTask],
        profile_map: dict[str, CharacterVisualProfile],
        output_dir: str,
    ) -> list[SceneImageTask]:
        scene_map = {scene.scene_id: scene for scene in scenes}
        scene_sequence = list(scenes)
        previous_scene_by_id: dict[str, VideoScene] = {}
        for index, scene in enumerate(scene_sequence):
            if index > 0:
                previous_scene_by_id[scene.scene_id] = scene_sequence[index - 1]
        tasks: list[SceneImageTask] = []
        for segment in segments:
            scene = scene_map.get(segment.scene_id)
            prepared_scene = (
                scene
                if scene is not None
                else self._prepare_scene_master_frame(
                    VideoScene(
                        scene_id=segment.scene_id,
                        chapter_number=segment.chapter_number,
                        title=segment.scene_title,
                        summary=segment.scene_summary,
                        scene_anchor=segment.scene_anchor,
                        involved_characters=list(segment.involved_characters),
                        covered_event_ids=[],
                        covered_event_summaries=[],
                        segments=[segment],
                        scene_bible=segment.scene_bible,
                    ),
                    output_dir,
                )
            )
            reference_images = self._scene_master_reference_images(
                prepared_scene,
                previous_scene_by_id.get(prepared_scene.scene_id),
            )
            reused_previous_master = self._reuse_previous_scene_master_frame(
                prepared_scene,
                previous_scene_by_id.get(prepared_scene.scene_id),
            )
            if reused_previous_master:
                reference_images = []
            if not prepared_scene.scene_master_reference_images and reference_images:
                prepared_scene.scene_master_reference_images = list(reference_images)
            scene_master_frame_prompt = prepared_scene.scene_master_frame_prompt
            scene_master_frame_path = prepared_scene.scene_master_frame_path
            scene_master_frame_url = prepared_scene.scene_master_frame_url
            scene_master_frame_status = prepared_scene.scene_master_frame_status
            scene_master_frame_error = prepared_scene.scene_master_frame_error
            tasks.append(
                SceneImageTask(
                    segment_id=segment.segment_id,
                    scene_id=segment.scene_id,
                    scene_title=segment.scene_title,
                    scene_master_frame_prompt=scene_master_frame_prompt,
                    scene_master_frame_path=scene_master_frame_path,
                    reference_images=reference_images,
                    provider=self.scene_image_provider,
                    involved_characters=list(segment.involved_characters),
                    scene_master_frame_status=scene_master_frame_status,
                    scene_master_frame_url=scene_master_frame_url,
                    scene_master_frame_error=scene_master_frame_error,
                )
            )
        return tasks

    def _reuse_previous_scene_master_frame(
        self,
        scene: VideoScene,
        previous_scene: VideoScene | None,
    ) -> bool:
        if previous_scene is None:
            return False
        if not self._scene_reuses_previous_master_frame(scene):
            return False
        previous_url = str(previous_scene.scene_master_frame_url or "").strip()
        previous_path = str(previous_scene.scene_master_frame_path or "").strip()
        if not previous_url and not previous_path:
            return False
        scene.scene_master_frame_url = previous_url
        scene.scene_master_frame_path = previous_path or scene.scene_master_frame_path
        scene.scene_master_frame_status = previous_scene.scene_master_frame_status or "completed"
        scene.scene_master_frame_error = ""
        scene.scene_master_reference_images = []
        scene.scene_master_request_info = {
            "provider": "storyforge",
            "variant": "reuse_previous_scene_master",
            "payload": {
                "reused_from_scene_id": previous_scene.scene_id,
                "scene_master_url": previous_url,
                "scene_master_path": previous_path,
            },
            "reference_bindings": [],
        }
        return True

    def _scene_reuses_previous_master_frame(self, scene: VideoScene) -> bool:
        contract = scene.scene_transition_contract
        mode = str(contract.scene_spatial_continuity_mode or "").strip().lower()
        if mode in {
            "same_space_progression",
            "same_location_new_angle",
            "time_jump_same_location",
        }:
            return True
        return False

    def _build_seedance_manifest(
        self,
        story_title: str,
        scenes: list[VideoScene],
        segments: list[VideoSegment],
        scene_images: list[SceneImageTask],
        character_images: list[CharacterImageTask],
        output_dir: str,
    ) -> SeedanceManifest:
        scene_map = {item.segment_id: item for item in scene_images}
        scene_by_id = {item.scene_id: item for item in scenes}
        character_path_map = {
            item.character_name: item.output_path
            for item in character_images
            if item.output_path
        }
        clips: list[SeedanceClipTask] = []
        previous_clip_by_scene: dict[str, SeedanceClipTask] = {}
        previous_timeline_clip: SeedanceClipTask | None = None
        for item in segments:
            previous_scene_clip = previous_clip_by_scene.get(item.scene_id)
            current_scene = scene_by_id.get(item.scene_id)
            previous_clip = previous_scene_clip
            if previous_clip is None and self._scene_allows_previous_tail_frame(current_scene):
                previous_clip = previous_timeline_clip
            clip = SeedanceClipTask(
                segment_id=item.segment_id,
                scene_id=item.scene_id,
                title=item.title,
                prompt=self._build_seedance_clip_prompt(
                    item,
                    scene=current_scene,
                ),
                narration=item.narration,
                dialogue_lines=item.dialogue_lines,
                subtitle_lines=item.subtitle_lines,
                sound_effects=item.sound_effects,
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                scene_master_path=scene_map[item.segment_id].scene_master_frame_path,
                scene_master_url=scene_map[item.segment_id].scene_master_frame_url,
                character_image_paths=[
                    path
                    for name in item.involved_characters
                    for path in [character_path_map.get(name, "")]
                    if path
                ],
                visible_characters=list(item.involved_characters),
                motion_contract=self._build_segment_motion_contract(item),
                duration_seconds=item.duration_seconds,
                aspect_ratio=self.aspect_ratio,
                with_audio=self.seedance_config.with_audio,
                output_path=f"{output_dir}/rendered/{item.segment_id}.mp4",
            )
            if previous_clip is not None:
                clip.previous_clip_segment_id = previous_clip.segment_id
                clip.previous_clip_video_url = previous_clip.video_url
                clip.first_frame_url = previous_clip.last_frame_url
            clips.append(clip)
            previous_clip_by_scene[item.scene_id] = clip
            previous_timeline_clip = clip
        return SeedanceManifest(
            title=story_title.strip() or "未命名故事",
            model=self.seedance_config.model,
            base_url=self.seedance_config.base_url,
            clips=clips,
            notes=[
                "视频阶段提交场景母图和实际出镜角色图作为参考。",
                "每个片段由 motion_contract 描述角色在场景中的运动轨迹、动作状态和收束状态。",
                "Seedance 负责生成视频与自带音频，无需单独 TTS。",
            ],
        )

    def _scene_allows_previous_tail_frame(self, scene: VideoScene | None) -> bool:
        if scene is None:
            return False
        contract = scene.scene_transition_contract
        mode = str(contract.scene_spatial_continuity_mode or "").strip().lower()
        if mode in {
            "same_space_progression",
            "same_location_new_angle",
            "time_jump_same_location",
        }:
            return True
        return False

    def _build_segment_motion_contract(self, segment: VideoSegment) -> dict[str, object]:
        return {
            "entry_state": segment.continuity_link.opening_match,
            "motion_trajectory": segment.shot_state.action_progression,
            "exit_state": getattr(segment.shot_state, "tail_handoff", "")
            or getattr(segment.shot_state, "end_state_lock", ""),
            "camera_plan": segment.shot_state.camera_motion,
            "framing": segment.shot_state.framing,
            "staging": getattr(segment.shot_state, "staging", "")
            or getattr(segment.shot_state, "blocking", ""),
            "spatial_rules": getattr(segment.shot_state, "direction", "")
            or getattr(segment.shot_state, "screen_direction", ""),
            "timed_beats": list(segment.timed_beats),
        }

    def _normalize_segments_for_seedance(
        self,
        plan: VideoSegmentPlanSchema,
    ) -> VideoSegmentPlanSchema:
        normalized_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            if self._segment_already_normalized_for_seedance(segment):
                normalized_segments.append(self._sanitize_seedance_ready_segment(segment))
                continue
            normalized_segments.extend(self._expand_segment_for_seedance(segment))
        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=normalized_segments,
        )

    def _segment_already_normalized_for_seedance(
        self,
        segment: VideoSegmentSchema,
    ) -> bool:
        return bool(segment.source_segment_id.strip())

    def _sanitize_seedance_ready_segment(
        self,
        segment: VideoSegmentSchema,
    ) -> VideoSegmentSchema:
        shot_state = segment.shot_state.model_copy(
            update={
                "framing": self._strip_internal_segment_markers(segment.shot_state.framing),
                "camera_motion": self._strip_internal_segment_markers(segment.shot_state.camera_motion),
                "blocking": self._strip_internal_segment_markers(segment.shot_state.blocking),
                "action_progression": self._strip_internal_segment_markers(segment.shot_state.action_progression),
                "emotion_progression": self._strip_internal_segment_markers(segment.shot_state.emotion_progression),
                "prop_continuity": self._strip_internal_segment_markers(segment.shot_state.prop_continuity),
                "screen_direction": self._strip_internal_segment_markers(segment.shot_state.screen_direction),
                "end_state_lock": self._strip_internal_segment_markers(segment.shot_state.end_state_lock),
            }
        )
        continuity_link = segment.continuity_link.model_copy(
            update={
                "opening_match": self._strip_internal_segment_markers(segment.continuity_link.opening_match),
                "allowed_changes": self._strip_internal_segment_markers(segment.continuity_link.allowed_changes),
                "transition_reason": self._strip_internal_segment_markers(segment.continuity_link.transition_reason),
                "carry_over_elements": [
                    self._strip_internal_segment_markers(item)
                    for item in segment.continuity_link.carry_over_elements
                    if self._strip_internal_segment_markers(item)
                ],
            }
        )
        return segment.model_copy(
            update={
                "title": self._strip_internal_segment_markers(segment.title) or segment.title,
                "summary": self._strip_internal_segment_markers(segment.summary) or segment.summary,
                "narration": self._strip_internal_segment_markers(segment.narration) or segment.narration,
                "subtitle_lines": [
                    self._strip_internal_segment_markers(item)
                    for item in segment.subtitle_lines
                    if self._strip_internal_segment_markers(item)
                ],
                "timed_beats": [
                    self._strip_internal_segment_markers(item)
                    for item in segment.timed_beats
                    if self._strip_internal_segment_markers(item)
                ],
                "sound_effects": self._sanitize_segment_sound_effects(
                    segment.sound_effects,
                    scene_bible=segment.scene_bible,
                    prop_continuity=segment.shot_state.prop_continuity,
                ),
                "transition_hint": self._normalize_transition_hint(segment.transition_hint),
                "shot_state": shot_state,
                "continuity_link": continuity_link,
            }
        )

    def _expand_segment_for_seedance(
        self,
        segment: VideoSegmentSchema,
    ) -> list[VideoSegmentSchema]:
        narration, dialogue_lines, subtitle_lines = self._sanitize_segment_audio_tracks(
            narration=segment.narration,
            dialogue_lines=segment.dialogue_lines,
            subtitle_lines=segment.subtitle_lines,
            summary=segment.summary,
            timed_beats=segment.timed_beats,
            involved_characters=segment.involved_characters,
        )
        sound_effects = self._sanitize_segment_sound_effects(
            segment.sound_effects,
            scene_bible=segment.scene_bible,
            prop_continuity=segment.shot_state.prop_continuity,
        )
        requested_duration = max(
            segment.duration_seconds,
            self.PLANNER_MIN_DURATION_SECONDS,
            self._estimate_required_speech_duration(
                narration=narration,
                dialogue_lines=dialogue_lines,
                subtitle_lines=subtitle_lines,
            ),
        )
        normalized_duration = min(requested_duration, self.SEEDANCE_MAX_DURATION_SECONDS)
        timed_beats = segment.timed_beats or self._build_default_timed_beats(
            beat=segment.summary,
            chapter_summary=segment.summary,
            narration=narration,
            dialogue_lines=dialogue_lines,
            sound_effects=sound_effects,
            duration_seconds=requested_duration,
        )

        if requested_duration <= self.SEEDANCE_MAX_DURATION_SECONDS:
            subtitle_lines = subtitle_lines or self._build_subtitle_lines(
                narration=narration,
                dialogue_lines=dialogue_lines,
                timed_beats=timed_beats,
            )
            if normalized_duration != segment.duration_seconds:
                timed_beats = self._retime_beat_descriptions(
                    self._extract_beat_descriptions(timed_beats),
                    normalized_duration,
                )
            return [
                segment.model_copy(
                    update={
                        "duration_seconds": normalized_duration,
                        "narration": narration,
                        "dialogue_lines": dialogue_lines,
                        "timed_beats": timed_beats,
                        "subtitle_lines": subtitle_lines,
                        "sound_effects": sound_effects,
                        "transition_hint": self._normalize_transition_hint(segment.transition_hint),
                        "source_segment_id": segment.source_segment_id or segment.segment_id,
                        "subsegment_index": 1,
                        "subsegment_count": 1,
                        "shot_state": self._retarget_shot_state(
                            segment.shot_state,
                            focus_summary=segment.summary,
                            opening_focus=self._extract_beat_descriptions(timed_beats)[0]
                            if self._extract_beat_descriptions(timed_beats)
                            else segment.summary,
                            closing_focus=self._extract_beat_descriptions(timed_beats)[-1]
                            if self._extract_beat_descriptions(timed_beats)
                            else segment.summary,
                            segment_index=1,
                            segment_count=1,
                        ),
                        "continuity_link": self._retarget_continuity_link(
                            segment.continuity_link,
                            previous_segment_id=self._continuity_link_value(
                                segment.continuity_link,
                                "previous_segment_id",
                            ),
                            transition_mode=self._continuity_link_value(
                                segment.continuity_link,
                                "transition_mode",
                            )
                            or self._normalize_transition_mode_from_hint(segment.transition_hint),
                            focus_summary=segment.summary,
                            opening_focus=self._extract_beat_descriptions(timed_beats)[0]
                            if self._extract_beat_descriptions(timed_beats)
                            else segment.summary,
                            closing_focus=self._shot_state_value(segment.shot_state, "end_state_lock")
                            or segment.summary,
                            segment_index=1,
                            segment_count=1,
                        ),
                    }
                )
            ]

        split_count = ceil(requested_duration / self.SEEDANCE_MAX_DURATION_SECONDS)
        source_segment_id = segment.source_segment_id or segment.segment_id
        split_durations = self._distribute_duration(requested_duration, split_count)
        beat_chunks = self._chunk_list(self._extract_beat_descriptions(timed_beats), split_count)
        dialogue_chunks = self._chunk_dialogue_lines(dialogue_lines, split_count)
        subtitle_source = self._split_subtitle_source(
            subtitle_lines or ([narration] if narration else []),
        )
        subtitle_chunks = self._chunk_list(subtitle_source, split_count)
        sound_effect_chunks = self._chunk_list(
            self._sanitize_segment_sound_effects(
                segment.sound_effects,
                scene_bible=segment.scene_bible,
                prop_continuity=segment.shot_state.prop_continuity,
            ),
            split_count,
        )
        narration_chunks = self._chunk_narration(narration, split_count)

        expanded_segments: list[VideoSegmentSchema] = []
        previous_closing_focus = ""
        for index, clip_duration in enumerate(split_durations, start=1):
            beat_descriptions = beat_chunks[index - 1] or [segment.summary]
            dialogue_lines = dialogue_chunks[index - 1]
            narration = narration_chunks[index - 1]
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
                        "title": self._strip_internal_segment_markers(segment.title) or segment.title,
                        "summary": focus_summary,
                        "narration": narration,
                        "dialogue_lines": dialogue_lines,
                        "subtitle_lines": subtitle_lines,
                        "character_voice_notes": self._build_segment_voice_notes(
                            segment.involved_characters,
                            {},
                            existing_notes=segment.character_voice_notes,
                        ),
                        "sound_effects": sound_effect_chunks[index - 1] or segment.sound_effects[:1],
                        "timed_beats": timed_beats_chunk,
                        "duration_seconds": clip_duration,
                        "transition_hint": (
                            self._normalize_transition_hint(segment.transition_hint)
                            if index == 1
                            else "continue"
                        ),
                        "source_segment_id": source_segment_id,
                        "subsegment_index": index,
                        "subsegment_count": split_count,
                        "shot_state": self._retarget_shot_state(
                            segment.shot_state,
                            focus_summary=focus_summary,
                            opening_focus=previous_closing_focus or beat_descriptions[0],
                            closing_focus=beat_descriptions[-1],
                            segment_index=index,
                            segment_count=split_count,
                        ),
                        "continuity_link": self._retarget_continuity_link(
                            segment.continuity_link,
                            previous_segment_id=(
                                f"{segment.segment_id}_{index - 1:02d}"
                                if index > 1
                                else self._continuity_link_value(
                                    segment.continuity_link,
                                    "previous_segment_id",
                                )
                            ),
                            transition_mode=(
                                "continue"
                                if index > 1
                                else self._continuity_link_value(
                                    segment.continuity_link,
                                    "transition_mode",
                                )
                                or self._normalize_transition_mode_from_hint(segment.transition_hint)
                            ),
                            focus_summary=focus_summary,
                            opening_focus=previous_closing_focus or beat_descriptions[0],
                            closing_focus=beat_descriptions[-1],
                            segment_index=index,
                            segment_count=split_count,
                        ),
                    }
                )
            )
            previous_closing_focus = beat_descriptions[-1]

        return expanded_segments

    def _merge_unique_character_names(
        self,
        *character_lists: list[str],
    ) -> list[str]:
        merged: list[str] = []
        for character_list in character_lists:
            for name in character_list:
                if name and name not in merged:
                    merged.append(name)
        return merged

    def _merge_unique_paths(
        self,
        paths: list[str],
    ) -> list[str]:
        merged: list[str] = []
        for path in paths:
            if path and path not in merged:
                merged.append(path)
        return merged

    def _merge_unique_strings(
        self,
        *string_lists: list[str],
    ) -> list[str]:
        merged: list[str] = []
        for string_list in string_lists:
            for item in string_list:
                normalized = str(item or "").strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
        return merged

    def _scene_master_reference_images(
        self,
        scene: VideoScene,
        previous_scene: VideoScene | None,
    ) -> list[str]:
        explicit_references = self._merge_unique_paths(list(scene.scene_master_reference_images))
        if explicit_references:
            return explicit_references[:1]
        if not self._scene_allows_previous_master_reference(scene):
            return []
        if previous_scene is None:
            return []
        previous_url = str(previous_scene.scene_master_frame_url or "").strip()
        return self._merge_unique_paths([previous_url])[:1]

    def _scene_allows_previous_master_reference(self, scene: VideoScene) -> bool:
        contract = scene.scene_transition_contract
        mode = str(contract.scene_spatial_continuity_mode or "").strip().lower()
        if mode in {
            "same_space_progression",
            "same_location_new_angle",
            "time_jump_same_location",
        }:
            return True
        if mode in {"hard_cut_new_location", "uncertain"}:
            return False
        return False

    def _resolve_scene_transition_source_segment_id(
        self,
        *,
        current_segment: VideoSegment,
        current_scene: VideoScene,
        scene_map: dict[str, VideoScene],
        previous_segment: VideoSegment | None,
    ) -> str:
        if not self._is_scene_first_segment(current_segment, current_scene):
            return ""
        contract = current_scene.scene_transition_contract
        previous_scene_id = str(contract.previous_scene_id or "").strip()
        transition_mode = str(contract.transition_mode or "").strip().lower()
        if not previous_scene_id or transition_mode == "hard_cut":
            return ""
        previous_scene = scene_map.get(previous_scene_id)
        if previous_scene is not None and previous_scene.segments:
            return str(previous_scene.segments[-1].segment_id or "").strip()
        if previous_segment is not None and previous_segment.scene_id.strip() == previous_scene_id:
            return previous_segment.segment_id.strip()
        return ""

    def _is_scene_first_segment(
        self,
        current_segment: VideoSegment,
        current_scene: VideoScene | None,
    ) -> bool:
        if current_scene is None or current_segment.scene_id.strip() != current_scene.scene_id.strip():
            return False
        if not current_scene.segments:
            return True
        return current_segment.segment_id.strip() == current_scene.segments[0].segment_id.strip()

    def _normalize_transition_hint(self, transition_hint: str) -> str:
        value = transition_hint.strip().lower()
        if value in {"continue", "cut", "auto"}:
            return value
        return "auto"

    def _contains_hard_cut_hint(self, segment: VideoSegment) -> bool:
        combined = " ".join(
            [
                segment.summary,
                segment.shot_state.action_progression,
                segment.shot_state.end_state_lock,
                segment.continuity_link.opening_match,
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
        if current_segment.scene_id and previous_segment.scene_id:
            if current_segment.scene_id == previous_segment.scene_id:
                return True
        current_location = current_segment.scene_bible.location.strip()
        previous_location = previous_segment.scene_bible.location.strip()
        if current_location and previous_location and current_location == previous_location:
            current_time = current_segment.scene_bible.time_window.strip()
            previous_time = previous_segment.scene_bible.time_window.strip()
            if not current_time or not previous_time or current_time == previous_time:
                return True
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

    def _estimate_required_speech_duration(
        self,
        narration: str,
        dialogue_lines: list[str],
        subtitle_lines: list[str],
    ) -> int:
        audible_chars = self._count_speech_chars(
            "\n".join([narration, *dialogue_lines])
        )
        subtitle_chars = self._count_speech_chars("\n".join(subtitle_lines))
        speech_chars = max(audible_chars, subtitle_chars)
        if speech_chars <= 0:
            return self.PLANNER_MIN_DURATION_SECONDS
        return ceil(speech_chars / self.SPEECH_CHARS_PER_SECOND)

    def _sanitize_segment_audio_tracks(
        self,
        *,
        narration: str,
        dialogue_lines: list[str],
        subtitle_lines: list[str],
        summary: str,
        timed_beats: list[str],
        involved_characters: list[str],
    ) -> tuple[str, list[str], list[str]]:
        cleaned_narration = str(narration or "").strip()
        cleaned_dialogue_lines = [
            str(line).strip()
            for line in dialogue_lines
            if str(line).strip()
        ]
        cleaned_subtitle_lines = [
            str(line).strip()
            for line in subtitle_lines
            if str(line).strip()
        ]
        if self._should_drop_descriptive_narration(
            narration=cleaned_narration,
            dialogue_lines=cleaned_dialogue_lines,
            summary=summary,
            timed_beats=timed_beats,
            involved_characters=involved_characters,
        ):
            cleaned_narration = ""
        return cleaned_narration, cleaned_dialogue_lines, cleaned_subtitle_lines

    def _should_drop_descriptive_narration(
        self,
        *,
        narration: str,
        dialogue_lines: list[str],
        summary: str,
        timed_beats: list[str],
        involved_characters: list[str],
    ) -> bool:
        if not narration or not dialogue_lines:
            return False
        if any(marker in narration for marker in self.NARRATION_FIRST_PERSON_MARKERS):
            return False
        if any(symbol in narration for symbol in ("“", "”", "\"", "：", ":")):
            return False
        if any(name and name in narration for name in involved_characters):
            return True
        dialogue_text = " ".join(
            self._split_dialogue_speaker(line)[1] or line
            for line in dialogue_lines
        )
        beat_text = " ".join(self._extract_beat_descriptions(timed_beats))
        if self._audio_text_overlap_ratio(narration, dialogue_text) >= 0.42:
            return True
        if summary and self._audio_text_overlap_ratio(narration, summary) >= 0.58:
            return True
        if beat_text and self._audio_text_overlap_ratio(narration, beat_text) >= 0.58:
            return True
        return any(keyword in narration for keyword in self.DESCRIPTIVE_NARRATION_ACTION_KEYWORDS)

    def _audio_text_overlap_ratio(self, left: str, right: str) -> float:
        normalized_left = self._normalize_audio_similarity_text(left)
        normalized_right = self._normalize_audio_similarity_text(right)
        if not normalized_left or not normalized_right:
            return 0.0
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return min(len(normalized_left), len(normalized_right)) / max(
                len(normalized_left),
                len(normalized_right),
            )
        left_ngrams = self._audio_text_ngrams(normalized_left)
        right_ngrams = self._audio_text_ngrams(normalized_right)
        if not left_ngrams or not right_ngrams:
            return 0.0
        return len(left_ngrams & right_ngrams) / min(len(left_ngrams), len(right_ngrams))

    def _normalize_audio_similarity_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())

    def _audio_text_ngrams(self, value: str) -> set[str]:
        if len(value) <= 2:
            return {value} if value else set()
        return {value[index: index + 2] for index in range(len(value) - 1)}

    def _count_speech_chars(self, text: str) -> int:
        cleaned_lines = []
        for line in text.splitlines():
            line = re.sub(r"^\s*[^：:\n]{1,16}[：:]\s*", "", line)
            line = re.sub(r"[（(][^）)]{0,24}[）)]", "", line)
            cleaned_lines.append(line)
        compact = re.sub(r"[\s，。！？；：、“”‘’\"'.,!?;:()\[\]（）【】《》<>…—-]", "", "".join(cleaned_lines))
        return len(compact)

    def _split_long_text_unit(self, text: str) -> list[str]:
        max_chars = self.SEEDANCE_MAX_DURATION_SECONDS * self.SPEECH_CHARS_PER_SECOND
        if self._count_speech_chars(text) <= max_chars:
            return [text.strip()] if text.strip() else []

        chunks: list[str] = []
        current = ""
        current_count = 0
        for char in text.strip():
            char_count = self._count_speech_chars(char)
            if current and current_count + char_count > max_chars:
                chunks.append(current.strip())
                current = char
                current_count = char_count
            else:
                current += char
                current_count += char_count
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _chunk_dialogue_lines(
        self,
        dialogue_lines: list[str],
        chunk_count: int,
    ) -> list[list[str]]:
        units: list[str] = []
        for line in dialogue_lines:
            speaker, content = self._split_dialogue_speaker(line)
            for unit in self._split_text_units(content):
                for piece in self._split_long_text_unit(unit):
                    units.append(f"{speaker}：{piece}" if speaker else piece)
        return self._chunk_list(units, chunk_count)

    def _split_dialogue_speaker(self, line: str) -> tuple[str, str]:
        match = re.match(r"^\s*([^：:\n]{1,16})[：:]\s*(.+)$", line.strip())
        if not match:
            return "", line.strip()
        return match.group(1).strip(), match.group(2).strip()

    def _split_subtitle_source(self, subtitle_lines: list[str]) -> list[str]:
        units: list[str] = []
        for line in subtitle_lines:
            for unit in self._split_text_units(line):
                units.extend(self._split_long_text_unit(unit))
        return units

    def _chunk_narration(self, narration: str, chunk_count: int) -> list[str]:
        units: list[str] = []
        for unit in self._split_text_units(narration):
            units.extend(self._split_long_text_unit(unit))
        if not units:
            return ["" for _ in range(chunk_count)]
        return [
            "".join(chunk).strip()
            for chunk in self._chunk_list(units, chunk_count)
        ]

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

    def _scene_bible_brief(self, scene_bible: object) -> str:
        parts: list[str] = []
        location = self._scene_bible_value(scene_bible, "location")
        time_window = self._scene_bible_value(scene_bible, "time_window")
        weather = self._scene_bible_value(scene_bible, "weather")
        lighting = self._scene_bible_value(scene_bible, "lighting")
        background_anchors = self._scene_bible_list(scene_bible, "background_anchors")
        if location:
            parts.append(f"地点 {location}")
        if time_window:
            parts.append(f"时间 {time_window}")
        if weather:
            parts.append(f"天气 {weather}")
        if lighting:
            parts.append(f"光线 {lighting}")
        if background_anchors:
            parts.append(f"背景锚点 {'、'.join(background_anchors[:3])}")
        return "；".join(parts) or "保持当前场景的时空与空间连续性"

    def _shot_state_brief(self, shot_state: object) -> str:
        parts: list[str] = []
        for key, label in (
            ("framing", "景别"),
            ("camera_motion", "镜头"),
            ("blocking", "调度"),
            ("action_progression", "动作"),
            ("screen_direction", "方向"),
            ("end_state_lock", "尾部"),
        ):
            value = self._shot_state_value(shot_state, key)
            if value:
                parts.append(f"{label} {value}")
        return "；".join(parts) or "保持当前片段镜头与动作连续性"

    def _continuity_link_brief(self, continuity_link: object) -> str:
        transition_mode = self._continuity_link_value(continuity_link, "transition_mode") or "start"
        previous_segment_id = self._continuity_link_value(continuity_link, "previous_segment_id")
        opening_match = self._continuity_link_value(continuity_link, "opening_match")
        carry_over_elements = self._continuity_link_list(continuity_link, "carry_over_elements")
        transition_reason = self._continuity_link_value(continuity_link, "transition_reason")
        allowed_changes = self._continuity_link_value(continuity_link, "allowed_changes")
        parts = [f"模式 {transition_mode}"]
        if previous_segment_id:
            parts.append(f"承接 {previous_segment_id}")
        if opening_match:
            parts.append(f"开场匹配 {opening_match}")
        if carry_over_elements:
            parts.append(f"延续 {'、'.join(carry_over_elements[:4])}")
        if allowed_changes:
            parts.append(f"允许变化 {allowed_changes}")
        if transition_reason:
            parts.append(f"原因 {transition_reason}")
        return "；".join(parts)

    def _pick_scene_location(
        self,
        scene_anchor: str,
        scene_summary: str,
        chapter_title: str,
    ) -> str:
        for text in (scene_anchor, scene_summary, chapter_title):
            candidate = text.strip(" ，。；;")
            if candidate:
                return candidate[:36]
        return ""

    def _match_scene_keyword(
        self,
        text: str,
        keywords: list[str],
    ) -> str:
        for keyword in keywords:
            if keyword in text:
                return keyword
        return ""

    def _extract_anchor_list(
        self,
        text: str,
        *,
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        for token in re.split(r"[，,、；;。/\n]+", text):
            normalized = token.strip()
            if not normalized:
                continue
            if normalized not in items:
                items.append(normalized)
            if len(items) >= max_items:
                break
        return items

    def _retarget_shot_state(
        self,
        shot_state: ShotStateSchema | object,
        *,
        focus_summary: str,
        opening_focus: str,
        closing_focus: str,
        segment_index: int,
        segment_count: int,
    ) -> ShotStateSchema:
        base_payload = (
            shot_state.model_dump()
            if hasattr(shot_state, "model_dump")
            else {
                key: self._shot_state_value(shot_state, key)
                for key in (
                    "framing",
                    "camera_motion",
                    "blocking",
                    "action_progression",
                    "emotion_progression",
                    "prop_continuity",
                    "screen_direction",
                    "end_state_lock",
                )
            }
        )
        action_progression = self._strip_internal_segment_markers(
            str(base_payload.get("action_progression", "") or focus_summary)
        )
        end_state_lock = self._strip_internal_segment_markers(
            str(base_payload.get("end_state_lock", "") or closing_focus)
        )
        emotion_progression = self._strip_internal_segment_markers(
            str(base_payload.get("emotion_progression", "") or focus_summary)
        )
        if segment_count > 1:
            action_progression = self._strip_internal_segment_markers(focus_summary) or action_progression
            end_state_lock = self._strip_internal_segment_markers(closing_focus) or end_state_lock
            emotion_progression = self._strip_internal_segment_markers(
                emotion_progression or opening_focus or focus_summary
            )
        return ShotStateSchema.model_validate(
            {
                **base_payload,
                "action_progression": action_progression,
                "emotion_progression": emotion_progression,
                "end_state_lock": end_state_lock,
            }
        )

    def _retarget_continuity_link(
        self,
        continuity_link: ContinuityLinkSchema | object,
        *,
        previous_segment_id: str,
        transition_mode: str,
        focus_summary: str,
        opening_focus: str,
        closing_focus: str,
        segment_index: int,
        segment_count: int,
    ) -> ContinuityLinkSchema:
        base_payload = (
            continuity_link.model_dump()
            if hasattr(continuity_link, "model_dump")
            else {
                key: (
                    self._continuity_link_list(continuity_link, key)
                    if key == "carry_over_elements"
                    else self._continuity_link_value(continuity_link, key)
                )
                for key in (
                    "previous_segment_id",
                    "transition_mode",
                    "opening_match",
                    "carry_over_elements",
                    "allowed_changes",
                    "transition_reason",
                )
            }
        )
        normalized_mode = transition_mode.strip().lower()
        if normalized_mode not in {"start", "continue", "cut"}:
            normalized_mode = "start"
        opening_match = self._strip_internal_segment_markers(str(base_payload.get("opening_match", "") or ""))
        if normalized_mode == "continue":
            opening_match = opening_match or f"开场先承接上一段尾部：{self._strip_internal_segment_markers(opening_focus)}"
        else:
            opening_match = opening_match if normalized_mode == "cut" else ""
        carry_over_elements = list(base_payload.get("carry_over_elements", []))
        if normalized_mode == "continue" and not carry_over_elements:
            carry_over_elements = ["角色站位", "视线方向", "关键道具", "背景锚点"]
        return ContinuityLinkSchema.model_validate(
            {
                **base_payload,
                "previous_segment_id": previous_segment_id if normalized_mode == "continue" else "",
                "transition_mode": normalized_mode,
                "opening_match": opening_match,
                "carry_over_elements": carry_over_elements if normalized_mode == "continue" else [],
                "allowed_changes": (
                    self._strip_internal_segment_markers(str(base_payload.get("allowed_changes", "") or ""))
                    or (
                        f"承接开场后，允许把动作推进到：{self._strip_internal_segment_markers(focus_summary)}"
                        if normalized_mode == "continue"
                        else ("允许切到新的动作与镜头状态" if normalized_mode == "cut" else "作为起始段建立新的连续性基线")
                    )
                ),
                "transition_reason": (
                    self._strip_internal_segment_markers(str(base_payload.get("transition_reason", "") or ""))
                    or (
                        "同一场景或同一动作链的连续推进"
                        if normalized_mode == "continue"
                        else ("发生明显转场或镜头断开" if normalized_mode == "cut" else "故事或场景起始段")
                    )
                ),
            }
        )

    def _normalize_transition_mode_from_hint(self, transition_hint: str) -> str:
        normalized = self._normalize_transition_hint(transition_hint)
        if normalized == "continue":
            return "continue"
        if normalized == "cut":
            return "cut"
        return "start"
