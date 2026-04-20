from __future__ import annotations

import json
import re

from storyforge.domains.novel.contracts import CharacterVoiceProfile, NovelPackage
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    StoryMemoryPackage,
    VideoScene,
    VideoSegment,
)


class VideoPromptingMixin:
    CHAPTER_SCENE_PLANNER_EXCERPT_CHARS = 780
    SCENE_CHUNK_PLANNER_EXCERPT_CHARS = 420
    SCENE_SEGMENT_CHUNK_CONTRACT_EXCERPT_CHARS = 320
    STORY_MEMORY_RECENT_CHAPTER_LIMIT = 2
    STORY_MEMORY_RECENT_SCENE_LIMIT = 1
    STORY_MEMORY_MAX_CHAPTER_CAST = 4
    STORY_MEMORY_MAX_SCENE_CAST = 3

    SCENE_NO_TEXT_PROMPT = (
        "画面中禁止出现任何可见文字、对白字幕、台词字卡、聊天气泡、漫画对话框、旁白框、"
        "屏幕贴字、海报文案、水印、Logo、片名字样或说明性排版。"
        "本阶段只生成纯画面分镜，所有对白和硬字幕都只在后续视频阶段添加，不要提前画进图片里。"
    )
    SCENE_MASTER_FRAME_NO_PEOPLE_PROMPT = (
        "这是一张纯场景参考图。画面中不得出现任何人物、角色、人脸、人体局部、背影、剪影、"
        "倒影、影子、手脚、服装边角、人物海报、人物照片、人物雕像或其它拟人主体。"
        "如果输入材料里出现角色名、人物站位、动作、表演、对白、情绪，请全部忽略，只保留空场景本身。"
    )

    CHARACTER_SHEET_LAYOUT_PROMPT = (
        "统一三视图模板 SF-TURN-01：所有角色定妆图必须使用完全相同的横版 16:9 白底三视图版式，"
        "同一项目内所有角色必须保持同一种美术风格、同一种线条粗细、同一种上色方式和同一种柔和光照，"
        "不得因角色身份、性别或剧情气质改变构图、画风、镜头焦段或渲染质感。"
        "背景必须是纯白色，不要场景、不要道具陈列、不要灰底网格、不要信息格、不要色卡、不要材质块。"
        "画面顶部只允许出现角色中文姓名；不得写性别、身份、职业、角色定位、英文标签、编号、水印或说明文字。"
        "画面主体固定为三栏等宽全身站姿：左栏正面，中栏左侧面，右栏背面。"
        "三视图都必须平视，双脚完整入画，脚底对齐同一基准线，人物高度和缩放比例完全一致，"
        "双臂自然下垂或轻微离开身体，避免夸张动作。"
        "统一采用干净高级的动画电影概念设定稿风格，柔和赛璐璐上色，低饱和自然色彩，清晰轮廓线，"
        "避免有的角色偏写实、有的角色偏二次元、有的角色偏照片或海报。"
        "同一张图里只能是同一个角色的正面、左侧面和背面参考，不得出现第二个独立角色或剧情场景。"
    )

    def _strip_internal_segment_markers(self, text: str) -> str:
        cleaned = str(text or "")
        if not cleaned:
            return ""
        cleaned = re.sub(r"\s*/\s*第\d+段", " ", cleaned)
        cleaned = re.sub(r"[（(]\s*当前为第\s*\d+\s*/\s*\d+\s*段\s*[）)]", " ", cleaned)
        cleaned = re.sub(
            r"\s*当前子片段：第\d+\s*/\s*\d+段(?:，重点：[^。；!?！？]*)?[。；!?！？]?",
            " ",
            cleaned,
        )
        for marker in (
            "开场重点：",
            "中段重点：",
            "收束重点：",
            "收束状态：",
            "重点呈现：",
        ):
            cleaned = cleaned.replace(marker, "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s*([，。；：!?！？])\s*", r"\1", cleaned)
        cleaned = cleaned.strip(" ，。；：!?！？")
        return cleaned

    def _prompt_json(self, payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _scene_bible_rule_block(self) -> str:
        return (
            "- `scene_bible` 只写可复用环境基线：地点、时间、天气、光线、主色、背景锚点、固定道具、空间布局、角色调度、连续性说明。\n"
            "- `scene_bible` 短写：`dominant_palette` 最多 3 个词，`background_anchors` 最多 4 项，`fixed_props` 最多 3 项，其余字段尽量 1 句。\n"
            "- `background_anchors`、`fixed_props` 只能写可见实体或布景元素，例如长椅、路灯、拱门、花墙、书包；不要写情绪、冲突、关系或抽象概念。\n"
            "- 不要写对白、字幕或剧情分析。"
        )

    def _frame_character_rule_block(self) -> str:
        return (
            "- `involved_characters` 只包含当前 segment 真正出镜或发声的角色；当前段未出镜、未发声的人物不要写进来。\n"
            "- `dialogue_lines` 中出现的所有角色，都必须进入 `involved_characters`。\n"
            "- `start_frame_characters`、`mid_frame_characters`、`end_frame_characters` 都必须是 `involved_characters` 的子集，且只包含该帧真正出镜的人物。\n"
            "- 如果首帧是单人等待、独白、回头或站立，不要把尚未出镜的人物写进首帧；尾帧同理。\n"
            "- `mid_frame_characters` 必须严格跟随片段中间那一拍真实出镜角色，不要直接照搬整个 scene cast，也不要把只在尾帧才出现的人物提前写进中段帧。\n"
            "- 若片段为多人同框、时长 >= 8 秒、对白 >= 2 句，或 `timed_beats` 有 3 拍及以上，`requires_mid_frame` 必须为 true，且必须显式给出 `mid_frame_characters`；不要把这项留给系统推断。\n"
            "- 若 `requires_mid_frame = false`，`mid_frame_characters` 必须为空数组。"
        )

    def _segment_audio_budget_rule_block(self) -> str:
        return (
            f"- `duration_seconds` 必须在 {self.PLANNER_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒内，并按中文自然口播语速估算音频长度，约每秒 {self.SPEECH_CHARS_PER_SECOND} 个中文字。\n"
            "- 5 秒片段只能放极短句，总旁白 + 对白 + 硬字幕文案约 15 字以内；8 秒片段约 24 字以内；12 秒片段约 36 字以内。\n"
            "- 如果旁白、对白或硬字幕超过当前时长可说完的字数，必须拆成下一个片段，不得硬塞进同一段。\n"
            "- 5-8 秒片段通常只允许 1 句可听见对白；12 秒片段通常最多 2 句，且每句都要短。\n"
            "- `subtitle_lines` 只允许写本段真正会被听到的对白或旁白；纯动作段输出空数组，不要把动作说明直接写成硬字幕。\n"
            "- 每个 `segment` 都必须显式输出非空 `timed_beats`；即使是纯动作段也至少写 1 条，格式示例：`0-2秒：他停下脚步，看向湖面。`\n"
            "- 5-6 秒片段通常输出 1-2 条 `timed_beats`；8-12 秒片段通常输出 2-3 条。不要把整段压成一条 `0-10秒：两人继续交流` 这种泛描述。\n"
            "- `subtitle_lines` 只能写本片段实际能在音频里说完的文字；`timed_beats` 要写清每句话或每拍动作在几秒发生。"
        )

    def _segment_continuity_rule_block(self) -> str:
        return (
            "- 相邻 segment 必须按真实顺序推进，不能重复上一拍动作，也不能提前写后续高潮或结果。\n"
            "- 同场景连续承接时，`transition_mode` 应为 `continue`，`opening_match` 要明确上一段尾部状态，`allowed_changes` 只写本段新增推进。\n"
            "- 起始段若使用 `transition_mode = start`，`opening_match` 也要简短写出本段开场已成立的站位、动作或环境状态，不要留空。\n"
            "- `opening_match` 必须写成可拍到的开场画面，不要写成“承接上一段继续”“场景开始”“继续推进”这类空话。\n"
            "- `transition_mode = start` 示例：`陈默已站在镜湖长椅旁，面向湖面等待。`；`transition_mode = continue` 示例：`承接上一段尾部，陈默仍站在长椅旁，刚回头看向来人。`\n"
            "- 同一 chunk 内相邻 segment 的 `title` 不得相同，也不能只是“继续 / 再次 / 延续 / 停顿”这类弱变化。\n"
            "- 明显转场用 `cut`，起始段用 `start`。"
        )

    def _anti_micro_split_rule_block(self) -> str:
        return (
            "- 告白、回应、对峙、双人长对话 scene 要优先少段而不是碎段；同一发言轮次通常只允许 1 个 segment，确实超出字数预算时才拆成 2 个。\n"
            "- `停下脚步`、`抬头`、`深吸一口气`、`沉默`、`对视` 这类预备动作，如果仍服务于同一次开口，不要单独拆成新的 segment。\n"
            "- 只有出现新的对白轮次、明确空间位移、动作结果落地或关系状态变化，才能进入下一段。\n"
            "- 如果两个相邻 segment 仍是同一地点、同一出镜角色、同一情绪目标，只是换说法描述同一动作，应合并。"
        )

    def _segment_field_concision_rule_block(self) -> str:
        return (
            "- `title`、`summary` 只写当前段新增推进，不要把整个 scene / chunk 摘要重复抄进来，也不要加 `第1段`、`第2段`、`继续`、`延续` 这类编号或弱变化标签。\n"
            "- `narration`、`shot_state`、`continuity_link` 都要短写，每个字段尽量 1 句；禁止散文、禁止复述父级 scene 的整段背景说明。\n"
            "- 如果当前 chunk 实际只有 1 个完整事件结果，不必凑满 `expected_segment_count`；它是执行上限，不是必须补满的目标值。"
        )

    def _chunk_split_rule_block(self) -> str:
        return (
            "- 一个 chunk 必须对应一个连续事件目标，而不是一个小动作词；不要把“等待 / 深呼吸 / 看手机 / 继续等待”拆成多个近义 chunk。\n"
            "- `expected_segment_count` 要按保守上限填写，优先填 1；只有 chunk 内确实存在两个以上完整推进点时才填 2-4。\n"
            "- 如果 `title`、`summary` 或 `must_cover` 只是把前一个 chunk 换说法重写，说明拆得太碎，应合并。"
        )

    def _structured_output_guardrail_line(self) -> str:
        return "- 只返回结构化结果，不要解释，不要输出 Markdown 代码块。"

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
8. `portrait_prompt` 只描述人物特征，不要自行指定与统一角色定妆卡冲突的构图、场景或镜头
""".strip()

    def _build_chapter_scene_planner_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            chapter_scoped=True,
            focus_characters=chapter_outline.featured_characters,
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.CHAPTER_SCENE_PLANNER_EXCERPT_CHARS,
        )
        previous_exit = memory_context.get("previous_chapter_exit_state", {})
        previous_exit_json = self._prompt_json(previous_exit)
        memory_json = self._prompt_json(memory_context)
        chapter_id_prefix = f"ch{chapter_number:02d}"
        return f"""
请只为当前章节生成场景结构，不要生成片段，不要生成任何图片 prompt。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次只允许输出第 {chapter_number} 章内容，不得把后续章节事件、关系进展或高潮提前写进本章。
- 你只需要输出 `scenes`；字段契约以结构化 schema 为准，不要自造字段。
- 当前章可以拆成 1 个或多个 `scene`，必须完全根据当前章节正文决定。
- `scene_id` 必须以 `{chapter_id_prefix}-sc` 开头，例如 `{chapter_id_prefix}-sc01`。
{self._scene_bible_rule_block()}
- 如果发生明显地点切换、时间跳转、光线大变或叙事空间切换，就必须开新 scene。
- 如果正文是告白、对峙、争吵、审问、双人对话，`involved_characters` 必须同时包含双方。
- `summary`、`scene_anchor`、`scene_bible` 都尽量短写，避免长段散文。
- 不要输出 `segments`。
{self._structured_output_guardrail_line()}

上一章退出状态 JSON：
{previous_exit_json}

story memory JSON：
{memory_json}

当前章节拆分依据：
{chapter_block}
""".strip()

    def _build_scene_segment_contract_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
        chunk_payload: dict[str, object] | None = None,
        previous_chunk_exit_state: dict[str, object] | None = None,
        max_segments_override: int | None = None,
        forced_min_segments: int | None = None,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        focus_terms = self._build_scene_prompt_focus_terms(
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
        )
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            chapter_scoped=False,
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_SEGMENT_CHUNK_CONTRACT_EXCERPT_CHARS,
            focus_terms=focus_terms,
        )
        scene_json = self._prompt_json(scene_payload)
        chunk_json = self._prompt_json(chunk_payload or {})
        memory_json = self._prompt_json(memory_context)
        previous_chunk_exit_json = self._prompt_json(previous_chunk_exit_state or {})
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        effective_max_segments = int(
            max_segments_override
            or int((chunk_payload or {}).get("expected_segment_count", 4) or 4)
        )
        split_retry_directive = ""
        if forced_min_segments and forced_min_segments > 1:
            split_retry_directive = (
                f"- 上一轮校验发现当前 chunk 的对白预算已经超过单段 12 秒上限。"
                f"本次必须把当前 chunk 至少拆成 {forced_min_segments} 个 segment，"
                "优先按对白轮次、句意边界或动作结果落点拆开，"
                "不要再试图把整段对白硬塞进 1 个 segment。\n"
            )
        return f"""
请只为目标 scene 的当前 chunk 生成片段合同，不要生成场景 prompt，不要生成首帧/中段/尾帧 prompt。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次只允许输出 `segments`；字段契约以结构化 schema 为准，不要自造字段。
- 只覆盖 `目标 chunk JSON` 里当前 chunk 的内容，不得把前一个 chunk 已发生的事件重写一遍，也不得把后一个 chunk 的结果提前写进来。
- 所有 `segment.chapter_number` 必须是 {chapter_number}；所有 `segment.scene_id` 必须是 `{scene_id}`。
- 当前 chunk 一般拆成 1-3 个 segment，最多不超过 4 个；必须完全根据动作推进、对白密度和情绪转折决定。
- 当前 chunk 这次最多只能输出 {effective_max_segments} 个 segment；这就是当前执行上限，超过就视为失败，不要额外加段。
{split_retry_directive}- `expected_segment_count` 是上限，不是目标值；如果当前 chunk 实际只需要 1 个完整 segment，就只输出 1 个，不要为了凑数硬拆。
- 同一个动作单元，例如停步、回头、抬头、赏花、对视、沉默等待，默认只允许 1 个 segment；只有发生新的动作推进、空间位移、对白交换或关系变化时才能拆出下一段。
- 不得把同一拍动作改写成多段近义重复片段来拖时长；相邻 segment 必须看得出新增推进。
- 如果当前 chunk 是告白、回应、双人对话或情绪对峙，优先生成较少但更完整的 8-12 秒 segment，不要把一句话拆成多个 5-6 秒微段。
- 不要把“准备开口”和“真正开口”拆成两个近义连续片段，除非单段字数预算已经超限。
- 不要输出 `scene_prompt`、`start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- `segment_id` 只需在当前 chunk 内唯一，系统后续会统一重编；建议仍使用 `{scene_id}-seg01` 这类短格式。
- 每个 `segment` 都必须带 `timed_beats`，不能为空；如果任何一段漏掉 `timed_beats`，整批合同都会判失败并重试。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`、`当前为第2/2段`。
- 若片段时长 >= 8 秒、多人同框、动作推进明显或情绪关系变化明显，`requires_mid_frame` 必须为 true。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
- 如果 `上一 chunk 退出状态` 不为空，则当前 chunk 的第一个 segment 必须从该退出状态继续推进；不要重开场，不要把同一 scene 写成重新开始。
- 如果正文是告白、对峙、争吵、审问、双人对话，`involved_characters` 必须同时包含双方。
- 有对白时，`timed_beats` 必须明确写出哪一秒谁说了哪句；不要只写“她温柔回应”“他说出告白”这类抽象概括。
- 单条对白若超过约 18-22 个中文字符，或本身包含多个分句，必须在当前 chunk 内主动拆成多个 beats，必要时拆成多个 segment；不要把长句整段塞给后处理再拆。
- `shot_state` 只写镜头、调度、动作、道具和承接状态，尽量 1 句完成，不要写成长段散文。
{self._segment_field_concision_rule_block()}
{self._structured_output_guardrail_line()}

story memory JSON：
{memory_json}

上一 chunk 退出状态 JSON：
{previous_chunk_exit_json}

目标 chunk JSON：
{chunk_json}

目标 scene JSON：
{scene_json}

当前章节参考：
{chapter_block}
""".strip()

    def _build_scene_segment_overflow_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
        chunk_payload: dict[str, object] | None = None,
        previous_chunk_exit_state: dict[str, object] | None = None,
        failed_contract_payload: dict[str, object],
        offending_segment_id: str,
        required_duration_seconds: int,
        current_duration_seconds: int,
        required_segment_count: int,
        max_segments_override: int,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        focus_terms = self._build_scene_prompt_focus_terms(
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
        )
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            chapter_scoped=False,
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_SEGMENT_CHUNK_CONTRACT_EXCERPT_CHARS,
            focus_terms=focus_terms,
        )
        scene_json = self._prompt_json(scene_payload)
        chunk_json = self._prompt_json(chunk_payload or {})
        memory_json = self._prompt_json(memory_context)
        previous_chunk_exit_json = self._prompt_json(previous_chunk_exit_state or {})
        failed_contract_json = self._prompt_json(failed_contract_payload)
        offending_segment_payload = next(
            (
                item for item in list(failed_contract_payload.get("segments", []) or [])
                if str(item.get("segment_id", "")).strip() == offending_segment_id
            ),
            {},
        )
        offending_segment_json = self._prompt_json(offending_segment_payload)
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        return f"""
你是 StoryForge 的超长对白拆段修复 Agent。
你收到的是同一个 chunk 上一轮失败的完整合同。不要从零重写剧情；请基于失败合同做最小必要改写，把超长对白拆成可执行的正式 segment。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次必须返回当前 chunk 的完整 `segments` 列表，不是 patch，不是 diff。
- 所有 `segment.chapter_number` 必须是 {chapter_number}；所有 `segment.scene_id` 必须是 `{scene_id}`。
- 上一轮失败的超长片段是 `{offending_segment_id}`。
- 该片段的对白/字幕预算约为 {required_duration_seconds} 秒，但上一轮只给了 {current_duration_seconds} 秒；单段上限仍然只有 12 秒。
- 本次必须把当前 chunk 至少拆成 {required_segment_count} 个 segment，且最多只能输出 {max_segments_override} 个 segment。
- 如果上一轮 batch 里存在未超长的 segment，优先保留它们的事件顺序、角色承接、镜头状态和连续性，只重写必要片段。
- 不得再原样保留一个仍然超长的单段；必须把问题对白按句意边界、对白轮次、动作落点或回应节点拆开。
- 不得回放当前 chunk 之前已经发生的事件，也不得提前写入当前 chunk 之后的剧情结果。
- 不得为了满足拆分而制造近义重复段；拆出来的每一段都必须有新增推进。
- 如果某段文本预算仍能在 12 秒内说完，可以直接把 `duration_seconds` 提到所需秒数；只有确实超过 12 秒时才继续拆分。
- 不要输出 `scene_prompt`、`start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{self._segment_field_concision_rule_block()}
{self._structured_output_guardrail_line()}

story memory JSON：
{memory_json}

上一 chunk 退出状态 JSON：
{previous_chunk_exit_json}

目标 chunk JSON：
{chunk_json}

目标 scene JSON：
{scene_json}

上一轮失败 batch JSON：
{failed_contract_json}

上一轮超长 segment JSON：
{offending_segment_json}

当前章节参考：
{chapter_block}
""".strip()

    def _build_scene_chunk_planner_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        focus_terms = self._build_scene_prompt_focus_terms(scene_payload=scene_payload)
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            chapter_scoped=False,
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_CHUNK_PLANNER_EXCERPT_CHARS,
            focus_terms=focus_terms,
        )
        scene_json = self._prompt_json(scene_payload)
        memory_json = self._prompt_json(memory_context)
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        return f"""
请先把目标 scene 拆成连续的内部分块，只输出分块大纲，不要输出 segments，不要输出任何图片或视频 prompt。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次只允许输出 `chunks`；字段契约以结构化 schema 为准，不要自造字段。
- `chunks` 必须按当前 scene 内事件真实发生顺序排列，不能乱序、不能重叠，也不能把后面的高潮提前塞进前面的 chunk。
- 当前 scene 的第一个 chunk 必须从本 scene 在正文里的真正起点开始，不得把上一 scene 已完成的动作、对白、汇合、停步或关系推进重新演一遍。
- 如果上一 scene 已经完成了某个事件，本 scene 只能从“那个事件之后的新推进”开始，不能回放。
- 一个 scene 通常拆成 1-4 个 chunk；如果 scene 本身只有一个完整动作单元，就只输出 1 个 chunk。
- 对话、告白、回应类 scene 优先拆成 1-3 个 chunk；不要把同一轮告白、同一轮回应拆成多个近义重复 chunk。
- 整个 scene 的 `expected_segment_count` 总和通常控制在 2-8；不要为了拖时长把同一事件拆成大量 chunk。
- `expected_segment_count` 是后续 segment planner 的硬上限，也是你现在就要算准的最终执行数量；后续不得超过这个上限继续加段。
- `must_cover` 只写 1-3 条短句，`transition_goal` 只写一句短话，`expected_segment_count` 只填 1-4。
- 同一 scene 内相邻 chunk 必须有明确推进，不能只是换说法重复前一个 chunk。
- 不要把整个 scene 的完整摘要复制到每个 chunk；每个 chunk 只保留自己负责的那一小段。
{self._chunk_split_rule_block()}
{self._anti_micro_split_rule_block()}
{self._structured_output_guardrail_line()}

story memory JSON：
{memory_json}

目标 scene JSON：
{scene_json}

当前章节参考：
{chapter_block}
""".strip()

    def _build_story_memory_prompt_context(
        self,
        story_memory: StoryMemoryPackage,
        *,
        chapter_number: int,
        chapter_scoped: bool = False,
        focus_characters: list[str] | None = None,
    ) -> dict[str, object]:
        current_chapter_state = next(
            (
                item for item in story_memory.chapter_states
                if item.chapter_number == chapter_number
            ),
            None,
        )
        previous_chapter_state = next(
            (
                item
                for item in reversed(story_memory.chapter_states)
                if item.chapter_number < chapter_number and item.generated_segment_ids
            ),
            None,
        )
        recent_limit = (
            self.STORY_MEMORY_RECENT_CHAPTER_LIMIT
            if chapter_scoped
            else self.STORY_MEMORY_RECENT_SCENE_LIMIT
        )
        max_cast_entries = (
            self.STORY_MEMORY_MAX_CHAPTER_CAST
            if chapter_scoped
            else self.STORY_MEMORY_MAX_SCENE_CAST
        )
        focus_cast = self._build_story_memory_focus_cast_entries(
            story_memory,
            focus_characters=focus_characters or [],
            max_items=max_cast_entries,
        )
        recent_memory = self._build_story_memory_recent_chapter_memory(
            story_memory,
            chapter_number=chapter_number,
            limit=recent_limit,
        )
        chapter_batch_view = self._build_story_memory_chapter_batch_view(
            story_memory,
            chapter_number=chapter_number,
        )
        return {
            "story_identity": {
                "story_title": story_memory.story_identity.story_title,
                "story_source_revision": story_memory.story_identity.story_source_revision,
            },
            "global_story_bible": {
                "core_theme": story_memory.global_story_bible.core_theme,
                "narrative_promise": story_memory.global_story_bible.narrative_promise,
                "visual_motifs": story_memory.global_story_bible.visual_motifs,
                "forbidden_deviations": story_memory.global_story_bible.forbidden_deviations,
            },
            "chapter_batch_view": chapter_batch_view,
            "focus_cast_bible": focus_cast,
            "current_chapter_state": {
                "chapter_number": current_chapter_state.chapter_number if current_chapter_state else chapter_number,
                "chapter_title": current_chapter_state.chapter_title if current_chapter_state else "",
                "chapter_summary": (
                    self._compact_story_memory_text(
                        current_chapter_state.chapter_summary,
                        limit=120,
                    )
                    if current_chapter_state
                    else ""
                ),
                "entry_state": current_chapter_state.entry_state if current_chapter_state else {},
                "new_facts": current_chapter_state.new_facts[:3] if current_chapter_state else [],
                "resolved_threads": current_chapter_state.resolved_threads[:2] if current_chapter_state else [],
                "unresolved_threads": (
                    current_chapter_state.unresolved_threads[:3] if current_chapter_state else []
                ),
                "carry_over_summary": (
                    self._compact_story_memory_text(
                        current_chapter_state.carry_over_summary,
                        limit=100,
                    )
                    if current_chapter_state
                    else ""
                ),
                "carry_over_visuals": (
                    current_chapter_state.carry_over_visuals[:4] if current_chapter_state else []
                ),
                "carry_over_props": (
                    current_chapter_state.carry_over_props[:3] if current_chapter_state else []
                ),
                "relationship_state": (
                    current_chapter_state.relationship_state[:3] if current_chapter_state else []
                ),
            },
            "previous_chapter_exit_state": (
                self._build_story_memory_exit_state_payload(
                    previous_chapter_state.exit_state if previous_chapter_state else {}
                )
            ),
            "recent_chapter_memory": recent_memory,
            "continuity_state": {
                "current_time_context": story_memory.continuity_state.current_time_context,
                "current_location_context": story_memory.continuity_state.current_location_context,
                "active_props": story_memory.continuity_state.active_props[:4],
                "active_relationship_state": story_memory.continuity_state.active_relationship_state[:3],
                "carry_over_visuals": story_memory.continuity_state.carry_over_visuals[:5],
            },
        }

    def _build_story_memory_focus_cast_entries(
        self,
        story_memory: StoryMemoryPackage,
        *,
        focus_characters: list[str],
        max_items: int,
    ) -> list[dict[str, object]]:
        focus_names = {
            str(name).strip()
            for name in focus_characters
            if str(name).strip()
        }
        selected_entries = [
            item
            for item in story_memory.cast_bible
            if not focus_names or item.name in focus_names
        ]
        if not selected_entries:
            selected_entries = list(story_memory.cast_bible)
        return [
            {
                "name": item.name,
                "gender": item.gender,
                "role": item.role,
                "appearance_summary": self._compact_story_memory_text(item.appearance_summary, limit=80),
                "voice_summary": self._compact_story_memory_text(item.voice_summary, limit=60),
                "personality_summary": self._compact_story_memory_text(item.personality_summary, limit=80),
                "hard_constraints": list(item.hard_constraints[:2]),
            }
            for item in selected_entries[:max_items]
        ]

    def _build_story_memory_recent_chapter_memory(
        self,
        story_memory: StoryMemoryPackage,
        *,
        chapter_number: int,
        limit: int,
    ) -> list[dict[str, object]]:
        completed_states = [
            item
            for item in story_memory.chapter_states
            if item.chapter_number < chapter_number and item.generated_segment_ids
        ]
        recent_states = completed_states[-max(0, limit):]
        return [
            {
                "chapter_number": item.chapter_number,
                "chapter_title": item.chapter_title,
                "chapter_summary": self._compact_story_memory_text(item.chapter_summary, limit=70),
                "new_facts": list(item.new_facts[:2]),
                "resolved_threads": list(item.resolved_threads[:2]),
                "unresolved_threads": list(item.unresolved_threads[:2]),
                "carry_over_summary": self._compact_story_memory_text(item.carry_over_summary, limit=90),
                "carry_over_visuals": list(item.carry_over_visuals[:4]),
                "carry_over_props": list(item.carry_over_props[:3]),
                "relationship_state": list(item.relationship_state[:3]),
                "exit_state": self._build_story_memory_exit_state_payload(item.exit_state),
                "generated_scene_count": len(item.generated_scene_ids),
                "generated_segment_count": len(item.generated_segment_ids),
            }
            for item in recent_states
        ]

    def _build_story_memory_chapter_batch_view(
        self,
        story_memory: StoryMemoryPackage,
        *,
        chapter_number: int,
    ) -> dict[str, object]:
        completed_chapters = [
            item.chapter_number
            for item in story_memory.planning_index.chapters
            if item.segment_count > 0
        ]
        upcoming_chapters = [
            {
                "chapter_number": item.chapter_number,
                "chapter_title": item.chapter_title,
                "chapter_summary": self._compact_story_memory_text(item.chapter_summary, limit=60),
            }
            for item in story_memory.chapter_states
            if item.chapter_number > chapter_number
        ][:2]
        return {
            "current_chapter_number": chapter_number,
            "last_planned_chapter": story_memory.generation_notes.last_planned_chapter,
            "recent_planned_chapters": completed_chapters[-self.STORY_MEMORY_RECENT_CHAPTER_LIMIT :],
            "upcoming_chapter_guard": upcoming_chapters,
            "planned_scene_count": story_memory.planning_index.scene_count,
            "planned_segment_count": story_memory.planning_index.segment_count,
        }

    def _build_story_memory_exit_state_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if not payload:
            return {}
        return {
            "segment_id": str(payload.get("segment_id", "") or ""),
            "scene_id": str(payload.get("scene_id", "") or ""),
            "scene_title": self._compact_story_memory_text(
                str(payload.get("scene_title", "") or ""),
                limit=60,
            ),
            "summary": self._compact_story_memory_text(
                str(payload.get("summary", "") or ""),
                limit=80,
            ),
            "carry_over_characters": list(payload.get("carry_over_characters", []) or [])[:3],
            "end_state_lock": self._compact_story_memory_text(
                str(payload.get("end_state_lock", "") or ""),
                limit=80,
            ),
            "transition_hint": str(payload.get("transition_hint", "") or ""),
        }

    def _build_segment_continuity_repair_user_prompt(
        self,
        *,
        story_title: str,
        character_profiles: list[CharacterVisualProfile],
        scene_payload: dict[str, object],
        segment_payload: dict[str, object],
        previous_segment_payload: dict[str, object] | None,
        next_segment_payload: dict[str, object] | None,
        continuity_issues: list[dict[str, object]],
        speech_budget_context: dict[str, object] | None = None,
    ) -> str:
        context = {
            "story_title": story_title,
            "character_profiles": [
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                    "appearance": item.appearance,
                    "outfit": item.outfit,
                }
                for item in character_profiles
            ],
            "target_scene": scene_payload,
            "target_segment": segment_payload,
            "previous_segment": previous_segment_payload,
            "next_segment": next_segment_payload,
            "continuity_issues": continuity_issues,
            "speech_budget_context": speech_budget_context or {},
        }
        allowed_names = "、".join(
            str(item.get("name", "")).strip()
            for item in context["character_profiles"]
            if str(item.get("name", "")).strip()
        ) or "无"
        return f"""
请只修复目标片段的连续性规划，不要重写整个故事。

- 小说标题：{story_title}
- 允许角色白名单：{allowed_names}
- 只能修复 `target_segment`
- 不能修改：`segment_id`、`scene_id`、`scene_title`、`scene_summary`、`scene_anchor`、`involved_characters`
- 不能新增角色、改名、换 scene、换章节
- 你只能调整这些字段：
  - `scene_prompt`
  - `start_frame_prompt`
  - `mid_frame_prompt`
  - `end_frame_prompt`
  - `start_frame_characters`
  - `mid_frame_characters`
  - `end_frame_characters`
  - `narration`
  - `dialogue_lines`
  - `subtitle_lines`
  - `timed_beats`
  - `duration_seconds`
  - `requires_mid_frame`
  - `transition_hint`
  - `shot_state`
  - `continuity_link`
- 输出必须让画面承接、动作推进、对白长度、字幕时长更成立
- `duration_seconds` 必须在 5-12 秒
- `subtitle_lines` 必须和实际能说完的旁白/对白一致
- `timed_beats` 必须写出具体秒数，不要只写抽象节奏
- `start_frame_characters` / `mid_frame_characters` / `end_frame_characters` 必须是 `involved_characters` 的子集
- 如果不需要中段帧，`requires_mid_frame=false`，并把 `mid_frame_prompt` 置空、`mid_frame_characters` 置空数组
- 如果问题主要是对白超时，就优先缩短对白、拆短字幕、压缩旁白，而不是盲目拉满 12 秒
- 如果 `speech_budget_context.required_duration_seconds` 已经大于 12，说明原文本本身塞不进单段视频；你必须主动删减或改写对白、旁白和字幕，让修复后的文本能在 12 秒内说完，不能试图保留原长文本
- 如果问题主要是动作或站位不连贯，就优先修 `shot_state`、`continuity_link` 和帧 prompt
- 如果目标片段承接上一段，`continuity_link.opening_match` 必须明确写出上一段尾部在当前段开场如何被复现
- `continuity_link.allowed_changes` 必须明确写出这一段比上一段新增推进的动作或关系变化，不能只是重复上一段
- 不要输出解释，不要输出 Markdown，只返回结构化结果

上下文 JSON：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()

    def _build_scene_continuity_repair_user_prompt(
        self,
        *,
        story_title: str,
        character_profiles: list[CharacterVisualProfile],
        scene_payload: dict[str, object],
        target_segment_payloads: list[dict[str, object]],
        scene_issues: list[dict[str, object]],
        related_segment_issues: list[dict[str, object]],
        selection_mode: str,
    ) -> str:
        context = {
            "story_title": story_title,
            "character_profiles": [
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                }
                for item in character_profiles
            ],
            "target_scene": scene_payload,
            "target_segments": target_segment_payloads,
            "scene_issues": scene_issues,
            "related_segment_issues": related_segment_issues,
            "selection_mode": selection_mode,
        }
        return f"""
请只修复目标 scene 的场景连续性基线，不要重写剧情，不要改章节结构，不要新增角色。

- 小说标题：{story_title}
- 只能修复 `target_scene`
- 不能修改：`scene_id`、`chapter_number`、`title`、`summary`、`involved_characters`
- 你只能调整这些字段：
  - `scene_anchor`
  - `scene_bible`
- `scene_bible` 必须服务于同一 scene 下多个 segment 的稳定复用，写法要偏环境、空间、光线、固定道具和连续性，不要写对白，不要写剧情分析
- 如果当前问题是“入口处”和“向内部漫步”的空间关系不稳定，就把场景锚点与场景圣经改写成能同时覆盖入口到内部花径的连续空间，而不是只盯死在入口一角
- `background_anchors` 至少给 3 个稳定锚点，`fixed_props` 至少给 2 个，`dominant_palette` 至少给 2 个
- `spatial_layout` 必须明确空间延展方向、可移动路径和镜头透视
- `continuity_notes` 必须明确哪些场景元素在同一 scene 多个片段里不能漂移
- 输出要短、稳、可复用，不要写 Markdown，不要解释，只返回结构化结果

上下文 JSON：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()

    def _build_chapter_segment_directive(
        self,
        novel_package: NovelPackage,
        chapter_number: int,
        excerpt_max_chars: int = 1400,
        focus_terms: list[str] | None = None,
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
        focus_term_list = [
            item
            for item in (focus_terms or [])
            if item
        ]
        excerpt = self._excerpt_relevant_text(
            draft.markdown if draft else chapter.summary,
            keywords=focus_term_list,
            max_chars=excerpt_max_chars,
        )
        focus_line = (
            f"  本次聚焦：{'、'.join(focus_term_list[:6])}\n"
            if focus_term_list
            else ""
        )
        return (
            f"- 第 {chapter.number} 章《{chapter.title}》\n"
            "  该章应由模型自行判断拆成几段\n"
            f"  章节目标：{chapter.goal}\n"
            f"  章节摘要：{chapter.summary}\n"
            f"  关键冲突：{chapter.key_conflict}\n"
            f"  重点角色：{featured}\n"
            f"  场景节拍：{beats}\n"
            f"{focus_line}"
            f"  正文摘录：{excerpt}"
        )

    def _excerpt_text(self, text: str, max_chars: int = 220) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    def _excerpt_relevant_text(
        self,
        text: str,
        *,
        keywords: list[str],
        max_chars: int,
    ) -> str:
        normalized_keywords = self._normalize_prompt_focus_terms(keywords)
        if not normalized_keywords:
            return self._excerpt_text(text, max_chars=max_chars)
        units = self._split_text_units(text)
        if not units:
            return self._excerpt_text(text, max_chars=max_chars)
        scored_units: list[tuple[int, int]] = []
        for index, unit in enumerate(units):
            score = sum(unit.count(keyword) for keyword in normalized_keywords)
            if score <= 0:
                continue
            scored_units.append((index, score))
        if not scored_units:
            return self._excerpt_text(text, max_chars=max_chars)
        ranked = sorted(scored_units, key=lambda item: (-item[1], item[0]))
        selected_indices: set[int] = set()
        for index, _score in ranked[:4]:
            selected_indices.add(index)
            if len(selected_indices) < 6 and index > 0:
                selected_indices.add(index - 1)
            if len(selected_indices) < 6 and index + 1 < len(units):
                selected_indices.add(index + 1)
            if len(selected_indices) >= 6:
                break
        excerpt = " ".join(units[index] for index in sorted(selected_indices)).strip()
        return self._excerpt_text(excerpt or text, max_chars=max_chars)

    def _build_scene_prompt_focus_terms(
        self,
        *,
        scene_payload: dict[str, object],
        chunk_payload: dict[str, object] | None = None,
    ) -> list[str]:
        scene_bible = scene_payload.get("scene_bible", {}) or {}
        raw_terms: list[str] = [
            str(scene_payload.get("title", "") or ""),
            str(scene_payload.get("summary", "") or ""),
            str(scene_payload.get("scene_anchor", "") or ""),
            str(scene_bible.get("location", "") or ""),
            str(scene_bible.get("time_window", "") or ""),
            str(scene_bible.get("weather", "") or ""),
            str(scene_bible.get("lighting", "") or ""),
        ]
        raw_terms.extend(str(item) for item in scene_payload.get("involved_characters", []) or [])
        raw_terms.extend(str(item) for item in scene_bible.get("background_anchors", []) or [])
        raw_terms.extend(str(item) for item in scene_bible.get("fixed_props", []) or [])
        if chunk_payload:
            raw_terms.extend(
                [
                    str(chunk_payload.get("title", "") or ""),
                    str(chunk_payload.get("summary", "") or ""),
                    str(chunk_payload.get("transition_goal", "") or ""),
                ]
            )
            raw_terms.extend(str(item) for item in chunk_payload.get("must_cover", []) or [])
        return self._normalize_prompt_focus_terms(raw_terms)[:8]

    def _normalize_prompt_focus_terms(self, raw_terms: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in raw_terms:
            text = re.sub(r"\s+", " ", str(raw or "")).strip()
            if not text:
                continue
            parts = re.split(r"[，,、；;。！？!?（）()《》“”\"'：:\-/]+", text)
            for part in parts:
                value = part.strip()
                if len(value) < 2 or value in normalized:
                    continue
                normalized.append(value)
        return normalized

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

    def _build_default_subsegment_narration(
        self,
        summary: str,
        segment_index: int,
        segment_count: int,
    ) -> str:
        return self._strip_internal_segment_markers(summary)

    def _build_character_sheet_prompt(
        self,
        name: str,
        role: str,
        gender: str,
        appearance: str,
        outfit: str,
        source_prompt: str,
    ) -> str:
        source_hint = source_prompt.strip()
        extra_hint = (
            f"补充人物描述：{source_hint}。"
            if source_hint
            else ""
        )
        return (
            "原创虚构角色白底三视图，单角色，非真人摄影，非写实照片，"
            "偏影视概念设定与动画电影角色设计，prompt 尽量简洁，只根据姓名和人物描述生成。"
            f"{self.CHARACTER_SHEET_LAYOUT_PROMPT}"
            f"画面唯一可见文字：{name}。"
            f"人物描述：{appearance}；{outfit}。"
            f"内部理解参考，不要写成画面文字：性别 {gender}；叙事身份 {role}。"
            "必须保持同一张脸、同一发型、同一服装、同一年龄感、同一身材比例，"
            "锁定肩宽、头身比、四肢比例和体脂观感，不要随机改设定。"
            "不要改成电影剧照、动态打斗、半身大头照、单独肖像、海报、全景环境图、复杂场景或设计信息板。"
            "不要因为镜头或姿势变化把角色画得更老、更幼、更胖、更瘦、更壮或更矮。"
            "只保留设定中明确出现的道具，不要额外添加盔甲、外骨骼、枪械、刀剑、奇幻饰品或科幻装备。"
            "禁止在画面中出现“男、女、主角、配角、身份、职业、年龄、性格、主色、材质”等文字标签。"
            f"{extra_hint}"
        )

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
        character_names: list[str],
        profile_map: dict[str, CharacterVisualProfile],
    ) -> str:
        locked_profiles: list[str] = []
        for name in character_names:
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
            "多人同屏时不得省略任何一个当前帧实际出镜角色，"
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
        sanitized_prompt = self._sanitize_image_prompt_text(prompt)
        scene_bible_context = self._scene_bible_prompt_context(segment.scene_bible)
        return (
            "原创虚构场景分镜，风格化概念插画，非真人摄影，"
            "优先展示环境、光线和镜头调度，避免近景人像特写，"
            "若 involved_characters 有 2 人或以上，则这些角色必须同时出镜，不要只画一个人，"
            "每个 involved_characters 都必须按对应参考设定图还原，"
            "若角色出镜，必须保持稳定年龄感、稳定体型、稳定肩宽、稳定四肢比例和稳定脸型轮廓，"
            f"{self._scene_baseline_lock_context(segment.scene_bible)}"
            f"{scene_bible_context}"
            f"{self._shot_state_prompt_context(segment.shot_state)}"
            f"{self.SCENE_NO_TEXT_PROMPT}"
            f"角色：{characters}，{character_lock}，{sanitized_prompt}"
        )

    def _build_scene_master_frame_prompt(self, scene: VideoScene) -> str:
        scene_master_baseline_lock = self._scene_master_baseline_lock_context(
            scene.scene_bible,
            scene.involved_characters,
        )
        scene_master_context = self._scene_master_frame_prompt_context(
            scene.scene_bible,
            scene.involved_characters,
        )
        return (
            "原创虚构场景母图，风格化概念插画，非真人摄影，"
            "这是同一 scene 所有片段共用的环境与空间基准图，不是具体分镜终稿。"
            "优先稳定锁定地点、时间、天气、光线、背景锚点、固定道具和空间布局，"
            "不要把它画成情绪过满、动作过强或表演瞬间过于具体的剧情镜头。"
            "尽量以环境和空间关系为主体，生成无角色的空场景板。"
            f"{scene_master_baseline_lock}"
            f"{scene_master_context}"
            f"{self.SCENE_MASTER_FRAME_NO_PEOPLE_PROMPT}"
            f"{self.SCENE_NO_TEXT_PROMPT}"
            "目标：生成稳定、可复用、可供后续首帧/中段/尾帧继续派生的场景母图。"
        )

    def _stylize_frame_prompt(
        self,
        prompt: str,
        frame_characters: list[str],
        frame_type: str,
        character_lock: str,
        scene_bible_context: str = "",
        shot_state_context: str = "",
        continuity_link_context: str = "",
    ) -> str:
        characters = "、".join(frame_characters) or "环境为主"
        sanitized_prompt = self._sanitize_image_prompt_text(prompt)
        return (
            f"{frame_type}，原创虚构电影分镜，风格化概念插画，非真人摄影，"
            f"当前帧出镜角色：{characters}，只画这一帧真正入镜的人物；若有双人或多人出镜要求则必须全部画出，且全部按对应参考设定图还原，{character_lock}，"
            f"保持场景连续性、稳定年龄感、稳定体型、稳定肩宽和稳定四肢比例，"
            f"{self._scene_baseline_lock_context_from_context(scene_bible_context)}"
            f"{scene_bible_context}"
            f"{shot_state_context}"
            f"{continuity_link_context}"
            f"{self.SCENE_NO_TEXT_PROMPT}"
            f"{sanitized_prompt}"
        )

    def _sanitize_image_prompt_text(self, prompt: str) -> str:
        sanitized = prompt.strip()
        if not sanitized:
            return sanitized

        # Remove explicit subtitle/onscreen text instructions from image prompts.
        sanitized = re.sub(
            r"(字幕|对白|台词|旁白|对话框|聊天气泡|文字写着|屏幕显示)\s*[：:]\s*[^，。；;]*",
            "角色正在说话或情绪推进",
            sanitized,
        )

        # Replace direct quoted speech with visual action instead of verbatim words.
        sanitized = re.sub(r"[“\"].{1,40}?[”\"]", "角色正在说话", sanitized)

        # Replace explicit "X说：..." patterns so the model focuses on mouth/action, not text.
        sanitized = re.sub(
            r"([\u4e00-\u9fffA-Za-z0-9_]{1,12})(?:轻声|低声|高声|小声|开口|忽然|缓缓)?说\s*[：:]\s*[^，。；;]*",
            r"\1正在说话",
            sanitized,
        )

        sanitized = re.sub(r"\s+", " ", sanitized).strip(" ，。；;")
        return sanitized

    def _scene_bible_prompt_context(self, scene_bible: object) -> str:
        line = self._scene_bible_prompt_line(scene_bible)
        if not line:
            return ""
        return f"场景圣经约束：{line}。"

    def _scene_baseline_lock_context(self, scene_bible: object) -> str:
        line = self._scene_baseline_prompt_line(scene_bible)
        if not line:
            return ""
        return (
            "场景基线锁定："
            f"{line}。后续关键帧与视频必须复用同一地点、时间、光线、主色、背景锚点、固定道具和空间透视，不要漂移成新场景。"
        )

    def _scene_master_baseline_lock_context(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        line = self._scene_master_baseline_prompt_line(scene_bible, involved_characters)
        if not line:
            return ""
        return (
            "场景基线锁定："
            f"{line}。后续关键帧与视频必须复用同一地点、时间、光线、主色、背景锚点、固定道具和空间透视，不要漂移成新场景。"
        )

    def _scene_baseline_lock_context_from_context(self, scene_bible_context: str) -> str:
        if not scene_bible_context:
            return ""
        return "场景基线必须优先服从 scene master frame 与当前 scene 的环境基线，不要自行替换背景、光线或固定道具。"

    def _scene_master_frame_prompt_context(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        line = self._scene_master_frame_prompt_line(scene_bible, involved_characters)
        if not line:
            return ""
        return f"空场景环境约束：{line}。"

    def _shot_state_prompt_context(self, shot_state: object) -> str:
        line = self._shot_state_prompt_line(shot_state)
        if not line:
            return ""
        return f"镜头状态约束：{line}。"

    def _continuity_link_prompt_context(self, continuity_link: object) -> str:
        line = self._continuity_link_prompt_line(continuity_link)
        if not line:
            return ""
        return f"连续性承接约束：{line}。"

    def _scene_bible_prompt_line(self, scene_bible: object) -> str:
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", self._scene_bible_value(scene_bible, "spatial_layout")),
            ("角色调度", self._scene_bible_value(scene_bible, "character_blocking")),
            ("连续性说明", self._scene_bible_value(scene_bible, "continuity_notes")),
        ):
            normalized = str(value or "").strip()
            if normalized:
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_list(scene_bible, "fixed_props")),
        ):
            normalized_values = [str(item).strip() for item in values or [] if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

        return "；".join(parts)

    def _scene_master_frame_prompt_line(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", self._scene_bible_value(scene_bible, "spatial_layout")),
        ):
            normalized = str(value or "").strip()
            if normalized and not self._contains_scene_master_human_signal(
                normalized,
                involved_characters,
            ):
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_list(scene_bible, "fixed_props")),
        ):
            filtered_values = [
                item
                for item in values
                if not self._contains_scene_master_human_signal(item, involved_characters)
            ]
            normalized_values = [str(item).strip() for item in filtered_values if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

        return "；".join(parts)

    def _scene_baseline_prompt_line(self, scene_bible: object) -> str:
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", self._scene_bible_value(scene_bible, "spatial_layout")),
        ):
            normalized = str(value or "").strip()
            if normalized:
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_list(scene_bible, "fixed_props")),
        ):
            normalized_values = [str(item).strip() for item in values or [] if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

        return "；".join(parts)

    def _scene_master_baseline_prompt_line(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", self._scene_bible_value(scene_bible, "spatial_layout")),
        ):
            normalized = str(value or "").strip()
            if normalized and not self._contains_scene_master_human_signal(
                normalized,
                involved_characters,
            ):
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_list(scene_bible, "fixed_props")),
        ):
            filtered_values = [
                item
                for item in values
                if not self._contains_scene_master_human_signal(item, involved_characters)
            ]
            normalized_values = [str(item).strip() for item in filtered_values if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

        return "；".join(parts)

    def _shot_state_prompt_line(self, shot_state: object) -> str:
        parts: list[str] = []
        for label, value in (
            ("景别", self._shot_state_value(shot_state, "framing")),
            ("镜头运动", self._shot_state_value(shot_state, "camera_motion")),
            ("调度", self._shot_state_value(shot_state, "blocking")),
            ("动作推进", self._shot_state_value(shot_state, "action_progression")),
            ("情绪推进", self._shot_state_value(shot_state, "emotion_progression")),
            ("道具连续性", self._shot_state_value(shot_state, "prop_continuity")),
            ("方向", self._shot_state_value(shot_state, "screen_direction")),
            ("尾部承接", self._shot_state_value(shot_state, "end_state_lock")),
        ):
            normalized = str(value or "").strip()
            if normalized:
                parts.append(f"{label}：{normalized}")
        return "；".join(parts)

    def _continuity_link_prompt_line(self, continuity_link: object) -> str:
        parts: list[str] = []
        for label, value in (
            ("上一段", self._continuity_link_value(continuity_link, "previous_segment_id")),
            ("模式", self._continuity_link_value(continuity_link, "transition_mode")),
            ("开场匹配", self._continuity_link_value(continuity_link, "opening_match")),
            ("允许变化", self._continuity_link_value(continuity_link, "allowed_changes")),
            ("原因", self._continuity_link_value(continuity_link, "transition_reason")),
        ):
            normalized = str(value or "").strip()
            if normalized:
                parts.append(f"{label}：{normalized}")
        carry_over_elements = self._continuity_link_list(continuity_link, "carry_over_elements")
        if carry_over_elements:
            parts.append(f"延续元素：{'、'.join(carry_over_elements[:4])}")
        return "；".join(parts)

    def _scene_bible_value(self, scene_bible: object, key: str) -> str:
        if isinstance(scene_bible, dict):
            return str(scene_bible.get(key, "") or "")
        return str(getattr(scene_bible, key, "") or "")

    def _scene_bible_list(self, scene_bible: object, key: str) -> list[str]:
        if isinstance(scene_bible, dict):
            raw = scene_bible.get(key, [])
        else:
            raw = getattr(scene_bible, key, [])
        return [str(item).strip() for item in raw or [] if str(item).strip()]

    def _contains_involved_character_name(
        self,
        text: str,
        involved_characters: list[str],
    ) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        return any(name and name in normalized for name in involved_characters)

    def _contains_scene_master_human_signal(
        self,
        text: str,
        involved_characters: list[str],
    ) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        if self._contains_involved_character_name(normalized, involved_characters):
            return True
        return any(
            token in normalized
            for token in (
                "人物",
                "角色",
                "学生",
                "老师",
                "同学",
                "男生",
                "女生",
                "乘客",
                "路人",
                "行人",
                "监考",
                "巡视",
                "男主",
                "女主",
                "主角",
                "配角",
                "人影",
                "背影",
                "站位",
                "走位",
                "站在",
                "坐在",
                "走近",
                "走向",
                "走进",
                "对视",
                "靠近",
                "等待",
                "追逐",
                "奔跑",
                "拥抱",
                "回头",
                "低头",
                "抬眼",
                "伏在",
                "说话",
                "表情",
                "情绪",
            )
        )

    def _shot_state_value(self, shot_state: object, key: str) -> str:
        if isinstance(shot_state, dict):
            return str(shot_state.get(key, "") or "")
        return str(getattr(shot_state, key, "") or "")

    def _continuity_link_value(self, continuity_link: object, key: str) -> str:
        if isinstance(continuity_link, dict):
            return str(continuity_link.get(key, "") or "")
        return str(getattr(continuity_link, key, "") or "")

    def _continuity_link_list(self, continuity_link: object, key: str) -> list[str]:
        if isinstance(continuity_link, dict):
            raw = continuity_link.get(key, [])
        else:
            raw = getattr(continuity_link, key, [])
        return [str(item).strip() for item in raw or [] if str(item).strip()]

    def _build_seedance_clip_prompt(self, segment: VideoSegment) -> str:
        speech_budget = segment.duration_seconds * self.SPEECH_CHARS_PER_SECOND
        lines = [
            "请生成带原生音频的中文剧情短视频片段。",
            f"片段标题：{segment.title}",
            f"时长：{segment.duration_seconds} 秒。",
            f"语速预算：中文口播总量控制在约 {speech_budget} 字以内，所有对白和旁白必须在片尾前自然说完。",
            f"角色：{'、'.join(segment.involved_characters) or '环境为主'}。",
            f"场景圣经：{self._scene_bible_prompt_line(segment.scene_bible)}",
            f"镜头状态：{self._shot_state_prompt_line(segment.shot_state)}",
            f"连续性承接：{self._continuity_link_prompt_line(segment.continuity_link)}",
            f"画面主提示：{segment.scene_prompt}",
            f"旁白：{segment.narration}",
        ]
        if segment.requires_mid_frame and segment.mid_frame_prompt.strip():
            lines.append(f"中段锚点：{segment.mid_frame_prompt}")
            lines.append("镜头推进必须从首帧自然过渡到中段锚点，再收束到尾帧。")
        if len(segment.involved_characters) >= 2:
            lines.append(
                "多人同框要求：所有 involved_characters 在关键镜头中都必须保持身份清晰、体型稳定和关系正确，不要少人、换人或把其中一人弱化成背景路人。"
            )
        if segment.dialogue_lines:
            lines.append("角色对白：")
            lines.extend(f"- {line}" for line in segment.dialogue_lines)
        else:
            lines.append("角色对白：")
            lines.append("- 本段无角色对白，只保留旁白、环境音和镜头动作。")
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
            lines.append("硬字幕必须与实际口播同步出现，不要提前打印尚未说出口的文字。")
            lines.append("如果时长不足，优先压缩停顿和删减非字幕口播，不要截断对白或字幕。")
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
        return subtitle_lines[:3]
