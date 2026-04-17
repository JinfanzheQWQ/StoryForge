from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field, model_validator


class CharacterVisualProfileSchema(BaseModel):
    name: str = Field(description="角色名")
    role: str = Field(description="角色职责")
    gender: str = Field(default="未指定", description="角色性别，必须从小说角色卡继承")
    appearance: str = Field(description="外观描述")
    outfit: str = Field(description="服装设定")
    color_palette: list[str] = Field(description="主色板")
    portrait_prompt: str = Field(description="角色图生成 prompt")


class CharacterVisualBibleSchema(BaseModel):
    characters: list[CharacterVisualProfileSchema] = Field(description="角色视觉圣经")


class SceneBibleSchema(BaseModel):
    location: str = Field(default="", description="场景地点与空间主体")
    time_window: str = Field(default="", description="时间信息，例如傍晚 / 雨夜 / 深夜 / 次日清晨")
    weather: str = Field(default="", description="天气或空气状态")
    lighting: str = Field(default="", description="主光线和整体照明状态")
    dominant_palette: list[str] = Field(default_factory=list, description="主色调")
    background_anchors: list[str] = Field(
        default_factory=list,
        description="必须在同一场景多段视频里稳定出现的背景锚点",
    )
    fixed_props: list[str] = Field(
        default_factory=list,
        description="场景中持续存在的重要道具或布景元素",
    )
    spatial_layout: str = Field(default="", description="场景空间关系与镜头可用方向")
    character_blocking: str = Field(default="", description="角色基础站位、出入口和运动区域")
    continuity_notes: str = Field(default="", description="这个场景跨片段保持一致时必须遵守的说明")


class ShotStateSchema(BaseModel):
    framing: str = Field(default="", description="该片段核心景别、构图与主体组织方式")
    camera_motion: str = Field(default="", description="镜头运动方式、推进节奏与运动方向")
    blocking: str = Field(default="", description="角色站位、朝向、入画出画和相对关系")
    action_progression: str = Field(default="", description="从开场到收束的主要动作推进")
    emotion_progression: str = Field(default="", description="该片段内部的情绪推进")
    prop_continuity: str = Field(default="", description="手部状态、持物、服装和关键道具的连续性要求")
    screen_direction: str = Field(default="", description="角色运动方向、视线方向与反轴控制要求")
    end_state_lock: str = Field(default="", description="片段尾部应保持的定格状态，供下一段承接")


class ContinuityLinkSchema(BaseModel):
    previous_segment_id: str = Field(default="", description="当前片段承接的上一片段 ID；首段可为空")
    transition_mode: str = Field(
        default="start",
        description="与上一片段的连续关系，可取 start / continue / cut",
    )
    opening_match: str = Field(default="", description="当前片段开场必须与上一片段尾部对齐的状态")
    carry_over_elements: list[str] = Field(
        default_factory=list,
        description="需要从上一片段延续到当前片段开场的角色、道具、背景或方向元素",
    )
    allowed_changes: str = Field(default="", description="承接后本片段允许发生的变化")
    transition_reason: str = Field(default="", description="为什么是承接、切断或新起一段")


class VideoSegmentSchema(BaseModel):
    segment_id: str = Field(description="片段 ID")
    chapter_number: int = Field(description="所属章节")
    scene_id: str = Field(default="", description="所属场景 ID")
    scene_title: str = Field(default="", description="所属场景标题")
    scene_summary: str = Field(default="", description="所属场景摘要")
    scene_anchor: str = Field(default="", description="所属场景连续性锚点")
    scene_bible: SceneBibleSchema = Field(
        default_factory=SceneBibleSchema,
        description="该片段继承的场景圣经，用于锁定时空、光线、背景锚点和空间关系",
    )
    shot_state: ShotStateSchema = Field(
        default_factory=ShotStateSchema,
        description="该片段镜头与动作状态约束，用于锁定景别、调度、动作推进与尾部承接状态",
    )
    continuity_link: ContinuityLinkSchema = Field(
        default_factory=ContinuityLinkSchema,
        description="该片段与上一片段的显式连续性承接关系",
    )
    title: str = Field(description="片段标题")
    summary: str = Field(description="片段摘要")
    involved_characters: list[str] = Field(description="涉及角色")
    start_frame_characters: list[str] = Field(
        default_factory=list,
        description="首帧实际出镜角色，只包含这一帧真正入镜的人物",
    )
    mid_frame_characters: list[str] = Field(
        default_factory=list,
        description="中段锚点帧实际出镜角色；若无需中段帧可留空",
    )
    end_frame_characters: list[str] = Field(
        default_factory=list,
        description="尾帧实际出镜角色，只包含这一帧真正入镜的人物",
    )
    narration: str = Field(description="视频自带音频的旁白内容")
    dialogue_lines: list[str] = Field(
        default_factory=list,
        description="适合直接驱动视频模型音频的角色对白列表",
    )
    subtitle_lines: list[str] = Field(
        default_factory=list,
        description="硬字幕文本列表",
    )
    character_voice_notes: list[str] = Field(
        default_factory=list,
        description="角色音色与说话方式锁定说明",
    )
    sound_effects: list[str] = Field(
        default_factory=list,
        description="环境音与拟音列表",
    )
    music_direction: str = Field(default="", description="背景音乐方向")
    timed_beats: list[str] = Field(
        default_factory=list,
        description="按时间组织的镜头、对白和音效节拍",
    )
    scene_prompt: str = Field(description="生图总 prompt")
    start_frame_prompt: str = Field(description="首帧 prompt")
    mid_frame_prompt: str = Field(
        default="",
        description="中段锚点帧 prompt；当片段较长、多人同框或镜头运动明显时用于约束中段状态",
    )
    end_frame_prompt: str = Field(description="尾帧 prompt")
    duration_seconds: int = Field(description="建议时长")
    requires_mid_frame: bool = Field(
        default=False,
        description="是否需要额外生成中段锚点帧",
    )
    transition_hint: str = Field(
        default="auto",
        description="与上一片段的转场关系，可取 continue / cut / auto",
    )
    source_segment_id: str = Field(default="", description="拆分前的原始片段 ID")
    subsegment_index: int = Field(default=1, description="当前子片段序号")
    subsegment_count: int = Field(default=1, description="当前原始片段拆出的总子片段数")
    reuse_previous_end_frame: bool = Field(
        default=False,
        description="是否直接沿用上一子片段的尾帧作为当前片段首帧",
    )


class SegmentContinuityRepairSchema(BaseModel):
    segment_id: str = Field(description="需要被修复的目标片段 ID，必须与输入目标一致")
    repair_summary: str = Field(
        default="",
        description="一句话说明本次修复打算解决什么连续性问题",
    )
    scene_prompt: str = Field(description="修复后的片段场景总提示词")
    start_frame_prompt: str = Field(description="修复后的首帧 prompt")
    mid_frame_prompt: str = Field(
        default="",
        description="修复后的中段锚点帧 prompt；若不需要中段帧则置空",
    )
    end_frame_prompt: str = Field(description="修复后的尾帧 prompt")
    start_frame_characters: list[str] = Field(
        default_factory=list,
        description="修复后的首帧实际出镜角色",
    )
    mid_frame_characters: list[str] = Field(
        default_factory=list,
        description="修复后的中段帧实际出镜角色",
    )
    end_frame_characters: list[str] = Field(
        default_factory=list,
        description="修复后的尾帧实际出镜角色",
    )
    narration: str = Field(default="", description="修复后的旁白")
    dialogue_lines: list[str] = Field(default_factory=list, description="修复后的对白")
    subtitle_lines: list[str] = Field(default_factory=list, description="修复后的硬字幕")
    timed_beats: list[str] = Field(default_factory=list, description="修复后的时间节拍")
    duration_seconds: int = Field(ge=5, le=12, description="修复后的时长，必须在 5-12 秒内")
    requires_mid_frame: bool = Field(default=False, description="是否保留中段锚点帧")
    transition_hint: str = Field(default="auto", description="修复后的转场提示")
    shot_state: ShotStateSchema = Field(
        default_factory=ShotStateSchema,
        description="修复后的镜头状态",
    )
    continuity_link: ContinuityLinkSchema = Field(
        default_factory=ContinuityLinkSchema,
        description="修复后的跨段连续性约束",
    )

    @model_validator(mode="after")
    def normalize_mid_frame_fields(self) -> "SegmentContinuityRepairSchema":
        if not self.requires_mid_frame:
            self.mid_frame_prompt = ""
            self.mid_frame_characters = []
        return self


class VideoSceneSchema(BaseModel):
    scene_id: str = Field(description="场景 ID")
    chapter_number: int = Field(description="所属章节")
    title: str = Field(description="场景标题")
    summary: str = Field(description="场景摘要")
    scene_anchor: str = Field(
        default="",
        description="场景连续性锚点，例如地点、时间、光线、固定道具或空间关系",
    )
    scene_bible: SceneBibleSchema = Field(
        default_factory=SceneBibleSchema,
        description="场景级圣经，用于约束同一 scene 下多个片段的视觉与空间连续性",
    )
    scene_master_frame_prompt: str = Field(
        default="",
        description="场景母图 prompt，用于先生成同一 scene 的环境与空间基准图",
    )
    scene_master_frame_path: str = Field(
        default="",
        description="场景母图输出路径",
    )
    scene_master_frame_url: str = Field(
        default="",
        description="场景母图远程 URL",
    )
    scene_master_frame_status: str = Field(
        default="planned",
        description="场景母图生成状态",
    )
    scene_master_frame_error: str = Field(
        default="",
        description="场景母图生成失败原因",
    )
    involved_characters: list[str] = Field(
        default_factory=list,
        description="该场景整体涉及的角色集合",
    )
    segments: list[VideoSegmentSchema] = Field(description="该场景下的片段列表")


class VideoSegmentPlanSchema(BaseModel):
    scenes: list[VideoSceneSchema] = Field(description="完整场景与片段规划")

    @model_validator(mode="before")
    @classmethod
    def normalize_input_payload(cls, raw):
        if isinstance(raw, list):
            return {"scenes": _build_scenes_from_flat_segments(raw)}
        if isinstance(raw, dict):
            if isinstance(raw.get("scenes"), list):
                return {"scenes": _normalize_raw_scenes(raw.get("scenes", []))}
            if isinstance(raw.get("segments"), list):
                return {"scenes": _build_scenes_from_flat_segments(raw.get("segments", []))}
        return raw

    @property
    def segments(self) -> list[VideoSegmentSchema]:
        flattened: list[VideoSegmentSchema] = []
        for scene in self.scenes:
            flattened.extend(scene.segments)
        return flattened


def _normalize_raw_scenes(raw_scenes: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        scene_payload = _coerce_mapping(raw_scene)
        if scene_payload is None:
            continue
        segments = scene_payload.get("segments", [])
        if not isinstance(segments, list):
            segments = []

        chapter_number = int(scene_payload.get("chapter_number") or _first_segment_chapter_number(segments))
        scene_id = str(scene_payload.get("scene_id") or "").strip()
        if not scene_id:
            if chapter_number > 0:
                scene_id = f"ch{chapter_number:02d}-sc{index:02d}"
            else:
                scene_id = f"scene-{index:02d}"
        title = str(
            scene_payload.get("title")
            or scene_payload.get("scene_title")
            or f"场景 {index}"
        ).strip() or f"场景 {index}"
        summary = str(
            scene_payload.get("summary")
            or scene_payload.get("scene_summary")
            or title
        ).strip() or title
        scene_anchor = str(scene_payload.get("scene_anchor") or "").strip()
        scene_bible = _normalize_scene_bible(
            scene_payload.get("scene_bible"),
            default_summary=summary,
            scene_anchor_default=scene_anchor,
        )
        involved_characters = _normalize_name_list(scene_payload.get("involved_characters", []))
        scene_master_frame_prompt = str(scene_payload.get("scene_master_frame_prompt") or "").strip()
        scene_master_frame_path = str(scene_payload.get("scene_master_frame_path") or "").strip()
        scene_master_frame_url = str(scene_payload.get("scene_master_frame_url") or "").strip()
        scene_master_frame_status = str(
            scene_payload.get("scene_master_frame_status") or "planned"
        ).strip() or "planned"
        scene_master_frame_error = str(scene_payload.get("scene_master_frame_error") or "").strip()

        normalized_segments: list[dict[str, object]] = []
        for segment_index, raw_segment in enumerate(segments, start=1):
            payload = _coerce_mapping(raw_segment)
            if payload is None:
                continue
            payload.setdefault("chapter_number", chapter_number)
            payload.setdefault("scene_id", scene_id)
            payload.setdefault("scene_title", title)
            payload.setdefault("scene_summary", summary)
            payload.setdefault("scene_anchor", scene_anchor)
            payload.setdefault("scene_bible", dict(scene_bible))
            payload["shot_state"] = _normalize_shot_state(
                payload.get("shot_state"),
                default_summary=str(payload.get("summary") or summary),
                default_prompt=str(payload.get("scene_prompt") or ""),
                scene_anchor_default=scene_anchor,
            )
            payload["continuity_link"] = _normalize_continuity_link(
                payload.get("continuity_link"),
            )
            payload.setdefault("segment_id", f"{scene_id}-seg{segment_index:02d}")
            payload.setdefault("title", f"{title} / 片段 {segment_index}")
            payload.setdefault("summary", summary)
            normalized_segments.append(payload)

        if not involved_characters:
            involved_characters = _collect_scene_characters(normalized_segments)

        normalized.append(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "title": title,
                "summary": summary,
                "scene_anchor": scene_anchor,
                "scene_bible": scene_bible,
                "scene_master_frame_prompt": scene_master_frame_prompt,
                "scene_master_frame_path": scene_master_frame_path,
                "scene_master_frame_url": scene_master_frame_url,
                "scene_master_frame_status": scene_master_frame_status,
                "scene_master_frame_error": scene_master_frame_error,
                "involved_characters": involved_characters,
                "segments": normalized_segments,
            }
        )
    return normalized


def _build_scenes_from_flat_segments(raw_segments: list[object]) -> list[dict[str, object]]:
    grouped: dict[tuple[int, str], dict[str, object]] = {}
    chapter_counters: defaultdict[int, int] = defaultdict(int)

    for index, raw_segment in enumerate(raw_segments, start=1):
        payload = _coerce_mapping(raw_segment)
        if payload is None:
            continue
        chapter_number = int(payload.get("chapter_number") or 0)
        scene_id = str(payload.get("scene_id") or "").strip()
        if not scene_id:
            chapter_counters[chapter_number] += 1
            if chapter_number > 0:
                scene_id = f"ch{chapter_number:02d}-sc{chapter_counters[chapter_number]:02d}"
            else:
                scene_id = f"scene-{index:02d}"
        else:
            chapter_counters[chapter_number] += 0

        scene_title = str(payload.get("scene_title") or payload.get("title") or f"场景 {index}").strip()
        scene_summary = str(payload.get("scene_summary") or payload.get("summary") or scene_title).strip()
        scene_anchor = str(payload.get("scene_anchor") or "").strip()
        scene_bible = _normalize_scene_bible(
            payload.get("scene_bible"),
            default_summary=scene_summary,
            scene_anchor_default=scene_anchor,
        )
        shot_state = _normalize_shot_state(
            payload.get("shot_state"),
            default_summary=scene_summary,
            default_prompt=str(payload.get("scene_prompt") or ""),
            scene_anchor_default=scene_anchor,
        )
        payload["scene_id"] = scene_id
        payload["scene_title"] = scene_title
        payload["scene_summary"] = scene_summary
        payload["scene_anchor"] = scene_anchor
        payload["scene_bible"] = dict(scene_bible)
        payload["shot_state"] = dict(shot_state)
        payload["continuity_link"] = dict(
            _normalize_continuity_link(payload.get("continuity_link"))
        )

        group_key = (chapter_number, scene_id)
        group = grouped.setdefault(
            group_key,
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "title": scene_title or f"场景 {index}",
                "summary": scene_summary or scene_title or f"场景 {index}",
                "scene_anchor": scene_anchor,
                "scene_bible": scene_bible,
                "scene_master_frame_prompt": str(payload.get("scene_master_frame_prompt") or "").strip(),
                "scene_master_frame_path": str(payload.get("scene_master_frame_path") or "").strip(),
                "scene_master_frame_url": str(payload.get("scene_master_frame_url") or "").strip(),
                "scene_master_frame_status": str(
                    payload.get("scene_master_frame_status") or "planned"
                ).strip() or "planned",
                "scene_master_frame_error": str(payload.get("scene_master_frame_error") or "").strip(),
                "involved_characters": [],
                "segments": [],
            },
        )
        if _scene_bible_has_signal(scene_bible) and not _scene_bible_has_signal(group.get("scene_bible", {})):
            group["scene_bible"] = scene_bible
        for key in (
            "scene_master_frame_prompt",
            "scene_master_frame_path",
            "scene_master_frame_url",
            "scene_master_frame_status",
            "scene_master_frame_error",
        ):
            current_value = str(group.get(key, "") or "").strip()
            incoming_value = str(payload.get(key, "") or "").strip()
            if incoming_value and not current_value:
                group[key] = incoming_value
        group["segments"].append(payload)

    normalized = list(grouped.values())
    for scene in normalized:
        scene["involved_characters"] = _collect_scene_characters(scene.get("segments", []))
    return normalized


def _collect_scene_characters(raw_segments: list[object]) -> list[str]:
    names: list[str] = []
    for raw_segment in raw_segments:
        payload = _coerce_mapping(raw_segment)
        if payload is None:
            continue
        for name in _normalize_name_list(payload.get("involved_characters", [])):
            if name not in names:
                names.append(name)
    return names


def _normalize_name_list(raw_names: object) -> list[str]:
    if not isinstance(raw_names, list):
        return []
    normalized: list[str] = []
    for item in raw_names:
        name = str(item).strip()
        if name and name not in normalized:
            normalized.append(name)
    return normalized


def _first_segment_chapter_number(raw_segments: list[object]) -> int:
    for raw_segment in raw_segments:
        payload = _coerce_mapping(raw_segment)
        if payload is not None:
            return int(payload.get("chapter_number") or 0)
    return 0


def _coerce_mapping(raw: object) -> dict[str, object] | None:
    if isinstance(raw, dict):
        return dict(raw)
    if hasattr(raw, "model_dump"):
        return dict(raw.model_dump())
    return None


def _normalize_scene_bible(
    raw_scene_bible: object,
    *,
    default_summary: str,
    scene_anchor_default: str,
) -> dict[str, object]:
    payload = _coerce_mapping(raw_scene_bible) or {}
    normalized = SceneBibleSchema.model_validate(payload).model_dump()
    if not _scene_bible_has_signal(normalized):
        normalized["continuity_notes"] = (
            f"保持 {default_summary or '当前场景'} 的空间、光线和氛围连续性。"
        )
        if scene_anchor_default:
            normalized["spatial_layout"] = scene_anchor_default
    return normalized


def _normalize_shot_state(
    raw_shot_state: object,
    *,
    default_summary: str,
    default_prompt: str,
    scene_anchor_default: str,
) -> dict[str, object]:
    payload = _coerce_mapping(raw_shot_state) or {}
    normalized = ShotStateSchema.model_validate(payload).model_dump()
    if not _shot_state_has_signal(normalized):
        normalized["framing"] = "以中景或可交代空间关系的镜头建立主体与环境关系。"
        normalized["camera_motion"] = "镜头按当前片段节奏自然推进，除非明确转场，不要突然反向跳轴。"
        normalized["blocking"] = (
            scene_anchor_default
            or "保持当前片段角色站位、朝向、进出场路径和相对位置稳定。"
        )
        normalized["action_progression"] = default_summary or default_prompt or "保持当前片段的核心动作推进。"
        normalized["emotion_progression"] = default_summary or "情绪沿当前片段自然推进。"
        normalized["prop_continuity"] = "保持服装、持物、手部状态和关键道具连续，不要凭空增删。"
        normalized["screen_direction"] = "保持角色运动方向与视线方向一致，避免突然反轴。"
        normalized["end_state_lock"] = default_summary or default_prompt or "保持片段尾部动作与姿态，便于下一段承接。"
    return normalized


def _normalize_continuity_link(raw_continuity_link: object) -> dict[str, object]:
    payload = _coerce_mapping(raw_continuity_link) or {}
    normalized = ContinuityLinkSchema.model_validate(payload).model_dump()
    normalized["transition_mode"] = _normalize_transition_mode(
        normalized.get("transition_mode", "start")
    )
    return normalized


def _scene_bible_has_signal(raw_scene_bible: object) -> bool:
    payload = _coerce_mapping(raw_scene_bible)
    if payload is None:
        return False
    for key, value in payload.items():
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def _shot_state_has_signal(raw_shot_state: object) -> bool:
    payload = _coerce_mapping(raw_shot_state)
    if payload is None:
        return False
    for key, value in payload.items():
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def _normalize_transition_mode(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if value in {"start", "continue", "cut"}:
        return value
    return "start"
