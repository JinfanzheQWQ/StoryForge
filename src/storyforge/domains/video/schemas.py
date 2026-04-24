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


class MotionPlanSchema(BaseModel):
    start_to_mid: str = Field(
        default="",
        description="从首帧图片推进到中段帧图片的具体画面运动；无中段帧时表示首帧到尾帧的推进",
    )
    mid_to_end: str = Field(
        default="",
        description="从中段帧图片推进到尾帧图片的具体画面运动；无中段帧时可留空",
    )
    camera_path: str = Field(default="", description="镜头路径，例如固定机位、轻微前推、跟拍、切入再切回")
    character_motion: str = Field(default="", description="角色入画、靠近、转身、停步、离场或站位变化")
    continuity_guard: str = Field(default="", description="防止硬跳、换景、少人、换脸或构图突变的连续性要求")


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


class SceneTransitionContractSchema(BaseModel):
    previous_scene_id: str = Field(default="", description="上一个 scene 的 ID；首个 scene 留空")
    transition_mode: str = Field(
        default="",
        description="scene 间过渡方式，可取 direct_continue / adjacent_move / motivated_cut / hard_cut",
    )
    previous_scene_exit_state: str = Field(
        default="",
        description="上一场尾部可拍到的退出状态",
    )
    next_scene_entry_match: str = Field(
        default="",
        description="当前场第一段开头必须先建立的开场状态",
    )
    bridge_action: str = Field(
        default="",
        description="上一场尾部过渡到当前场开头的连接动作或连接结果",
    )
    carry_over_elements: list[str] = Field(
        default_factory=list,
        description="需要跨 scene 保持的角色、道具、方向或关系元素",
    )
    screen_direction_policy: str = Field(
        default="",
        description="跨 scene 的朝向、轴线或运动方向承接要求",
    )
    visual_bridge: str = Field(
        default="",
        description="当前 scene 新环境如何被 reveal",
    )
    audio_bridge: str = Field(
        default="none",
        description="声音桥接方式，可取 none / j_cut / l_cut / ambient_bridge",
    )
    transition_focus_seconds: int = Field(
        default=0,
        ge=0,
        le=3,
        description="建议在当前 scene 首段前几秒完成过渡建立，通常 0-3 秒",
    )


class ChapterCoverageEventSchema(BaseModel):
    event_id: str = Field(description="章节关键事件 ID，例如 ch01-ev01")
    summary: str = Field(description="必须被后续 scene 覆盖的关键事件摘要")
    source_evidence: list[str] = Field(
        default_factory=list,
        description="直接摘自当前章节正文的短词或短句，用于验证该事件确实存在",
    )
    involved_characters: list[str] = Field(
        default_factory=list,
        description="该事件直接涉及的角色集合",
    )


class ChapterCoveragePlanSchema(BaseModel):
    chapter_number: int = Field(default=0, description="所属章节")
    events: list[ChapterCoverageEventSchema] = Field(description="当前章节必须覆盖的关键事件列表")


class ChapterCoverageEventSplitItemSchema(BaseModel):
    summary: str = Field(description="用于替换单个粗事件的更细事件摘要")
    source_evidence: list[str] = Field(
        default_factory=list,
        description="直接摘自当前章节正文的短词或短句，用于验证该替换事件确实存在",
    )
    involved_characters: list[str] = Field(
        default_factory=list,
        description="该替换事件直接涉及的角色集合",
    )


class ChapterCoverageEventSplitPlanSchema(BaseModel):
    events: list[ChapterCoverageEventSplitItemSchema] = Field(
        description="用于替换单个过粗关键事件的更细事件列表",
    )


class ChapterSceneSchema(BaseModel):
    scene_id: str = Field(description="场景 ID")
    chapter_number: int = Field(description="所属章节")
    title: str = Field(description="场景标题")
    summary: str = Field(description="场景摘要")
    scene_anchor: str = Field(
        default="",
        description="场景连续性锚点，例如地点、时间、光线、固定背景物或空间关系",
    )
    involved_characters: list[str] = Field(
        default_factory=list,
        description="该场景整体涉及的角色集合",
    )
    covered_event_ids: list[str] = Field(
        default_factory=list,
        description="该 scene 覆盖的章节关键事件 ID，必须按正文顺序对应连续事件块",
    )
    covered_event_summaries: list[str] = Field(
        default_factory=list,
        description="该 scene 绑定的章节关键事件摘要，仅用于后续 chunk/segment 规划约束边界",
    )
    scene_bible: SceneBibleSchema = Field(
        default_factory=SceneBibleSchema,
        description="该场景共享的轻量场景圣经",
    )
    scene_transition_contract: SceneTransitionContractSchema = Field(
        default_factory=SceneTransitionContractSchema,
        description="当前 scene 相对上一 scene 的过渡合同；首个 scene 可为空",
    )
    @model_validator(mode="after")
    def normalize_transition_contract_entry(self) -> "ChapterSceneSchema":
        self.scene_transition_contract = SceneTransitionContractSchema.model_validate(
            _normalize_scene_transition_contract_for_scene(
                self.scene_transition_contract,
                title=self.title,
                summary=self.summary,
                scene_anchor=self.scene_anchor,
                scene_bible=self.scene_bible,
                involved_characters=self.involved_characters,
            )
        )
        return self


class ChapterSceneStructureSchema(BaseModel):
    scenes: list[ChapterSceneSchema] = Field(description="当前章节的场景结构")

    @model_validator(mode="before")
    @classmethod
    def normalize_input_payload(cls, raw):
        if isinstance(raw, list):
            return {"scenes": _normalize_scene_structure_payloads(raw)}
        if isinstance(raw, dict) and isinstance(raw.get("scenes"), list):
            return {"scenes": _normalize_scene_structure_payloads(raw.get("scenes", []))}
        return raw


class SceneSegmentChunkSchema(BaseModel):
    chunk_id: str = Field(description="场景内分块 ID")
    order_index: int = Field(description="分块顺序，从 1 开始")
    title: str = Field(description="分块标题")
    summary: str = Field(description="分块摘要")
    must_cover: list[str] = Field(
        default_factory=list,
        description="本分块必须覆盖的关键动作、对白或情绪点",
    )
    transition_goal: str = Field(default="", description="本分块结束时应推进到的状态")
    expected_segment_count: int = Field(
        default=1,
        ge=1,
        le=4,
        description="该分块预期拆成的 segment 数，通常 1-3",
    )


class SceneSegmentChunkPlanSchema(BaseModel):
    scene_id: str = Field(default="", description="所属场景 ID")
    chapter_number: int = Field(default=0, description="所属章节")
    chunks: list[SceneSegmentChunkSchema] = Field(description="当前场景的分块大纲")

    @model_validator(mode="before")
    @classmethod
    def normalize_input_payload(cls, raw):
        if isinstance(raw, list):
            return {"chunks": _normalize_scene_segment_chunks(raw)}
        if isinstance(raw, dict) and isinstance(raw.get("chunks"), list):
            payload = dict(raw)
            payload["chunks"] = _normalize_scene_segment_chunks(raw.get("chunks", []))
            return payload
        return raw


class SceneSegmentContractSchema(BaseModel):
    segment_id: str = Field(description="片段 ID")
    chapter_number: int = Field(description="所属章节")
    scene_id: str = Field(description="所属场景 ID")
    title: str = Field(description="片段标题")
    summary: str = Field(description="片段摘要")
    involved_characters: list[str] = Field(description="涉及角色")
    start_frame_characters: list[str] = Field(default_factory=list, description="首帧实际出镜角色")
    mid_frame_characters: list[str] = Field(default_factory=list, description="中段锚点帧实际出镜角色")
    mid_frame_mode: str = Field(
        default="continuous",
        description="中段锚点的镜头语义，可取 continuous / insert_cut",
    )
    end_frame_characters: list[str] = Field(default_factory=list, description="尾帧实际出镜角色")
    narration: str = Field(default="", description="该片段旁白")
    dialogue_lines: list[str] = Field(default_factory=list, description="该片段对白")
    subtitle_lines: list[str] = Field(default_factory=list, description="该片段硬字幕")
    timed_beats: list[str] = Field(
        min_length=1,
        description="该片段时间节拍，必填，且每条都应包含具体秒数范围",
    )
    duration_seconds: int = Field(description="建议时长")
    requires_mid_frame: bool = Field(default=False, description="是否需要中段锚点帧")
    transition_hint: str = Field(default="auto", description="continue / cut / auto")
    shot_state: ShotStateSchema = Field(
        default_factory=ShotStateSchema,
        description="片段镜头与动作状态",
    )
    continuity_link: ContinuityLinkSchema = Field(
        default_factory=ContinuityLinkSchema,
        description="与上一片段的连续性关系",
    )
    motion_plan: MotionPlanSchema = Field(
        default_factory=MotionPlanSchema,
        description="首帧 / 中段帧 / 尾帧之间的画面推进合同",
    )

    @model_validator(mode="after")
    def normalize_mid_frame_fields(self) -> "SceneSegmentContractSchema":
        self.mid_frame_mode = (
            "insert_cut"
            if str(self.mid_frame_mode or "").strip().lower() == "insert_cut"
            else "continuous"
        )
        if not self.requires_mid_frame:
            self.mid_frame_characters = []
            self.mid_frame_mode = "continuous"
        return self


class SceneSegmentContractBatchSchema(BaseModel):
    scene_id: str = Field(default="", description="所属场景 ID")
    chapter_number: int = Field(default=0, description="所属章节")
    segments: list[SceneSegmentContractSchema] = Field(description="当前场景的片段合同")

    @model_validator(mode="before")
    @classmethod
    def normalize_input_payload(cls, raw):
        if isinstance(raw, list):
            return {"segments": _normalize_scene_segment_contracts(raw)}
        if isinstance(raw, dict) and isinstance(raw.get("segments"), list):
            payload = dict(raw)
            payload["segments"] = _normalize_scene_segment_contracts(raw.get("segments", []))
            return payload
        return raw


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
    motion_plan: MotionPlanSchema = Field(
        default_factory=MotionPlanSchema,
        description="首帧 / 中段帧 / 尾帧之间的画面推进合同，用于生成 Seedance 图片1/2/3 推进提示",
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
    mid_frame_mode: str = Field(
        default="continuous",
        description="中段锚点的镜头语义，可取 continuous / insert_cut",
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

    @model_validator(mode="after")
    def normalize_mid_frame_contract(self) -> "VideoSegmentSchema":
        self.mid_frame_mode = (
            "insert_cut"
            if str(self.mid_frame_mode or "").strip().lower() == "insert_cut"
            else "continuous"
        )
        if not self.requires_mid_frame:
            self.mid_frame_characters = []
            self.mid_frame_prompt = ""
            self.mid_frame_mode = "continuous"
        return self


class SegmentContinuityRepairSchema(BaseModel):
    segment_id: str = Field(description="需要被修复的目标片段 ID，必须与输入目标一致")
    repair_summary: str = Field(
        default="",
        description="一句话说明本次修复打算解决什么连续性问题",
    )
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
    mid_frame_mode: str = Field(
        default="continuous",
        description="修复后的中段锚点镜头语义，可取 continuous / insert_cut",
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
    motion_plan: MotionPlanSchema = Field(
        default_factory=MotionPlanSchema,
        description="修复后的首帧 / 中段帧 / 尾帧画面推进合同",
    )

    @model_validator(mode="after")
    def normalize_mid_frame_fields(self) -> "SegmentContinuityRepairSchema":
        self.mid_frame_mode = (
            "insert_cut"
            if str(self.mid_frame_mode or "").strip().lower() == "insert_cut"
            else "continuous"
        )
        if not self.requires_mid_frame:
            self.mid_frame_prompt = ""
            self.mid_frame_characters = []
            self.mid_frame_mode = "continuous"
        return self


class SceneContinuityRepairSchema(BaseModel):
    scene_id: str = Field(description="需要被修复的目标场景 ID，必须与输入目标一致")
    repair_summary: str = Field(
        default="",
        description="一句话说明本次场景修复打算解决什么连续性问题",
    )
    scene_anchor: str = Field(
        default="",
        description="修复后的场景锚点，应能概括同一 scene 的空间与连续性基准",
    )
    scene_bible: SceneBibleSchema = Field(
        default_factory=SceneBibleSchema,
        description="修复后的场景圣经，用于稳定同一 scene 的环境、空间与镜头基线",
    )


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
    scene_transition_contract: SceneTransitionContractSchema = Field(
        default_factory=SceneTransitionContractSchema,
        description="scene 间过渡合同，用于约束 scene 首段如何承接上一场",
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
    scene_master_request_info: dict[str, object] = Field(
        default_factory=dict,
        description="场景母图实际提交到 Seedream 的请求参数摘要",
    )
    involved_characters: list[str] = Field(
        default_factory=list,
        description="该场景整体涉及的角色集合",
    )
    covered_event_ids: list[str] = Field(
        default_factory=list,
        description="该 scene 覆盖的章节关键事件 ID，用于上游场景结构校验与排查",
    )
    covered_event_summaries: list[str] = Field(
        default_factory=list,
        description="该 scene 绑定的章节关键事件摘要，用于约束后续 chunk/segment 规划不要越界",
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
        scene_transition_contract = _normalize_scene_transition_contract_for_scene(
            scene_payload.get("scene_transition_contract"),
            title=title,
            summary=summary,
            scene_anchor=scene_anchor,
            scene_bible=scene_bible,
            involved_characters=involved_characters,
        )
        scene_master_frame_prompt = str(scene_payload.get("scene_master_frame_prompt") or "").strip()
        scene_master_frame_path = str(scene_payload.get("scene_master_frame_path") or "").strip()
        scene_master_frame_url = str(scene_payload.get("scene_master_frame_url") or "").strip()
        scene_master_frame_status = str(
            scene_payload.get("scene_master_frame_status") or "planned"
        ).strip() or "planned"
        scene_master_frame_error = str(scene_payload.get("scene_master_frame_error") or "").strip()
        scene_master_request_info = dict(scene_payload.get("scene_master_request_info", {}) or {})
        covered_event_ids = _normalize_name_list(scene_payload.get("covered_event_ids", []))
        covered_event_summaries = [
            str(item).strip()
            for item in scene_payload.get("covered_event_summaries", [])
            if str(item).strip()
        ]

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
                scene_anchor_default=scene_anchor,
            )
            payload["shot_state"] = _normalize_shared_shot_state_for_frame_groups(
                payload["shot_state"],
                start_frame_characters=_normalize_name_list(payload.get("start_frame_characters", [])),
                mid_frame_characters=_normalize_name_list(payload.get("mid_frame_characters", [])),
                end_frame_characters=_normalize_name_list(payload.get("end_frame_characters", [])),
                requires_mid_frame=bool(payload.get("requires_mid_frame", False)),
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
                "scene_transition_contract": scene_transition_contract,
                "scene_master_frame_prompt": scene_master_frame_prompt,
                "scene_master_frame_path": scene_master_frame_path,
                "scene_master_frame_url": scene_master_frame_url,
                "scene_master_frame_status": scene_master_frame_status,
                "scene_master_frame_error": scene_master_frame_error,
                "scene_master_request_info": scene_master_request_info,
                "involved_characters": involved_characters,
                "covered_event_ids": covered_event_ids,
                "covered_event_summaries": covered_event_summaries,
                "segments": normalized_segments,
            }
        )
    return normalized


def _normalize_scene_structure_payloads(raw_scenes: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        payload = _coerce_mapping(raw_scene)
        if payload is None:
            continue
        chapter_number = int(payload.get("chapter_number") or 0)
        scene_id = str(payload.get("scene_id") or "").strip()
        if not scene_id:
            if chapter_number > 0:
                scene_id = f"ch{chapter_number:02d}-sc{index:02d}"
            else:
                scene_id = f"scene-{index:02d}"
        title = str(payload.get("title") or payload.get("scene_title") or f"场景 {index}").strip()
        summary = str(payload.get("summary") or payload.get("scene_summary") or title).strip()
        scene_anchor = str(payload.get("scene_anchor") or "").strip()
        involved_characters = _normalize_name_list(payload.get("involved_characters", []))
        scene_bible = _normalize_scene_bible(
            payload.get("scene_bible"),
            default_summary=summary or title or f"场景 {index}",
            scene_anchor_default=scene_anchor,
        )
        normalized.append(
            {
                "scene_id": scene_id,
                "chapter_number": chapter_number,
                "title": title or f"场景 {index}",
                "summary": summary or title or f"场景 {index}",
                "scene_anchor": scene_anchor,
                "involved_characters": involved_characters,
                "covered_event_ids": _normalize_name_list(payload.get("covered_event_ids", [])),
                "covered_event_summaries": [
                    str(item).strip()
                    for item in payload.get("covered_event_summaries", [])
                    if str(item).strip()
                ],
                "scene_bible": scene_bible,
                "scene_transition_contract": _normalize_scene_transition_contract_for_scene(
                    payload.get("scene_transition_contract"),
                    title=title or f"场景 {index}",
                    summary=summary or title or f"场景 {index}",
                    scene_anchor=scene_anchor,
                    scene_bible=scene_bible,
                    involved_characters=involved_characters,
                ),
            }
        )
    return normalized


def _normalize_scene_segment_contracts(raw_segments: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, raw_segment in enumerate(raw_segments, start=1):
        payload = _coerce_mapping(raw_segment)
        if payload is None:
            continue
        timed_beats = [
            str(item).strip()
            for item in payload.get("timed_beats", [])
            if str(item).strip()
        ]
        start_frame_characters = _normalize_name_list(payload.get("start_frame_characters", []))
        mid_frame_characters = _normalize_name_list(payload.get("mid_frame_characters", []))
        end_frame_characters = _normalize_name_list(payload.get("end_frame_characters", []))
        shot_state = _normalize_shot_state(
            payload.get("shot_state"),
            default_summary=str(payload.get("summary") or ""),
            scene_anchor_default="",
        )
        shot_state = _normalize_shared_shot_state_for_frame_groups(
            shot_state,
            start_frame_characters=start_frame_characters,
            mid_frame_characters=mid_frame_characters,
            end_frame_characters=end_frame_characters,
            requires_mid_frame=bool(payload.get("requires_mid_frame", False)),
        )
        normalized_payload = {
            "segment_id": str(payload.get("segment_id") or f"segment-{index:02d}").strip()
            or f"segment-{index:02d}",
            "chapter_number": int(payload.get("chapter_number") or 0),
            "scene_id": str(payload.get("scene_id") or "").strip(),
            "title": str(payload.get("title") or f"片段 {index}").strip() or f"片段 {index}",
            "summary": str(payload.get("summary") or "").strip(),
            "involved_characters": _normalize_name_list(payload.get("involved_characters", [])),
            "start_frame_characters": start_frame_characters,
            "mid_frame_characters": mid_frame_characters,
            "mid_frame_mode": (
                "insert_cut"
                if str(payload.get("mid_frame_mode", "") or "").strip().lower() == "insert_cut"
                else "continuous"
            ),
            "end_frame_characters": end_frame_characters,
            "narration": str(payload.get("narration") or "").strip(),
            "dialogue_lines": [
                str(item).strip()
                for item in payload.get("dialogue_lines", [])
                if str(item).strip()
            ],
            "subtitle_lines": [
                str(item).strip()
                for item in payload.get("subtitle_lines", [])
                if str(item).strip()
            ],
            "timed_beats": timed_beats,
            "duration_seconds": int(payload.get("duration_seconds") or 0),
            "requires_mid_frame": bool(payload.get("requires_mid_frame", False)),
            "transition_hint": str(payload.get("transition_hint") or "auto").strip() or "auto",
            "shot_state": shot_state,
            "continuity_link": _normalize_continuity_link(
                payload.get("continuity_link"),
            ),
            "motion_plan": _normalize_motion_plan(
                payload.get("motion_plan"),
                summary=str(payload.get("summary") or ""),
                timed_beats=timed_beats,
                shot_state=shot_state,
                requires_mid_frame=bool(payload.get("requires_mid_frame", False)),
            ),
        }
        normalized.append(normalized_payload)
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
            scene_anchor_default=scene_anchor,
        )
        payload["scene_id"] = scene_id
        payload["scene_title"] = scene_title
        payload["scene_summary"] = scene_summary
        payload["scene_anchor"] = scene_anchor
        payload["scene_bible"] = dict(scene_bible)
        shot_state = _normalize_shared_shot_state_for_frame_groups(
            shot_state,
            start_frame_characters=_normalize_name_list(payload.get("start_frame_characters", [])),
            mid_frame_characters=_normalize_name_list(payload.get("mid_frame_characters", [])),
            end_frame_characters=_normalize_name_list(payload.get("end_frame_characters", [])),
            requires_mid_frame=bool(payload.get("requires_mid_frame", False)),
        )
        payload["shot_state"] = dict(shot_state)
        payload["continuity_link"] = dict(
            _normalize_continuity_link(payload.get("continuity_link"))
        )
        payload["motion_plan"] = dict(
            _normalize_motion_plan(
                payload.get("motion_plan"),
                summary=str(payload.get("summary") or scene_summary or ""),
                timed_beats=[str(item).strip() for item in payload.get("timed_beats", []) if str(item).strip()],
                shot_state=payload.get("shot_state"),
                requires_mid_frame=bool(payload.get("requires_mid_frame", False)),
            )
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
                "scene_transition_contract": _normalize_scene_transition_contract(
                    payload.get("scene_transition_contract"),
                ),
                "scene_master_frame_prompt": str(payload.get("scene_master_frame_prompt") or "").strip(),
                "scene_master_frame_path": str(payload.get("scene_master_frame_path") or "").strip(),
                "scene_master_frame_url": str(payload.get("scene_master_frame_url") or "").strip(),
                "scene_master_frame_status": str(
                    payload.get("scene_master_frame_status") or "planned"
                ).strip() or "planned",
                "scene_master_frame_error": str(payload.get("scene_master_frame_error") or "").strip(),
                "scene_master_request_info": dict(payload.get("scene_master_request_info", {}) or {}),
                "involved_characters": [],
                "covered_event_ids": _normalize_name_list(payload.get("covered_event_ids", [])),
                "covered_event_summaries": [
                    str(item).strip()
                    for item in payload.get("covered_event_summaries", [])
                    if str(item).strip()
                ],
                "segments": [],
            },
        )
        if _scene_bible_has_signal(scene_bible) and not _scene_bible_has_signal(group.get("scene_bible", {})):
            group["scene_bible"] = scene_bible
        current_transition_contract = _coerce_mapping(group.get("scene_transition_contract")) or {}
        incoming_transition_contract = _normalize_scene_transition_contract_for_scene(
            payload.get("scene_transition_contract"),
            title=scene_title or f"场景 {index}",
            summary=scene_summary or scene_title or f"场景 {index}",
            scene_anchor=scene_anchor,
            scene_bible=scene_bible,
            involved_characters=_normalize_name_list(payload.get("involved_characters", [])),
        )
        if incoming_transition_contract.get("previous_scene_id") and not current_transition_contract.get(
            "previous_scene_id"
        ):
            group["scene_transition_contract"] = incoming_transition_contract
        for key in (
            "scene_master_frame_prompt",
            "scene_master_frame_path",
            "scene_master_frame_url",
            "scene_master_frame_status",
            "scene_master_frame_error",
            "scene_master_request_info",
        ):
            if key == "scene_master_request_info":
                current_value = dict(group.get(key, {}) or {})
                incoming_value = dict(payload.get(key, {}) or {})
                if incoming_value and not current_value:
                    group[key] = incoming_value
                continue
            current_value = str(group.get(key, "") or "").strip()
            incoming_value = str(payload.get(key, "") or "").strip()
            if incoming_value and not current_value:
                group[key] = incoming_value
        if not group.get("covered_event_ids"):
            group["covered_event_ids"] = _normalize_name_list(payload.get("covered_event_ids", []))
        if not group.get("covered_event_summaries"):
            group["covered_event_summaries"] = [
                str(item).strip()
                for item in payload.get("covered_event_summaries", [])
                if str(item).strip()
            ]
        group["segments"].append(payload)

    normalized = list(grouped.values())
    for scene in normalized:
        scene["involved_characters"] = _collect_scene_characters(scene.get("segments", []))
    return normalized


def _normalize_scene_segment_chunks(raw_chunks: list[object]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, raw_chunk in enumerate(raw_chunks, start=1):
        payload = _coerce_mapping(raw_chunk)
        if payload is None:
            continue
        must_cover = payload.get("must_cover", [])
        normalized.append(
            {
                "chunk_id": str(
                    payload.get("chunk_id")
                    or payload.get("id")
                    or f"chunk-{index:02d}"
                ).strip()
                or f"chunk-{index:02d}",
                "order_index": int(payload.get("order_index") or payload.get("index") or index),
                "title": str(payload.get("title") or f"分块 {index}").strip() or f"分块 {index}",
                "summary": str(payload.get("summary") or "").strip(),
                "must_cover": [
                    str(item).strip()
                    for item in must_cover
                    if str(item).strip()
                ]
                if isinstance(must_cover, list)
                else [],
                "transition_goal": str(payload.get("transition_goal") or "").strip(),
                "expected_segment_count": int(payload.get("expected_segment_count") or 1),
            }
        )
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
        normalized["action_progression"] = default_summary or "保持当前片段的核心动作推进。"
        normalized["emotion_progression"] = default_summary or "情绪沿当前片段自然推进。"
        normalized["prop_continuity"] = "保持服装、持物、手部状态和关键道具连续，不要凭空增删。"
        normalized["screen_direction"] = "保持角色运动方向与视线方向一致，避免突然反轴。"
        normalized["end_state_lock"] = default_summary or "保持片段尾部动作与姿态，便于下一段承接。"
    return normalized


def _normalize_shared_shot_state_for_frame_groups(
    shot_state: object,
    *,
    start_frame_characters: list[str],
    mid_frame_characters: list[str],
    end_frame_characters: list[str],
    requires_mid_frame: bool,
) -> dict[str, object]:
    normalized = ShotStateSchema.model_validate(_coerce_mapping(shot_state) or {}).model_dump()
    multi_frame_groups = [
        _unique_names(start_frame_characters),
        _unique_names(mid_frame_characters) if requires_mid_frame else [],
        _unique_names(end_frame_characters),
    ]
    multi_frame_groups = [group for group in multi_frame_groups if len(group) >= 2]
    if not multi_frame_groups:
        return normalized
    frame_names = "、".join(multi_frame_groups[0][:3])
    shared_framing = f"多人同框中景关系镜头，保持 {frame_names} 同框，完整交代角色相对位置。"
    shared_motion = f"镜头轻微推进或稳定跟随，保持 {frame_names} 多人同框；只通过站位、视线和表情差异突出主要情绪。"
    if _shared_shot_text_has_single_subject_focus(
        str(normalized.get("framing", "") or ""),
        multi_frame_groups,
    ):
        normalized["framing"] = shared_framing
    if _shared_shot_text_has_single_subject_focus(
        str(normalized.get("camera_motion", "") or ""),
        multi_frame_groups,
    ):
        normalized["camera_motion"] = shared_motion
    return normalized


def _shared_shot_text_has_single_subject_focus(
    text: str,
    multi_frame_groups: list[list[str]],
) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if any(
        token in normalized
        for token in (
            "双人特写",
            "两人特写",
            "双人近景",
            "两人近景",
            "双人中近景",
            "两人中近景",
            "双人同框",
            "两人同框",
            "多人同框",
        )
    ):
        return False
    focus_tokens = ("特写", "大特写", "近景", "中近景", "侧脸", "脸部", "面部", "半脸")
    if not any(token in normalized for token in focus_tokens):
        return False
    frame_names = {name for group in multi_frame_groups for name in group}
    if any(name in normalized for name in frame_names):
        return True
    return any(
        token in normalized
        for token in ("推向", "推近", "推进到", "聚焦到", "切到", "拉到", "摇到")
    )


def _unique_names(names: list[str]) -> list[str]:
    unique: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        if name and name not in unique:
            unique.append(name)
    return unique


def _normalize_continuity_link(raw_continuity_link: object) -> dict[str, object]:
    payload = _coerce_mapping(raw_continuity_link) or {}
    normalized = ContinuityLinkSchema.model_validate(payload).model_dump()
    normalized["transition_mode"] = _normalize_transition_mode(
        normalized.get("transition_mode", "start")
    )
    return normalized


def _normalize_motion_plan(
    raw_motion_plan: object,
    *,
    summary: str,
    timed_beats: list[str],
    shot_state: object,
    requires_mid_frame: bool,
) -> dict[str, object]:
    payload = _coerce_mapping(raw_motion_plan) or {}
    normalized = MotionPlanSchema.model_validate(payload).model_dump()
    shot_payload = _coerce_mapping(shot_state) or {}
    beat_focuses = [_extract_timed_beat_focus(item) for item in timed_beats]
    beat_focuses = [item for item in beat_focuses if item]
    action_progression = str(shot_payload.get("action_progression") or "").strip()
    camera_motion = str(shot_payload.get("camera_motion") or "").strip()
    blocking = str(shot_payload.get("blocking") or "").strip()
    end_state_lock = str(shot_payload.get("end_state_lock") or "").strip()
    default_start = beat_focuses[0] if beat_focuses else action_progression or summary
    default_mid = beat_focuses[len(beat_focuses) // 2] if len(beat_focuses) >= 3 else ""
    default_end = beat_focuses[-1] if beat_focuses else end_state_lock or action_progression or summary
    if not str(normalized.get("start_to_mid") or "").strip():
        if requires_mid_frame:
            normalized["start_to_mid"] = _join_motion_clauses(default_start, default_mid or action_progression)
        else:
            normalized["start_to_mid"] = _join_motion_clauses(default_start, default_end)
    if requires_mid_frame and not str(normalized.get("mid_to_end") or "").strip():
        normalized["mid_to_end"] = _join_motion_clauses(default_mid or action_progression, default_end)
    if not str(normalized.get("camera_path") or "").strip():
        normalized["camera_path"] = camera_motion or "镜头按关键帧顺序自然推进，不在片尾硬切到下一张图。"
    if not str(normalized.get("character_motion") or "").strip():
        normalized["character_motion"] = blocking or action_progression or summary or "角色按当前节拍完成可见动作变化。"
    if not str(normalized.get("continuity_guard") or "").strip():
        normalized["continuity_guard"] = "保持同一场景、同一角色身份和同一运动方向，避免突然换景、少人、换脸或跳尾帧。"
    return normalized


def _extract_timed_beat_focus(beat: str) -> str:
    normalized = str(beat or "").strip()
    if not normalized:
        return ""
    for separator in ("：", ":"):
        if separator in normalized:
            return normalized.split(separator, 1)[1].strip(" ，。；;")
    return normalized.strip(" ，。；;")


def _join_motion_clauses(*clauses: str) -> str:
    normalized: list[str] = []
    for clause in clauses:
        text = str(clause or "").strip(" ，。；;")
        if text and text not in normalized:
            normalized.append(text)
    return "，再".join(normalized[:2])


def _normalize_scene_transition_contract(raw_contract: object) -> dict[str, object]:
    payload = _coerce_mapping(raw_contract) or {}
    normalized = SceneTransitionContractSchema.model_validate(payload).model_dump()
    normalized["transition_mode"] = _normalize_scene_transition_mode(
        normalized.get("transition_mode", "")
    )
    normalized["audio_bridge"] = _normalize_scene_audio_bridge(
        normalized.get("audio_bridge", "none")
    )
    normalized["carry_over_elements"] = _normalize_name_list(
        normalized.get("carry_over_elements", [])
    )
    return normalized


def _normalize_scene_transition_contract_for_scene(
    raw_contract: object,
    *,
    title: str,
    summary: str,
    scene_anchor: str,
    scene_bible: object,
    involved_characters: list[str],
) -> dict[str, object]:
    normalized = _normalize_scene_transition_contract(raw_contract)
    if not str(normalized.get("previous_scene_id", "") or "").strip():
        return normalized
    if _transition_entry_has_current_scene_signal(
        str(normalized.get("next_scene_entry_match", "") or ""),
        title=title,
        summary=summary,
        scene_anchor=scene_anchor,
        scene_bible=scene_bible,
    ):
        return normalized

    current_opening = _build_scene_transition_entry_default(
        title=title,
        summary=summary,
        scene_anchor=scene_anchor,
        scene_bible=scene_bible,
        involved_characters=involved_characters,
    )
    existing_entry = str(normalized.get("next_scene_entry_match", "") or "").strip(" ，。；;")
    normalized["next_scene_entry_match"] = (
        f"{current_opening}；{existing_entry}" if existing_entry else current_opening
    )
    return normalized


def _build_scene_transition_entry_default(
    *,
    title: str,
    summary: str,
    scene_anchor: str,
    scene_bible: object,
    involved_characters: list[str],
) -> str:
    scene_payload = _coerce_mapping(scene_bible) or {}
    location = str(scene_payload.get("location", "") or "").strip()
    spatial_layout = str(scene_payload.get("spatial_layout", "") or "").strip()
    character_blocking = str(scene_payload.get("character_blocking", "") or "").strip()
    background_anchors = [
        str(item).strip()
        for item in list(scene_payload.get("background_anchors", []) or [])[:2]
        if str(item).strip()
    ]
    scene_place = location or scene_anchor or title or summary or "当前场景"
    if character_blocking:
        blocking = character_blocking
    else:
        names = "、".join(involved_characters[:3]) or "当前出镜角色"
        blocking = f"{names}先落在当前场景的开场站位"
    background = "、".join(background_anchors) or spatial_layout
    if background:
        return f"当前场开头先建立{scene_place}，{blocking}，画面可见{background}"
    return f"当前场开头先建立{scene_place}，{blocking}"


def _transition_entry_has_current_scene_signal(
    text: str,
    *,
    title: str,
    summary: str,
    scene_anchor: str,
    scene_bible: object,
) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    scene_payload = _coerce_mapping(scene_bible) or {}
    anchors = [
        title,
        scene_anchor,
        str(scene_payload.get("location", "") or ""),
        str(scene_payload.get("spatial_layout", "") or ""),
        str(scene_payload.get("character_blocking", "") or ""),
    ]
    anchors.extend(str(item) for item in list(scene_payload.get("background_anchors", []) or []))
    anchors.extend(str(item) for item in list(scene_payload.get("fixed_props", []) or []))
    concrete_anchors = [item.strip() for item in anchors if len(str(item).strip()) >= 2]
    if any(anchor in normalized for anchor in concrete_anchors[:8]):
        return True
    signal = " ".join([summary, scene_anchor, " ".join(concrete_anchors[:8])])
    return _simple_text_overlap(normalized, signal) >= 0.08


def _simple_text_overlap(left: str, right: str) -> float:
    left_tokens = _scene_signal_tokens(left)
    right_tokens = _scene_signal_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


def _scene_signal_tokens(text: str) -> set[str]:
    normalized = str(text or "")
    tokens: set[str] = set()
    current = []
    for char in normalized:
        if "\u4e00" <= char <= "\u9fff":
            current.append(char)
        else:
            if len(current) >= 2:
                chunk = "".join(current)
                tokens.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
            current = []
    if len(current) >= 2:
        chunk = "".join(current)
        tokens.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
    return tokens


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


def _normalize_scene_transition_mode(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if value in {"direct_continue", "adjacent_move", "motivated_cut", "hard_cut"}:
        return value
    return ""


def _normalize_scene_audio_bridge(raw_value: object) -> str:
    value = str(raw_value or "").strip().lower()
    if value in {"none", "j_cut", "l_cut", "ambient_bridge"}:
        return value
    return "none"
