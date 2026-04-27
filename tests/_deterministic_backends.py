from __future__ import annotations

import re

from storyforge.agents.base import AgentResult, PromptRequest
from storyforge.domains.novel.contracts import StoryBrief
from storyforge.domains.novel.schemas import (
    CastAnalysisSchema,
    CastRelationshipSchema,
    CastSlotSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    EditorialReviewSchema,
    StoryArchitectureSchema,
    StoryDraftSetSchema,
)
from storyforge.domains.novel.service import NovelGeneratorService
from storyforge.domains.video.schemas import (
    ChapterCoveragePlanSchema,
    ChapterSceneStructureSchema,
    SceneContinuityRepairSchema,
    SceneSegmentChunkPlanSchema,
    SceneSegmentContractBatchSchema,
    SegmentContinuityRepairSchema,
    VideoSegmentPlanSchema,
)


_LINE_PATTERNS = {
    "title_hint": re.compile(r"-\s*标题(?:参考)?：(?P<value>.+)"),
    "idea": re.compile(r"-\s*核心创意：(?P<value>.+)"),
    "genre": re.compile(r"-\s*类型：(?P<value>.+)"),
    "tone": re.compile(r"-\s*语气：(?P<value>.+)"),
    "target_audience": re.compile(r"-\s*目标读者：(?P<value>.+)"),
    "chapter_count": re.compile(r"-\s*章节数：(?P<value>\d+)"),
    "total_word_target": re.compile(r"-\s*总字数目标：(?P<value>\d+)"),
    "must_include": re.compile(r"-\s*必须包含：(?P<value>.+)"),
    "style_keywords": re.compile(r"-\s*风格关键词：(?P<value>.+)"),
}

_ALLOWED_NAMES_PATTERN = re.compile(r"-\s*角色原名白名单：(?P<value>.+)")
_NOVEL_TITLE_PATTERN = re.compile(r"-\s*小说标题：(?P<value>.+)")
_CHAPTER_DIRECTIVE_PATTERN = re.compile(
    r"-\s*第\s*(?P<number>\d+)\s*章《(?P<title>[^》]+)》"
)
_CHAPTER_SUMMARY_PATTERN = re.compile(r"章节摘要：(?P<value>.+)")
_CHAPTER_EVENT_ID_PATTERN = re.compile(r"-\s*(?P<event_id>ch\d{2}-ev\d{2})[:：]")
_CHARACTER_BLOCK_PATTERN = re.compile(
    r"-\s*角色名：(?P<name>.+?)\n"
    r"\s*性别：(?P<gender>.+?)\n"
    r"\s*身份：(?P<role>.+?)\n"
    r"\s*欲望：(?P<desire>.+?)\n"
    r"\s*冲突：(?P<conflict>.+?)\n"
    r"\s*视觉锚点：(?P<visual>.+?)\n"
    r"\s*角色图提示：(?P<prompt>.+?)(?:\n{2,}|\Z)",
    re.S,
)
_MISSING_SLOTS_PATTERN = re.compile(r"缺失 slots：(?P<value>[^\n。]+)")


def _split_items(raw: str) -> list[str]:
    value = raw.strip()
    if not value or value == "无":
        return []
    return [
        item.strip()
        for item in re.split(r"[，,、]", value)
        if item.strip()
    ]


def _extract_line_value(text: str, key: str, default: str = "") -> str:
    pattern = _LINE_PATTERNS[key]
    match = pattern.search(text)
    if match is None:
        return default
    return match.group("value").strip()


def _parse_brief(user_prompt: str) -> StoryBrief:
    title_hint = _extract_line_value(user_prompt, "title_hint", "测试故事")
    idea = _extract_line_value(user_prompt, "idea", f"{title_hint} 的测试创意")
    genre = _extract_line_value(user_prompt, "genre", "剧情短篇")
    tone = _extract_line_value(user_prompt, "tone", "克制、电影感")
    target_audience = _extract_line_value(user_prompt, "target_audience", "通用读者")
    chapter_count = int(_extract_line_value(user_prompt, "chapter_count", "1") or 1)
    total_word_target = int(_extract_line_value(user_prompt, "total_word_target", "1200") or 1200)
    must_include = _split_items(_extract_line_value(user_prompt, "must_include", ""))
    style_keywords = _split_items(_extract_line_value(user_prompt, "style_keywords", ""))
    return StoryBrief(
        title_hint=title_hint,
        idea=idea,
        genre=genre,
        tone=tone,
        target_audience=target_audience,
        chapter_count=chapter_count,
        total_word_target=total_word_target,
        must_include=must_include,
        style_keywords=style_keywords,
    )


class DeterministicStoryBackend:
    def __init__(self) -> None:
        self.helper = NovelGeneratorService()

    def generate(self, request: PromptRequest) -> AgentResult:
        return AgentResult(
            content=f"deterministic story backend: {request.metadata.get('task', 'generic')}",
            provider="deterministic-story",
        )

    def generate_structured(self, request: PromptRequest, schema):
        brief = _parse_brief(request.user_prompt)
        (
            architecture,
            story_draft_set,
            cast_analysis,
            character_roster,
            chapter_plan_set,
            editorial_review,
        ) = self._build_story_bundle(brief)

        task = str(request.metadata.get("task", "")).strip()
        if task in {"story-architect", "story-architect-analysis"}:
            return architecture
        if task == "story-drafter":
            return story_draft_set
        if task == "cast-analyzer":
            return cast_analysis
        if task == "character-designer":
            return character_roster
        if task == "character-designer-backfill":
            return self._build_character_backfill(request, character_roster)
        if task == "chapter-planner":
            return chapter_plan_set
        if task == "editor-review":
            return editorial_review
        return schema.model_validate({})

    def _build_story_bundle(
        self,
        brief: StoryBrief,
    ) -> tuple[
        StoryArchitectureSchema,
        StoryDraftSetSchema,
        CastAnalysisSchema,
        CharacterRosterSchema,
        ChapterPlanSetSchema,
        EditorialReviewSchema,
    ]:
        architecture = StoryArchitectureSchema(
            title=brief.title_hint,
            premise=f"{brief.idea} 的核心事件在限定篇幅内持续升级。",
            theme=f"围绕 {brief.tone} 气质下的人物选择与代价。",
            setting="具有明确空间辨识度的核心场景",
            story_engine="每一章都推进同一条主线事件，并为下一段制造更高压力。",
            visual_motifs=brief.style_keywords[:3] or ["雨夜", "灯光", "回声"],
            tone_notes=[brief.tone, "镜头感", "连续推进"],
        )

        if self._is_relationship_story(brief):
            character_specs = [
                ("lead_1", "林栀", "主角 / 主动方", "女"),
                ("lead_2", "周骁", "关键对位角色 / 回应方", "男"),
            ]
            story_draft_set = self._build_relationship_story_draft_set(brief, character_specs)
            cast_analysis = CastAnalysisSchema(
                story_shape="dual_relationship_with_supporting_cast",
                recommended_core_cast_count=2,
                requires_dual_leads=True,
                explicit_counterpart=True,
                prefers_male_female_pair=True,
                cast_strategy="严格保留关系双方，不新增无证据核心角色。",
                chapter_participation_rule="关键章节中两位核心角色必须共同参与事件推进。",
                ordering_rule="先输出 lead_1，再输出 lead_2。",
                slots=[
                    CastSlotSchema(
                        slot_id="lead_1",
                        tier="lead",
                        story_function="protagonist",
                        brief_label="林栀",
                        source_evidence=["林栀"],
                        gender_hint="女",
                        objective="主动推动核心关系事件发生。",
                        must_appear_in=["opening", "midpoint", "climax", "ending"],
                        order_priority=1,
                        notes="主动发起关系动作的一方。",
                    ),
                    CastSlotSchema(
                        slot_id="lead_2",
                        tier="lead",
                        story_function="love_interest",
                        brief_label="周骁",
                        source_evidence=["周骁"],
                        gender_hint="男",
                        objective="对关系动作作出回应并改变局势。",
                        must_appear_in=["opening", "climax", "ending"],
                        order_priority=2,
                        notes="关键回应方。",
                    ),
                ],
                relationships=[
                    CastRelationshipSchema(
                        source_slot_id="lead_1",
                        target_slot_id="lead_2",
                        relationship_type="core_relationship",
                        priority=1,
                        summary="两人的互动直接驱动主线。",
                    )
                ],
            )
        else:
            character_specs = [
                ("lead_1", "林深", "主角", "男"),
            ]
            story_draft_set = self._build_single_lead_story_draft_set(brief, character_specs[0][1])
            cast_analysis = CastAnalysisSchema(
                story_shape="single_lead_with_supporting_cast",
                recommended_core_cast_count=1,
                requires_dual_leads=False,
                explicit_counterpart=False,
                prefers_male_female_pair=False,
                cast_strategy="只保留正文中有稳定证据的核心主角。",
                chapter_participation_rule="主角必须持续参与所有章节。",
                ordering_rule="先输出 lead_1。",
                slots=[
                    CastSlotSchema(
                        slot_id="lead_1",
                        tier="lead",
                        story_function="protagonist",
                        brief_label="林深",
                        source_evidence=["林深"],
                        gender_hint="男",
                        objective="推动主线真相调查或核心事件。",
                        must_appear_in=["opening", "midpoint", "climax", "ending"],
                        order_priority=1,
                        notes="唯一稳定主角。",
                    )
                ],
                relationships=[],
            )

        character_roster = CharacterRosterSchema.model_validate(
            {
                "characters": [
                    {
                        "cast_slot_id": slot_id,
                        "name": name,
                        "role": role,
                        "gender": gender,
                        "desire": "完成当前故事的核心目标。",
                        "conflict": "在推进事件时不断遭遇阻力。",
                        "arc": "从犹豫走向主动承担。",
                        "visual_signature": architecture.visual_motifs[:2] or ["灯光", "雨夜"],
                        "voice_style": f"{brief.tone} 下稳定可复用的角色声线",
                        "voice_profile": {
                            "voice_style": f"{brief.tone} 下稳定可复用的角色声线",
                            "timbre": "清晰克制",
                            "speaking_rate": "中速",
                            "emotional_baseline": "克制但有压力感",
                            "accent_or_texture": "普通话",
                            "dialogue_delivery": "短句推进信息",
                            "forbidden_voice_changes": ["不要突然切换到明显不同的年龄感"],
                        },
                        "image_prompt": f"{name}，{gender}，{role}，体态稳定，适合角色定妆图。",
                    }
                    for slot_id, name, role, gender in character_specs
                ]
            }
        )

        chapter_plan_set = ChapterPlanSetSchema.model_validate(
            {
                "chapters": [
                    {
                        "number": index,
                        "title": chapter.title,
                        "goal": f"推进《{brief.title_hint}》的核心事件。",
                        "summary": chapter.summary,
                        "key_conflict": "角色必须在更高压力下继续推进。",
                        "beats": [
                            chapter.summary,
                            "角色作出关键选择，局势随之变化。",
                        ],
                        "cliffhanger": "章节末尾留下下一段必须回应的新问题。",
                        "featured_characters": [spec[1] for spec in character_specs],
                    }
                    for index, chapter in enumerate(story_draft_set.chapters, start=1)
                ]
            }
        )

        editorial_review = EditorialReviewSchema(
            overall_verdict="deterministic review ok",
            strengths=["结构完整", "角色与章节对应清晰"],
            continuity_risks=["测试后端只提供最小可用结构"],
            revision_notes=["仅用于自动化测试，不代表最终创作质量"],
        )
        return (
            architecture,
            story_draft_set,
            cast_analysis,
            character_roster,
            chapter_plan_set,
            editorial_review,
        )

    def _is_relationship_story(self, brief: StoryBrief) -> bool:
        text = f"{brief.title_hint} {brief.idea} {brief.genre}"
        return any(
            token in text
            for token in ("告白", "恋", "前任", "重逢", "暧昧", "情侣", "表白")
        )

    def _build_relationship_story_draft_set(
        self,
        brief: StoryBrief,
        character_specs: list[tuple[str, str, str, str]],
    ) -> StoryDraftSetSchema:
        lead_a = character_specs[0][1]
        lead_b = character_specs[1][1]
        chapters = []
        for number in range(1, brief.chapter_count + 1):
            title = f"第 {number} 章：{brief.title_hint}"
            summary = f"{lead_a} 与 {lead_b} 围绕核心事件正面相遇，关系在压力中推进。"
            markdown = (
                f"# {title}\n\n"
                f"{lead_a} 在这一章主动找到 {lead_b}，终于把一直压着的话说出口。"
                f"{lead_b} 没有离开，而是在短暂沉默后给出关键回应。"
                "两人的情绪和关系因此发生明确变化。"
            )
            chapters.append(
                {
                    "number": number,
                    "title": title,
                    "summary": summary,
                    "markdown": markdown,
                    "visual_hooks": ["两人同框", "关系推进"],
                    "continuity_refs": ["关系状态变化", "下一章压力继续升级"],
                }
            )
        return StoryDraftSetSchema.model_validate({"chapters": chapters})

    def _build_single_lead_story_draft_set(
        self,
        brief: StoryBrief,
        protagonist_name: str,
    ) -> StoryDraftSetSchema:
        chapters = []
        for number in range(1, brief.chapter_count + 1):
            title = f"第 {number} 章：{brief.title_hint}"
            summary = f"{protagonist_name} 独自推进主线，在当前场景中获得新的线索。"
            markdown = (
                f"# {title}\n\n"
                f"{protagonist_name} 带着疑问进入新的现场，逐步逼近这起事件真正的核心。"
                "随着线索出现，风险也同步上升。"
            )
            chapters.append(
                {
                    "number": number,
                    "title": title,
                    "summary": summary,
                    "markdown": markdown,
                    "visual_hooks": ["主角推进", "现场线索"],
                    "continuity_refs": ["线索递进", "风险升级"],
                }
            )
        return StoryDraftSetSchema.model_validate({"chapters": chapters})

    def _build_character_backfill(
        self,
        request: PromptRequest,
        roster: CharacterRosterSchema,
    ) -> CharacterRosterSchema:
        match = _MISSING_SLOTS_PATTERN.search(request.user_prompt)
        if match is None:
            return roster
        missing_slots = [
            item.strip()
            for item in re.split(r"[、,，]", match.group("value"))
            if item.strip()
        ]
        filtered = [
            item for item in roster.characters if item.cast_slot_id in missing_slots
        ]
        return CharacterRosterSchema(characters=filtered)


class DeterministicVideoBackend:
    def generate(self, request: PromptRequest) -> AgentResult:
        return AgentResult(
            content=f"deterministic video backend: {request.metadata.get('task', 'generic')}",
            provider="deterministic-video",
        )

    def generate_structured(self, request: PromptRequest, schema):
        task = str(request.metadata.get("task", "")).strip()
        if task == "video-character-bible":
            return self._build_character_visual_bible(request)
        if task == "video-chapter-event-planner":
            return self._build_chapter_event_plan(request)
        if task == "video-chapter-scene-planner":
            return self._build_scene_structure(request)
        if task == "video-scene-chunk-planner":
            return self._build_scene_chunk_plan(request)
        if task == "video-scene-segment-planner":
            return self._build_scene_segment_contracts(request)
        if task == "video-segment-planner":
            return self._build_segment_plan(request)
        if task == "segment-continuity-repair":
            return self._build_segment_repair(request)
        if task == "scene-continuity-repair":
            return self._build_scene_repair(request)
        return schema.model_validate({})

    def _build_character_visual_bible(self, request: PromptRequest):
        characters: list[dict[str, object]] = []
        seen_names: set[str] = set()
        for match in _CHARACTER_BLOCK_PATTERN.finditer(request.user_prompt):
            name = match.group("name").strip()
            seen_names.add(name)
            characters.append(
                {
                    "name": name,
                    "role": match.group("role").strip(),
                    "gender": match.group("gender").strip(),
                    "appearance": f"{match.group('gender').strip()}，年龄感稳定，体态稳定，{match.group('visual').strip()}",
                    "outfit": "统一轮廓感服装设定，便于持续出镜",
                    "color_palette": _split_items(match.group("visual")) or ["米白", "灰蓝"],
                    "portrait_prompt": f"{name}，{match.group('gender').strip()}，{match.group('prompt').strip()}",
                }
            )

        allowed_names = self._allowed_names(request.user_prompt)
        for name in allowed_names:
            if name in seen_names:
                continue
            characters.append(
                {
                    "name": name,
                    "role": self._extract_character_field(request.user_prompt, name, "身份") or "主角",
                    "gender": self._extract_character_field(request.user_prompt, name, "性别") or "未指定",
                    "appearance": "年龄感稳定，体态稳定",
                    "outfit": "统一轮廓感服装设定，便于持续出镜",
                    "color_palette": ["米白", "灰蓝"],
                    "portrait_prompt": f"{name}，角色定妆图。",
                }
            )
        return {"characters": characters}

    def _build_scene_structure(self, request: PromptRequest):
        story_title = self._novel_title(request.user_prompt)
        allowed_names = self._allowed_names(request.user_prompt)
        chapter_directives = self._chapter_directives(request.user_prompt)
        event_ids = self._chapter_event_ids(request.user_prompt)
        focus_characters = allowed_names[:2] or ["主角"]
        scenes: list[dict[str, object]] = []
        for chapter_number, chapter_title, chapter_summary in chapter_directives:
            scene_id = f"ch{chapter_number:02d}-sc01"
            summary = chapter_summary or f"{chapter_title} 的核心事件。"
            chapter_event_ids = [
                event_id
                for event_id in event_ids
                if event_id.startswith(f"ch{chapter_number:02d}-")
            ]
            scenes.append(
                {
                    "scene_id": scene_id,
                    "chapter_number": chapter_number,
                    "title": f"{chapter_title} / 场景 1",
                    "summary": summary,
                    "scene_anchor": f"{story_title} 第 {chapter_number} 章的连续性场景基线",
                    "scene_bible": {
                        "location": "统一测试场景",
                        "time_window": "傍晚",
                        "weather": "微风",
                        "lighting": "柔和侧光",
                        "dominant_palette": ["米白", "灰蓝"],
                        "background_anchors": ["固定背景锚点"],
                        "fixed_props": ["关键道具"],
                        "spatial_layout": "主体位于画面中部，背景结构稳定",
                        "character_blocking": "主要角色从画面中部入镜",
                        "continuity_notes": "保持同一场景的光线和空间关系",
                    },
                    "involved_characters": focus_characters,
                    "covered_event_ids": chapter_event_ids or [f"ch{chapter_number:02d}-ev01"],
                }
            )
        return ChapterSceneStructureSchema.model_validate({"scenes": scenes})

    def _build_chapter_event_plan(self, request: PromptRequest):
        chapter_number = int(request.metadata.get("chapter_number", 1) or 1)
        chapter_text = self._chapter_full_text(request.user_prompt)
        sentences = [
            item.strip()
            for item in re.split(r"[。！？!?]+", chapter_text)
            if item.strip()
        ]
        if not sentences:
            sentences = [f"第{chapter_number}章的核心事件"]
        selected = []
        for candidate in (sentences[0], sentences[min(len(sentences) - 1, 1)], sentences[-1]):
            if candidate not in selected:
                selected.append(candidate)
        events = [
            {
                "event_id": f"ch{chapter_number:02d}-ev{index:02d}",
                "summary": sentence[:48],
                "source_evidence": [sentence[:24] or sentence],
                "involved_characters": self._allowed_names(request.user_prompt)[:2],
            }
            for index, sentence in enumerate(selected, start=1)
        ]
        return ChapterCoveragePlanSchema.model_validate(
            {
                "chapter_number": chapter_number,
                "events": events,
            }
        )

    def _build_scene_segment_contracts(self, request: PromptRequest):
        scene_id = str(request.metadata.get("scene_id", "")).strip() or "ch01-sc01"
        chapter_number = int(request.metadata.get("chapter_number", 1) or 1)
        allowed_names = self._allowed_names(request.user_prompt)
        focus_characters = allowed_names[:2] or ["主角"]
        first_character = focus_characters[0]
        summary = f"{scene_id} 的核心事件。"
        return SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "segments": [
                    {
                        "segment_id": f"{scene_id}-seg01",
                        "chapter_number": chapter_number,
                        "scene_id": scene_id,
                        "title": f"{scene_id} / 片段 1",
                        "summary": summary,
                        "involved_characters": focus_characters,
                        "narration": summary,
                        "dialogue_lines": [],
                        "subtitle_lines": [summary],
                        "timed_beats": [f"0-6秒：{summary}"],
                        "duration_seconds": 6,
                        "transition_hint": "auto",
                        "shot_state": {
                            "framing": "中景",
                            "camera_motion": "缓慢推进",
                            "blocking": f"{first_character} 位于画面中心",
                            "action_progression": summary,
                            "emotion_progression": "情绪逐步升高",
                            "prop_continuity": "关键道具保持在手中",
                            "screen_direction": "保持向右推进",
                            "end_state_lock": f"{first_character} 在尾部停留一个定格动作",
                        },
                        "continuity_link": {
                            "previous_segment_id": "",
                            "transition_mode": "start",
                            "opening_match": f"{first_character} 已在当前场景开场站定，面向镜头右前方。",
                            "carry_over_elements": [],
                            "allowed_changes": "建立新的场景与动作基线",
                            "transition_reason": "场景起始段",
                        },
                        "motion_plan": {
                            "scene_motion": f"{first_character} 在当前场景母图空间里站定后完成核心动作。",
                            "beat_progression": f"0-6秒持续拍出：{summary}",
                            "camera_path": "缓慢推进",
                            "character_motion": f"{first_character} 位于画面中心并保持向右推进。",
                            "continuity_guard": "保持同一场景母图空间、同一角色身份和同一运动方向。",
                        },
                    }
                ],
            }
        )

    def _build_scene_chunk_plan(self, request: PromptRequest):
        scene_id = str(request.metadata.get("scene_id", "")).strip() or "ch01-sc01"
        chapter_number = int(request.metadata.get("chapter_number", 1) or 1)
        return SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "chunks": [
                    {
                        "chunk_id": f"{scene_id}-chunk01",
                        "order_index": 1,
                        "title": f"{scene_id} / 分块 1",
                        "summary": f"{scene_id} 的连续推进。",
                        "must_cover": [f"{scene_id} 的核心动作"],
                        "transition_goal": "推进到当前 scene 的下一状态。",
                        "expected_segment_count": 1,
                    }
                ],
            }
        )

    def _build_segment_plan(self, request: PromptRequest):
        story_title = self._novel_title(request.user_prompt)
        allowed_names = self._allowed_names(request.user_prompt)
        chapter_directives = self._chapter_directives(request.user_prompt)
        focus_characters = allowed_names[:2] or ["主角"]
        scenes: list[dict[str, object]] = []
        for chapter_number, chapter_title, chapter_summary in chapter_directives:
            scene_id = f"ch{chapter_number:02d}-sc01"
            scene_title = f"{chapter_title} / 场景 1"
            segment_id = f"{scene_id}-seg01"
            summary = chapter_summary or f"{chapter_title} 的核心事件。"
            first_character = focus_characters[0]
            scenes.append(
                {
                    "scene_id": scene_id,
                    "chapter_number": chapter_number,
                    "title": scene_title,
                    "summary": summary,
                    "scene_anchor": f"{story_title} 第 {chapter_number} 章的连续性场景基线",
                    "scene_bible": {
                        "location": "统一测试场景",
                        "time_window": "傍晚",
                        "weather": "微风",
                        "lighting": "柔和侧光",
                        "dominant_palette": ["米白", "灰蓝"],
                        "background_anchors": ["固定背景锚点"],
                        "fixed_props": ["关键道具"],
                        "spatial_layout": "主体位于画面中部，背景结构稳定",
                        "character_blocking": "主要角色从画面中部入镜",
                        "continuity_notes": "保持同一场景的光线和空间关系",
                    },
                    "involved_characters": focus_characters,
                    "segments": [
                        {
                            "segment_id": segment_id,
                            "chapter_number": chapter_number,
                            "scene_id": scene_id,
                            "scene_title": scene_title,
                            "scene_summary": summary,
                            "scene_anchor": f"{story_title} 第 {chapter_number} 章的连续性场景基线",
                            "scene_bible": {},
                            "shot_state": {
                                "framing": "中景",
                                "camera_motion": "缓慢推进",
                                "blocking": f"{first_character} 位于画面中心",
                                "action_progression": summary,
                                "emotion_progression": "情绪逐步升高",
                                "prop_continuity": "关键道具保持在手中",
                                "screen_direction": "保持向右推进",
                                "end_state_lock": f"{first_character} 在尾部停留一个定格动作",
                            },
                            "continuity_link": {
                                "previous_segment_id": "",
                                "transition_mode": "start",
                                "opening_match": f"{first_character} 已在当前场景开场站定，面向镜头右前方。",
                                "carry_over_elements": [],
                                "allowed_changes": "建立新的场景与动作基线",
                                "transition_reason": "场景起始段",
                            },
                            "title": f"{scene_title} / 片段 1",
                            "summary": summary,
                            "involved_characters": focus_characters,
                            "narration": summary,
                            "dialogue_lines": [],
                            "subtitle_lines": [summary],
                            "sound_effects": ["环境底噪"],
                            "music_direction": "轻度氛围音乐",
                            "timed_beats": [f"0-6秒：{summary}"],
                            "duration_seconds": 6,
                            "transition_hint": "auto",
                            "motion_plan": {
                                "scene_motion": f"{first_character} 在统一测试场景中开场入镜并完成核心事件。",
                                "beat_progression": f"0-6秒持续拍出：{summary}",
                                "camera_path": "缓慢推进",
                                "character_motion": f"{first_character} 位于画面中心，主要角色保持向右推进。",
                                "continuity_guard": "保持同一场景母图空间、同一角色身份和同一运动方向。",
                            },
                        }
                    ],
                }
            )
        return VideoSegmentPlanSchema.model_validate({"scenes": scenes})

    def _chapter_event_ids(self, user_prompt: str) -> list[str]:
        return [
            match.group("event_id").strip()
            for match in _CHAPTER_EVENT_ID_PATTERN.finditer(user_prompt)
        ]

    def _chapter_full_text(self, user_prompt: str) -> str:
        marker = "当前章节正文全文："
        if marker not in user_prompt:
            return ""
        return user_prompt.split(marker, 1)[1].strip()

    def _build_segment_repair(self, request: PromptRequest):
        segment_id_match = re.search(r'"segment_id":\s*"([^"]+)"', request.user_prompt)
        segment_id = segment_id_match.group(1) if segment_id_match else "segment"
        return SegmentContinuityRepairSchema(
            segment_id=segment_id,
            repair_summary="deterministic repair",
            summary="修复后的片段摘要",
            involved_characters=[],
            narration="修复后的旁白",
            dialogue_lines=[],
            subtitle_lines=["修复后的旁白"],
            timed_beats=["0-6秒：修复后的旁白"],
            duration_seconds=6,
            transition_hint="auto",
            motion_plan={
                "scene_motion": "角色在当前场景母图空间里完成修复后的动作推进。",
                "beat_progression": "0-6秒持续拍出修复后的旁白对应动作。",
                "camera_path": "稳定镜头轻微推进。",
                "character_motion": "角色动作连续，不跳切到未建立状态。",
                "continuity_guard": "保持同一场景、同一角色身份和同一运动方向。",
            },
        )

    def _build_scene_repair(self, request: PromptRequest):
        scene_id_match = re.search(r'"scene_id":\s*"([^"]+)"', request.user_prompt)
        scene_id = scene_id_match.group(1) if scene_id_match else "scene"
        return SceneContinuityRepairSchema(
            scene_id=scene_id,
            repair_summary="deterministic scene repair",
            scene_anchor="修复后的场景锚点，覆盖入口到内部步道的连续空间",
            scene_bible={
                "location": "玫瑰园入口连接内部步道的连续空间",
                "time_window": "傍晚",
                "weather": "晴朗微风",
                "lighting": "暖金色夕阳侧光",
                "dominant_palette": ["暖金", "花叶绿"],
                "background_anchors": ["入口拱门", "玫瑰花墙", "向内延伸的石板步道"],
                "fixed_props": ["路灯", "长椅"],
                "spatial_layout": "镜头可从入口沿步道向园内推进，保持纵深透视和前后景层次",
                "character_blocking": "角色沿同一条步道从入口向内部移动，不突然跳轴",
                "continuity_notes": "同一 scene 内保持入口到园内步道的空间连续，不回退成孤立入口角落",
            },
        )

    def _allowed_names(self, user_prompt: str) -> list[str]:
        match = _ALLOWED_NAMES_PATTERN.search(user_prompt)
        if match is None:
            return []
        return _split_items(match.group("value"))

    def _novel_title(self, user_prompt: str) -> str:
        match = _NOVEL_TITLE_PATTERN.search(user_prompt)
        if match is None:
            return "测试视频项目"
        return match.group("value").strip()

    def _chapter_directives(self, user_prompt: str) -> list[tuple[int, str, str]]:
        directives: list[tuple[int, str, str]] = []
        matches = list(_CHAPTER_DIRECTIVE_PATTERN.finditer(user_prompt))
        if not matches:
            return [(1, "第 1 章", "当前章节的核心事件。")]
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(user_prompt)
            block = user_prompt[start:end]
            summary_match = _CHAPTER_SUMMARY_PATTERN.search(block)
            directives.append(
                (
                    int(match.group("number")),
                    match.group("title").strip(),
                    summary_match.group("value").strip() if summary_match is not None else "",
                )
            )
        return directives

    def _extract_character_field(
        self,
        user_prompt: str,
        character_name: str,
        field_label: str,
    ) -> str:
        pattern = re.compile(
            rf"-\s*角色名：{re.escape(character_name)}\n(?:.*\n)*?\s*{re.escape(field_label)}：(?P<value>[^\n]+)",
            re.S,
        )
        match = pattern.search(user_prompt)
        if match is None:
            return ""
        return match.group("value").strip()
