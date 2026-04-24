from __future__ import annotations

import json
import re

from storyforge.core.io import to_jsonable
from storyforge.domains.novel.contracts import CharacterVoiceProfile, NovelPackage
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    StoryMemoryPackage,
    VideoScene,
    VideoSegment,
)


class VideoPromptingMixin:
    CHAPTER_SCENE_PLANNER_EXCERPT_CHARS = 620
    SCENE_CHUNK_PLANNER_EXCERPT_CHARS = 300
    SCENE_SEGMENT_CHUNK_CONTRACT_EXCERPT_CHARS = 240
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
    FRAME_PURE_IMAGE_PROMPT = "纯画面，不要文字、字幕、水印或 Logo。"
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
    CHARACTER_STYLE_OVERRIDE_PATTERNS = (
        re.compile(
            r"(?:身穿|穿着|穿了|穿)[^，。；;]{0,24}"
            r"(?:T恤|衬衫|外套|风衣|西装|毛衣|夹克|卫衣|校服|学士服|连衣裙|短裙|长裙|裙子|裤子|牛仔裤|短裤|鞋|球鞋|帆布鞋|高跟鞋)"
        ),
        re.compile(
            r"(?:头发|发型|马尾|高马尾|低马尾|双马尾|短发|长发|卷发|直发|刘海|盘发|发髻|丸子头|披肩发)[^，。；;]{0,18}"
        ),
        re.compile(
            r"(?:扎着|扎成|梳着|披着|留着|挽着|盘着|束着)[^，。；;]{0,18}"
            r"(?:头发|马尾|短发|长发|刘海|发髻|盘发|丸子头)"
        ),
    )
    TRANSIENT_FIXED_PROP_PATTERNS = (
        re.compile(r"(?:手机|电话|对讲机|耳机|平板|笔记本电脑)"),
        re.compile(r"(?:书包|背包|双肩包|挎包|手提包|行李箱)"),
        re.compile(r"(?:雨伞|阳伞)"),
        re.compile(r"(?:花束|鲜花|信封|礼盒|礼物盒|戒指盒)"),
        re.compile(r"(?:奶茶|咖啡|饮料|水杯|保温杯)"),
    )
    PROP_SOUND_EFFECT_PATTERN = re.compile(r"(?P<prop>[^，。；;:：]{1,16})相关细节声")
    ENVIRONMENT_PROP_ANCHOR_TOKENS = (
        "桌",
        "台",
        "架",
        "柜",
        "墙",
        "栏",
        "长椅",
        "座位",
        "地面",
        "地上",
        "门口",
        "窗边",
        "书架",
        "柜台",
        "课桌",
        "讲台",
        "石凳",
        "栈道边",
    )
    SCENE_MASTER_SPATIAL_RELATION_TOKENS = (
        "前景",
        "后景",
        "左侧",
        "右侧",
        "左前方",
        "右前方",
        "左后方",
        "右后方",
        "中央",
        "中心",
        "入口",
        "门口",
        "尽头",
        "深处",
        "边缘",
        "相距",
        "延伸",
        "连接",
        "通向",
        "通往",
        "正对",
        "对岸",
        "对面",
        "靠湖",
        "靠墙",
        "靠窗",
        "贴墙",
        "临湖",
    )
    SCENE_MASTER_SPATIAL_SUFFIXES = (
        "旁",
        "边",
        "下",
        "上",
        "前",
        "后",
        "里",
        "外",
    )
    SCENE_MASTER_SPATIAL_NOUN_HINT_PATTERN = re.compile(
        r"(?:路|径|道|桥|门|窗|墙|树|椅|架|湖|台|岸|楼|廊|轨|站|园|场|房|室|柱|栏|桌|石|亭|海|滩|林|河|车|花|馆|坡|梯|池|塔|牌|口)"
    )
    SCENE_MASTER_SPATIAL_DISTANCE_PATTERN = re.compile(
        r"[一二三四五六七八九十百0-9两半]+(?:米|步|尺|层|排)"
    )
    SCENE_MASTER_SPATIAL_HUMAN_STRIP_PATTERNS = (
        re.compile(
            r"(?:站在|站立|站定|坐在|坐于|坐下|等待|走近|靠近|走来|走向|走进|走到|迈步|跟上|回头|转身|抬头|低头|对视|面对面|并肩|停住|停下|开口|说话|对话|拥抱|亲吻|拥吻|接吻|看向|望向|入画|进入画面|出现在画面里)"
        ),
        re.compile(
            r"(?:先|后续|随后|再|继续|开始|正式|逐步|慢慢|缓缓|独自|单独|共同|一起|分别|仍然|依旧)"
        ),
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
        return json.dumps(
            to_jsonable(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _scene_bible_rule_block(self) -> str:
        return (
            "- `scene_bible` 只写可复用环境基线：地点、时间、天气、光线、主色、背景锚点、固定道具、空间布局、角色调度、连续性说明。\n"
            "- `scene_bible` 短写：`dominant_palette` 最多 3 个词，`background_anchors` 最多 4 项，`fixed_props` 最多 3 项，其余字段尽量 1 句。\n"
            "- `background_anchors`、`fixed_props` 只能写可见实体或布景元素；`fixed_props` 优先写场景内稳定存在的环境物，例如长椅、路灯、拱门、花墙、课桌，不要把手机、书包、雨伞、花束这类人物随身或临时动作道具写进去。\n"
            "- `scene_bible`、`shot_state`、`continuity_link` 和各帧 prompt 只能描述环境、镜头、站位、动作与承接；不得重新发明角色服装、发型、年龄感、体型或脸型。\n"
            "- 不要写对白、字幕或剧情分析。"
        )

    def _frame_character_rule_block(self) -> str:
        return (
            "- `involved_characters` 只包含当前段真正出镜或发声的角色；`dialogue_lines` 里出现的人也必须进入 `involved_characters`。`start_frame_characters`、`mid_frame_characters`、`end_frame_characters` 都必须是它的子集，且只写该帧真正出镜人物。\n"
            "- 如果首帧是单人等待、独白、回头或站立，不要把尚未出镜的人物写进首帧；尾帧同理。\n"
            "- `mid_frame_characters` 必须严格跟随片段中间那一拍真实出镜角色，不要直接照搬整个 scene cast，也不要把只在尾帧才出现的人物提前写进中段帧。\n"
            "- `mid_frame_mode` 只能取 `continuous` 或 `insert_cut`。\n"
            "- 二选一：如果首尾同组多人在中段仍是连续表演，就保留整组角色并写 `mid_frame_mode=continuous`；如果中段只切其中一人的反应或局部动作，才允许把 `mid_frame_characters` 缩成子集，并写 `mid_frame_mode=insert_cut`。\n"
            "- 只要用了 `insert_cut`，`timed_beats`、`mid_frame_prompt`、`shot_state.camera_motion` 就都必须明确写成“主镜头 -> 插入镜头 -> 主镜头”的往返运镜。\n"
            "- 非法反例：`start=[苏雨,林晨] / mid=[苏雨] / end=[苏雨,林晨] / mid_frame_mode=continuous`。\n"
            "- 若片段时长 >= 8 秒、对白 >= 2 句，或 `timed_beats` 有 3 拍及以上，`requires_mid_frame` 必须为 true，且必须显式给出 `mid_frame_characters`；若 `requires_mid_frame = false`，`mid_frame_characters` 必须为空数组。\n"
            "- 同一帧里同一角色只能出现一次；如果某一帧 `*_frame_characters` 有 2 人或以上，就不要在该帧 prompt、`framing` 或 `camera_motion` 里再写“某角色侧脸特写 / 大特写 / 单人近景”，避免把同一角色在单帧里重复画两次。\n"
            "- `shot_state.framing` 和 `shot_state.camera_motion` 是整个 segment 共享镜头，不是某一帧专属说明；先检查 `start_frame_characters / mid_frame_characters / end_frame_characters`，只要其中任一帧是双人或多人，就不要在这两个字段里写指向某一人的单独特写。\n"
            "- 非法示例：`start=[苏雨,林晨]`，却写 `shot_state.camera_motion=推向林晨侧脸特写`。\n"
            "- 合法示例：`shot_state.camera_motion=轻微前推，保持苏雨、林晨同框，只通过站位和表情差异突出林晨情绪变化`。"
        )

    def _segment_audio_budget_rule_block(self) -> str:
        return (
            f"- `duration_seconds` 必须在 {self.PLANNER_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒内，并按中文自然口播语速估算音频长度，约每秒 {self.SPEECH_CHARS_PER_SECOND} 个中文字。\n"
            "- 5 秒片段只能放极短句，总旁白 + 对白 + 硬字幕文案约 15 字以内；8 秒片段约 24 字以内；12 秒片段约 36 字以内。\n"
            "- 如果旁白、对白或硬字幕超过当前时长可说完的字数，必须拆成下一个片段，不得硬塞进同一段。\n"
            "- 动作容量预算也必须同时满足：5-6 秒片段最多只放 1-2 个可见推进点，8-12 秒片段最多只放 2-3 个。推进点指明确动作、对白轮次、关系变化或收束结果。\n"
            "- 如果一个 segment 同时塞了等待、会面、开口、回应、靠近、转身、停下等多个推进点，就必须拆段，不要把整条动作链硬压进单段。\n"
            "- `subtitle_lines` 只允许写本段真正会被听到的对白或旁白；纯动作段输出空数组，不要把动作说明直接写成硬字幕。\n"
            "- 每个 `segment` 都必须显式输出非空 `timed_beats`；即使是纯动作段也至少写 1 条，格式示例：`0-2秒：他停下脚步，看向湖面。`\n"
            "- 5-6 秒片段通常输出 1-2 条 `timed_beats`；8-12 秒片段通常输出 2-3 条。不要把整段压成一条 `0-10秒：两人继续交流` 这种泛描述。\n"
            "- 只要本段存在 `dialogue_lines` 或 `narration`，`timed_beats` 就必须把口播落到具体时间段里，直接写出谁在这一拍说了什么，不能只写“他开口”“她回应”。\n"
            "- 示例：不要写 `4-8秒：陈默终于告白。`；要写成 `4-8秒：陈默看着林晚说“我喜欢你很久了”。`\n"
            "- 如果本段有 2 句对白，就要让 `timed_beats` 明确这 2 句分别落在哪一拍；如果旁白和对白同时存在，也要写清哪一拍是旁白、哪一拍是谁开口。"
        )

    def _segment_continuity_rule_block(self) -> str:
        return (
            "- 相邻 segment 必须按真实顺序推进，不能重复上一拍动作，也不能提前写后续高潮或结果。\n"
            "- 同场景连续承接时，`transition_mode` 应为 `continue`，`opening_match` 要明确上一段尾部状态，`allowed_changes` 只写本段新增推进。\n"
            "- 起始段若使用 `transition_mode = start`，`opening_match` 也要简短写出本段开场已成立的站位、动作或环境状态，不要留空。\n"
            "- `opening_match` 必须写成可拍到的开场画面，不要写成“承接上一段继续”“场景开始”“继续推进”这类空话。\n"
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
            "- 如果 `must_cover + transition_goal` 已经包含 4 个及以上推进点，例如“试探开口 -> 正式告白 -> 明确回应 -> 关系落点”，就不要还写成 `expected_segment_count = 1`。\n"
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
        chapter_event_plan: object,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="chapter_scene",
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
        chapter_event_block = self._format_chapter_coverage_event_block(chapter_event_plan)
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
- 你必须完整覆盖“当前章必须覆盖的关键事件”；不得漏掉后半段事件，也不得在表白、和解、揭示等中途提前收束。
- 每个 `scene.covered_event_ids` 都必须填写，且只能使用下方关键事件列表里的 `event_id`。
- 所有 `covered_event_ids` 拼接后，必须与关键事件列表顺序完全一致；不能跳号、不能重复、不能乱序。
- 一个 scene 可以覆盖多个相邻关键事件，但只能覆盖连续事件块；不要把 `ev01` 和 `ev03` 放在同一 scene 却漏掉 `ev02`。
- 最后一个 scene 必须覆盖最后一个关键事件，也就是当前章节真正的收束动作、关系落点或结尾决定。
- `scene_id` 必须以 `{chapter_id_prefix}-sc` 开头，例如 `{chapter_id_prefix}-sc01`。
{self._scene_bible_rule_block()}
- 首个 scene 的 `scene_transition_contract` 保持空合同，不要伪造上一场承接。
- 从第二个 scene 开始，必须显式填写 `scene_transition_contract`，说明它如何从上一场进入当前场。
- `scene_transition_contract.transition_mode` 只能取 `direct_continue / adjacent_move / motivated_cut / hard_cut`。
- 如果不是 `hard_cut`，就必须写清：`previous_scene_id`、`previous_scene_exit_state`、`next_scene_entry_match`、`bridge_action`、`carry_over_elements`、`visual_bridge`。
- `next_scene_entry_match` 必须描述当前场第一段开头先建立的可拍状态；`bridge_action` 必须写上一场尾部如何过渡到当前场开头。
- `transition_focus_seconds` 通常只写 1-3 秒；不要把整场都写成过渡段。
- 如果发生明显地点切换、时间跳转、光线大变或叙事空间切换，就必须开新 scene。
- 不要把过多相邻关键事件一口气吞进同一个 scene；如果当前事件块已经明显形成“会面 -> 开口 -> 回应 -> 关系落点”这类多阶段链路，应优先拆成多个 scene，而不是把压力全部留给后面的 chunk planner。
- 如果正文是告白、对峙、争吵、审问、双人对话，`involved_characters` 必须同时包含双方。
- `summary`、`scene_anchor`、`scene_bible` 都尽量短写，避免长段散文。
- 不要输出 `segments`。
{self._structured_output_guardrail_line()}

上一章退出状态 JSON：
{previous_exit_json}

story memory JSON：
{memory_json}

当前章必须覆盖的关键事件：
{chapter_event_block}

当前章节拆分依据：
{chapter_block}
""".strip()

    def _build_chapter_event_coverage_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
    ) -> str:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        featured = "、".join(chapter_outline.featured_characters) or "无"
        chapter_id_prefix = f"ch{chapter_number:02d}"
        chapter_markdown = (draft.markdown if draft else chapter_outline.summary).strip()
        return f"""
请先从当前章节正文里抽取“后续场景规划必须覆盖”的关键事件。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章《{chapter_outline.title}》
- 角色原名白名单：{allowed_names}
- 重点角色：{featured}
- 章节目标：{chapter_outline.goal}
- 章节摘要：{chapter_outline.summary}
- 关键冲突：{chapter_outline.key_conflict}
- `event_id` 必须以 `{chapter_id_prefix}-ev` 开头，例如 `{chapter_id_prefix}-ev01`。
- 只提取“必须被 scene 覆盖”的关键推进事件：角色登场、关键对话落点、关系变化、动作结果、决定、章节结尾状态。
- 不要提取纯环境描写、重复心理描写、没有推动剧情的停顿、同义重复动作。
- 优先提取当前章节“当下正在发生”的正向表演事件；背景介绍、关系说明、人物履历、内心说明、回忆补叙如果只是解释上下文，不要单独抽成 must-cover event。
- 如果正文里出现“他们是在以前认识的”“从那以后”“他知道自己早就”这类背景 / 回忆 / 总结性补叙，通常应并入相邻 event 的背景，不要单独建 event，除非这一段在本章里被明确演成独立可视化场面。
- 普通 event 最多只保留 1-2 个紧密绑定的推进点；如果当前章节已经拆成多个 event，章节首尾 event 最多允许 3 个紧密绑定推进点。
- 如果一句里已经出现“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”这类多阶段动作链，就必须拆成多个相邻 event。
- 中间 event 尤其要保持窄：一轮问句、一次回答、一个动作结果或一个关系落点，通常只选其中 1-2 个；不要把“她走近看到花并发问 -> 他承认有话要说 -> 她继续追问”塞进同一个中间 event。
- 事件必须严格按正文顺序输出。
- `source_evidence` 必须直接摘取当前章节正文中的短词或短句，不要改写，不要编造。
- 每个 event 的 `source_evidence` 只保留当前 event 对应的 1-2 个相邻正文片段，不要把“等待 / 会面 / 开口 / 回应”这类跨多个 event 的证据拼到同一个 event 里。
- `involved_characters` 只能使用小说中已存在的角色原名，不得新增角色。
- 最后一条事件必须覆盖章节尾部真正的最后一个有效推进或关系落点，不能在中途提前结束。
- 如果章节结尾已经发生了回应、说出口、拥抱、亲吻、离开决定或关系明确变化，最后一条事件就必须覆盖到那里；不要停在“即将开口”“准备回应”“气氛升温”这种过早状态。
- 一章通常输出 3-8 个关键事件；短章可以更少，但不能漏掉章节尾部的重要落点。
{self._structured_output_guardrail_line()}

当前章节正文全文：
{chapter_markdown}
""".strip()

    def _format_chapter_coverage_event_block(self, chapter_event_plan: object) -> str:
        events = []
        if hasattr(chapter_event_plan, "events"):
            events = list(getattr(chapter_event_plan, "events") or [])
        elif isinstance(chapter_event_plan, dict):
            events = list(chapter_event_plan.get("events", []) or [])
        if not events:
            return "- 无"
        lines: list[str] = []
        for item in events:
            event_id = str(
                getattr(item, "event_id", "")
                if not isinstance(item, dict)
                else item.get("event_id", "")
            ).strip()
            summary = str(
                getattr(item, "summary", "")
                if not isinstance(item, dict)
                else item.get("summary", "")
            ).strip()
            evidence = (
                list(getattr(item, "source_evidence", []) or [])
                if not isinstance(item, dict)
                else list(item.get("source_evidence", []) or [])
            )
            evidence_line = " / ".join(str(token).strip() for token in evidence[:2] if str(token).strip())
            if evidence_line:
                lines.append(f"- {event_id}：{summary}；证据：{evidence_line}")
            else:
                lines.append(f"- {event_id}：{summary}")
        return "\n".join(lines)

    def _format_chapter_coverage_event_focus_block(
        self,
        chapter_event_plan: object,
        *,
        event_id: str,
    ) -> str:
        events = []
        if hasattr(chapter_event_plan, "events"):
            events = list(getattr(chapter_event_plan, "events") or [])
        elif isinstance(chapter_event_plan, dict):
            events = list(chapter_event_plan.get("events", []) or [])
        if not events or not event_id:
            return "- 无"
        normalized_events: list[dict[str, object]] = []
        for item in events:
            if isinstance(item, dict):
                normalized_events.append(item)
            else:
                normalized_events.append(
                    {
                        "event_id": getattr(item, "event_id", ""),
                        "summary": getattr(item, "summary", ""),
                        "source_evidence": list(getattr(item, "source_evidence", []) or []),
                    }
                )
        target_index = next(
            (
                index
                for index, item in enumerate(normalized_events)
                if str(item.get("event_id", "")).strip() == event_id
            ),
            -1,
        )
        if target_index < 0:
            return "- 无"
        start_index = max(0, target_index - 1)
        end_index = min(len(normalized_events), target_index + 2)
        lines: list[str] = []
        for index in range(start_index, end_index):
            item = normalized_events[index]
            label = "当前失败项" if index == target_index else "相邻项"
            summary = str(item.get("summary", "") or "").strip()
            evidence = " / ".join(
                str(token).strip()
                for token in list(item.get("source_evidence", []) or [])[:3]
                if str(token).strip()
            )
            line = f"- {label} {str(item.get('event_id', '')).strip()}：{summary}"
            if evidence:
                line += f"；证据：{evidence}"
            lines.append(line)
        return "\n".join(lines)

    def _format_scene_covered_event_summary_block(
        self,
        scene_payload: dict[str, object],
    ) -> str:
        summaries = [
            self._compact_story_memory_text(str(item or ""), limit=72)
            for item in list(scene_payload.get("covered_event_summaries", []) or [])
            if str(item or "").strip()
        ]
        if not summaries:
            return "- 无"
        return "\n".join(
            f"- 绑定事件 {index}：{summary}"
            for index, summary in enumerate(summaries, start=1)
        )

    def _build_chapter_event_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        invalid_plan: object,
        failure_message: str,
        offending_event_id: str = "",
    ) -> str:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        chapter_markdown = (draft.markdown if draft else chapter_outline.summary).strip()
        invalid_plan_json = self._prompt_json(
            invalid_plan.model_dump() if hasattr(invalid_plan, "model_dump") else invalid_plan
        )
        event_block = self._format_chapter_coverage_event_block(invalid_plan)
        focus_block = self._format_chapter_coverage_event_focus_block(
            invalid_plan,
            event_id=offending_event_id,
        )
        offending_note = (
            f"- 当前主要出错 event：`{offending_event_id}`。\n"
            if offending_event_id
            else ""
        )
        return f"""
请修复这份失败的章节关键事件规划，只输出修复后的完整 `ChapterCoveragePlanSchema`。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章《{chapter_outline.title}》
- 失败原因：{failure_message}
{offending_note}- 优先保留已经合理的 event 顺序，只改坏掉的 event；如果需要拆分或删除，最终 `event_id` 仍必须从 `ch{chapter_number:02d}-ev01` 连续编号。
- 如果已经点名某个出错 event，就优先只修这个 event 及其后续编号；前面已合理的 event 尽量不要改写。
- 背景介绍、关系说明、人物履历、回忆补叙如果只是解释上下文，不要单独保留为 must-cover event。
- 中间 event 必须更窄：一轮问句、一次回答、一个动作结果或一个关系落点，通常只选其中 1-2 个，不要把三连推进塞进一条。
- 多 event 章节的首尾 event 最多允许 3 个紧密绑定推进点；中间 event 最多允许 2 个。
- 如果当前失败项仍然至少有 3 个推进点，而它又不是章节首尾 event，就必须把它拆成两个连续 event，并把后续 event_id 顺延。
- `source_evidence` 只保留当前 event 对应的 1-2 个相邻正文短句，不要跨 event 拼接。
- 只修事件规划，不要生成 scene、segment、图片 prompt 或解释说明。
{self._structured_output_guardrail_line()}

当前失败项邻域：
{focus_block}

当前失败的事件清单：
{event_block}

当前失败的原始 JSON：
{invalid_plan_json}

当前章节正文全文：
{chapter_markdown}
""".strip()

    def _build_chapter_event_split_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        invalid_plan: object,
        offending_event_id: str,
        failure_message: str,
    ) -> str:
        chapter_outline = next(
            item for item in novel_package.outline.chapters if item.number == chapter_number
        )
        draft = next(
            (item for item in novel_package.chapters if item.number == chapter_number),
            None,
        )
        chapter_markdown = (draft.markdown if draft else chapter_outline.summary).strip()
        invalid_plan_json = self._prompt_json(
            invalid_plan.model_dump() if hasattr(invalid_plan, "model_dump") else invalid_plan
        )
        focus_block = self._format_chapter_coverage_event_focus_block(
            invalid_plan,
            event_id=offending_event_id,
        )
        target_event_payload = None
        raw_events = []
        if hasattr(invalid_plan, "events"):
            raw_events = list(getattr(invalid_plan, "events") or [])
        elif isinstance(invalid_plan, dict):
            raw_events = list(invalid_plan.get("events", []) or [])
        for item in raw_events:
            event_id = (
                str(item.get("event_id", "") or "").strip()
                if isinstance(item, dict)
                else str(getattr(item, "event_id", "") or "").strip()
            )
            if event_id != offending_event_id:
                continue
            if isinstance(item, dict):
                target_event_payload = item
            else:
                target_event_payload = {
                    "event_id": event_id,
                    "summary": str(getattr(item, "summary", "") or ""),
                    "source_evidence": list(getattr(item, "source_evidence", []) or []),
                    "involved_characters": list(getattr(item, "involved_characters", []) or []),
                }
            break
        target_event_json = self._prompt_json(target_event_payload or {})
        return f"""
请只拆分一个失败的章节关键事件，只输出 `ChapterCoverageEventSplitPlanSchema`。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章《{chapter_outline.title}》
- 当前失败事件：`{offending_event_id}`
- 失败原因：{failure_message}
- 你的任务不是重写整章 event plan，而是只把这个过粗 event 拆成 2-4 个更细、相邻、按正文顺序排列的 replacement events。
- 每个 replacement event 只覆盖当前粗事件里的一小拍推进，不要把相邻 event 的内容提前吞进来，也不要补写后续 scene、segment、图片 prompt。
- 普通 replacement event 最多只保留 1-2 个紧密绑定推进点；如果它本身是章节开头或章节结尾的局部收束，可以稍宽，但仍不能再塞 4 个推进点。
- 一轮问句、一次回答、一个动作结果、一次关系落点，通常应拆成不同 replacement event，不要继续三连合并。
- `source_evidence` 只保留当前 replacement event 对应的 1-2 个相邻正文短句，不要跨 replacement event 拼接。
- `involved_characters` 只能使用小说正文已有角色原名。
- 不要输出 `event_id`，最终连续编号由系统回填。
{self._structured_output_guardrail_line()}

当前失败项邻域：
{focus_block}

当前失败 event JSON：
{target_event_json}

整份失败 plan JSON：
{invalid_plan_json}

当前章节正文全文：
{chapter_markdown}
""".strip()

    def _format_scene_chunk_plan_block(self, chunk_plan: object) -> str:
        chunks = []
        if hasattr(chunk_plan, "chunks"):
            chunks = list(getattr(chunk_plan, "chunks") or [])
        elif isinstance(chunk_plan, dict):
            chunks = list(chunk_plan.get("chunks", []) or [])
        if not chunks:
            return "- 无"
        lines: list[str] = []
        for item in chunks:
            payload = (
                item if isinstance(item, dict) else {
                    "chunk_id": getattr(item, "chunk_id", ""),
                    "title": getattr(item, "title", ""),
                    "summary": getattr(item, "summary", ""),
                    "must_cover": list(getattr(item, "must_cover", []) or []),
                    "transition_goal": getattr(item, "transition_goal", ""),
                    "expected_segment_count": getattr(item, "expected_segment_count", 0),
                }
            )
            chunk_id = str(payload.get("chunk_id", "") or "").strip()
            title = str(payload.get("title", "") or "").strip()
            summary = str(payload.get("summary", "") or "").strip()
            must_cover = " / ".join(
                str(token).strip()
                for token in list(payload.get("must_cover", []) or [])[:3]
                if str(token).strip()
            )
            transition_goal = str(payload.get("transition_goal", "") or "").strip()
            expected_segment_count = int(payload.get("expected_segment_count", 0) or 0)
            line = f"- {chunk_id}：{title}；summary：{summary}"
            if must_cover:
                line += f"；must_cover：{must_cover}"
            if transition_goal:
                line += f"；transition_goal：{transition_goal}"
            if expected_segment_count:
                line += f"；expected_segment_count：{expected_segment_count}"
            lines.append(line)
        return "\n".join(lines)

    def _format_scene_chunk_focus_block(
        self,
        chunk_plan: object,
        *,
        chunk_id: str,
    ) -> str:
        chunks = []
        if hasattr(chunk_plan, "chunks"):
            chunks = list(getattr(chunk_plan, "chunks") or [])
        elif isinstance(chunk_plan, dict):
            chunks = list(chunk_plan.get("chunks", []) or [])
        if not chunks or not chunk_id:
            return "- 无"
        normalized_chunks: list[dict[str, object]] = []
        for item in chunks:
            if isinstance(item, dict):
                normalized_chunks.append(item)
            else:
                normalized_chunks.append(
                    {
                        "chunk_id": getattr(item, "chunk_id", ""),
                        "title": getattr(item, "title", ""),
                        "summary": getattr(item, "summary", ""),
                        "must_cover": list(getattr(item, "must_cover", []) or []),
                        "transition_goal": getattr(item, "transition_goal", ""),
                        "expected_segment_count": getattr(item, "expected_segment_count", 0),
                    }
                )
        target_index = next(
            (
                index
                for index, item in enumerate(normalized_chunks)
                if str(item.get("chunk_id", "")).strip() == chunk_id
            ),
            -1,
        )
        if target_index < 0:
            return "- 无"
        start_index = max(0, target_index - 1)
        end_index = min(len(normalized_chunks), target_index + 2)
        lines: list[str] = []
        for index in range(start_index, end_index):
            item = normalized_chunks[index]
            label = "当前失败项" if index == target_index else "相邻项"
            must_cover = " / ".join(
                str(token).strip()
                for token in list(item.get("must_cover", []) or [])[:3]
                if str(token).strip()
            )
            transition_goal = str(item.get("transition_goal", "") or "").strip()
            line = (
                f"- {label} {str(item.get('chunk_id', '')).strip()}："
                f"{str(item.get('summary', '') or '').strip()}"
            )
            if must_cover:
                line += f"；must_cover：{must_cover}"
            if transition_goal:
                line += f"；transition_goal：{transition_goal}"
            lines.append(line)
        return "\n".join(lines)

    def _build_scene_chunk_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
        invalid_plan: object,
        failure_message: str,
        offending_chunk_id: str = "",
        required_segment_count: int | None = None,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        focus_terms = self._build_scene_focus_terms(scene_payload=scene_payload)
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="scene_chunk",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_CHUNK_PLANNER_EXCERPT_CHARS,
            focus_terms=focus_terms,
            compact=True,
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        memory_json = self._prompt_json(memory_context)
        invalid_plan_json = self._prompt_json(
            invalid_plan.model_dump() if hasattr(invalid_plan, "model_dump") else invalid_plan
        )
        chunk_block = self._format_scene_chunk_plan_block(invalid_plan)
        focus_block = self._format_scene_chunk_focus_block(
            invalid_plan,
            chunk_id=offending_chunk_id,
        )
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        covered_event_summary_block = self._format_scene_covered_event_summary_block(scene_payload)
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        transition_rule = ""
        if str(scene_transition_contract.get("previous_scene_id", "") or "").strip():
            transition_rule = (
                "- 如果失败项是首个 chunk，修复后仍必须消费 `scene_transition_contract`，"
                "先承接上一场尾部，再 reveal 当前 scene 的新环境，不要把首段改成断开的重新开场。\n"
            )
        segment_count_rule = (
            f"- 当前失败项如果继续保留为单个 chunk，`expected_segment_count` 至少要改成 {required_segment_count}。\n"
            if required_segment_count and required_segment_count > 1
            else ""
        )
        offending_note = (
            f"- 当前主要出错 chunk：`{offending_chunk_id}`。\n"
            if offending_chunk_id
            else ""
        )
        return f"""
请修复这份失败的 scene chunk 规划，只输出修复后的完整 `SceneSegmentChunkPlanSchema`。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 失败原因：{failure_message}
{offending_note}- 优先保留已经合理的 chunk 顺序，只改坏掉的 chunk；如果需要拆分，最终 `chunk_id` 仍应保持顺序清晰。
- 一个 chunk 只能承担一个连续事件目标，不要把“等待 -> 走近 -> 发问 -> 回答”这种 4 个推进点继续塞在同一个 chunk。
- 修复后仍然只能覆盖当前 scene 已绑定的事件内容，不得提前写出后续 scene 的回应、告白结果、亲密动作或关系落点。
- 当前 scene 允许覆盖的事件内容：
{covered_event_summary_block}
{segment_count_rule}- 如果当前失败项已经包含 4 个及以上推进点，你只能二选一：
  1. 保留这个 chunk，但把 `expected_segment_count` 提高到足够值；
  2. 把它拆成两个连续 chunk，让每个 chunk 只承担更窄的一段推进。
- `must_cover` 只写 1-3 条短句，`transition_goal` 只写一句短话，避免长摘要散文。
- 不要把背景说明或整场 scene 摘要重复抄进每个 chunk。
{transition_rule}{self._chunk_split_rule_block()}
{self._anti_micro_split_rule_block()}
{self._structured_output_guardrail_line()}

story memory JSON：
{memory_json}

目标 scene JSON：
{scene_json}

当前失败项邻域：
{focus_block}

当前失败的 chunk 清单：
{chunk_block}

当前失败的原始 JSON：
{invalid_plan_json}

当前章节参考：
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
        focus_terms = self._build_scene_focus_terms(
            scene_payload=scene_payload,
            chunk_payload=chunk_payload,
        )
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="segment_contract",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_SEGMENT_CHUNK_CONTRACT_EXCERPT_CHARS,
            focus_terms=focus_terms,
            compact=True,
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        chunk_json = self._prompt_json(self._build_prompt_chunk_payload(chunk_payload or {}))
        memory_json = self._prompt_json(memory_context)
        has_previous_chunk_exit_state = bool(previous_chunk_exit_state)
        previous_chunk_exit_json = self._prompt_json(previous_chunk_exit_state or {})
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        scene_transition_previous_id = str(scene_transition_contract.get("previous_scene_id", "") or "").strip()
        chunk_order_index = int((chunk_payload or {}).get("order_index", 0) or 0)
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
        cross_chunk_opening_rule = ""
        previous_chunk_exit_block = ""
        if has_previous_chunk_exit_state:
            cross_chunk_opening_rule = (
                "- 若有上一 chunk 退出状态，首段必须直接承接其中的 "
                "`visible_tail_state` / `opening_match_seed`，"
                "复现上一段已成立的站位、朝向、道具或动作停点。\n"
                "- 首段 `continuity_link.opening_match` 建议写成："
                "`承接上一 chunk 尾部，角色A仍...，角色B继续...`；"
                "不要只写“继续推进”“承接上一段尾部”。\n"
            )
            previous_chunk_exit_block = f"""

上一 chunk 退出状态 JSON：
{previous_chunk_exit_json}
""".rstrip()
        scene_transition_rule = ""
        if chunk_order_index == 1 and scene_transition_previous_id:
            scene_transition_rule = (
                "- 当前是本 scene 的首个 chunk，必须消费 `scene_transition_contract`，不要把自己写成完全重新开场。\n"
                "- 首个 segment 的 `continuity_link.opening_match` 要先长成 `next_scene_entry_match` 指定的开场状态。\n"
                "- 第一条或前两条 `timed_beats` 必须包含 `bridge_action`，先承接上一场尾部，再 reveal 当前场环境。\n"
                "- 需要跨 scene 保持的 `carry_over_elements`、朝向或轴线，必须反映到 `opening_match`、`shot_state.blocking`、`shot_state.screen_direction`。\n"
                "- 即使当前 scene 的首段 `transition_mode` 仍是 `start`，也允许在 `opening_match` 里明确写出“承接上一场尾部”的可拍状态；不要因为新 scene 就把承接链断掉。\n"
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
- 如果当前 chunk 是告白、回应、双人对话或情绪对峙，优先生成较少但更完整的 8-12 秒 segment，不要把一句话拆成多个 5-6 秒微段。
- 不要把“准备开口”和“真正开口”拆成两个近义连续片段，除非单段字数预算已经超限。
- 如果当前 chunk 的 `must_cover` 或 `transition_goal` 已经要求说出口、回应、靠近、牵手、拥抱、亲吻或离开决定，最后一个 segment 必须真正落到这个结果，不要只停在“准备做”。
- 最后一个 segment 的最后一条 `timed_beats` 与 `shot_state.end_state_lock` 必须写成这个结果已经发生，不要再写成“准备回应 / 即将开口 / 停在亲吻前的一刻”。
- `narration` 只有在本段确实存在独立旁白、心声或画外音时才填写；如果本段已经有 `dialogue_lines`，不要再用 `narration` 复述动作、关系或对白内容。
- 不要把 `summary`、动作描述或 `timed_beats` 再抄进 `narration` / `subtitle_lines`。
- 不要输出 `start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- `segment_id` 只需在当前 chunk 内唯一，系统后续会统一重编；建议仍使用 `{scene_id}-seg01` 这类短格式。
- 每个 `segment` 都必须带 `timed_beats`，不能为空；如果任何一段漏掉 `timed_beats`，整批合同都会判失败并重试。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`、`当前为第2/2段`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{cross_chunk_opening_rule.rstrip()}
{scene_transition_rule.rstrip()}
- 有对白时，`timed_beats` 必须明确写出哪一秒谁说了哪句；不要只写“她温柔回应”“他说出告白”这类抽象概括。
- `shot_state` 只写镜头、调度、动作、道具和承接状态，尽量 1 句完成，不要写成长段散文。
{self._segment_field_concision_rule_block()}
{self._structured_output_guardrail_line()}

story memory JSON：
{memory_json}
{previous_chunk_exit_block}

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
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="repair",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        chunk_json = self._prompt_json(self._build_prompt_chunk_payload(chunk_payload or {}))
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
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        chunk_order_index = int((chunk_payload or {}).get("order_index", 0) or 0)
        scene_transition_rule = ""
        if chunk_order_index == 1 and str(
            scene_transition_contract.get("previous_scene_id", "") or ""
        ).strip():
            scene_transition_rule = (
                "- 当前 chunk 是本 scene 的首段承接段；修复超长对白时，不得删掉 `scene_transition_contract` 已要求的开场承接。\n"
                "- 首个修复后 segment 仍必须保留 `next_scene_entry_match` 与 `bridge_action`，不要把跨 scene 过渡修掉成普通重新开场。\n"
            )
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
- 不要输出 `start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{scene_transition_rule.rstrip()}
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
        """.strip()

    def _build_scene_segment_timeline_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
        chunk_payload: dict[str, object] | None = None,
        previous_chunk_exit_state: dict[str, object] | None = None,
        failed_contract_payload: dict[str, object],
        failure_message: str,
        offending_segment_id: str,
        max_end_seconds: float | None,
        duration_seconds: float | None,
        uncovered_seconds: float | None,
        max_segments_override: int,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="repair",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        chunk_json = self._prompt_json(self._build_prompt_chunk_payload(chunk_payload or {}))
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
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        chunk_order_index = int((chunk_payload or {}).get("order_index", 0) or 0)
        scene_transition_rule = ""
        if chunk_order_index == 1 and str(
            scene_transition_contract.get("previous_scene_id", "") or ""
        ).strip():
            scene_transition_rule = (
                "- 当前 chunk 是本 scene 的首段承接段；修复尾部 beat 时，不得删掉 `scene_transition_contract` 已要求的开场承接。\n"
                "- 首个修复后 segment 仍必须保留 `next_scene_entry_match` 与 `bridge_action`，不要把跨 scene 过渡修掉成普通重新开场。\n"
            )
        timeline_rule = ""
        if offending_segment_id and max_end_seconds is not None and duration_seconds is not None and uncovered_seconds is not None:
            timeline_rule = (
                f"- 上一轮失败的片段是 `{offending_segment_id}`。\n"
                f"- 该段 `timed_beats` 最后一拍只写到 {max_end_seconds:g} 秒，但片段时长是 {duration_seconds:g} 秒，"
                f"尾部仍有约 {uncovered_seconds:g} 秒没有合同约束。\n"
                "- 本次必须把最后一条 beat 延长到接近片尾，或新增 1 条尾部收束 beat，"
                "明确写出最后几秒真正可见的反应、停顿、走位收束或镜头停点。\n"
            )
        elif offending_segment_id:
            timeline_rule = (
                f"- 上一轮失败的片段是 `{offending_segment_id}`，本次只优先修它的 `timed_beats` 时间覆盖。\n"
            )
        return f"""
你是 StoryForge 的时序节拍修复 Agent。
你收到的是同一个 chunk 上一轮失败的完整合同。不要从零重写剧情；请基于失败合同做最小必要改写，重点修复 `timed_beats` 的时间覆盖。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次必须返回当前 chunk 的完整 `segments` 列表，不是 patch，不是 diff。
- 所有 `segment.chapter_number` 必须是 {chapter_number}；所有 `segment.scene_id` 必须是 `{scene_id}`。
- 当前 chunk 最多只能输出 {max_segments_override} 个 segment；优先保持上一轮已经合理的段数与顺序。
- 优先保留已经合理的 `title / summary / dialogue_lines / subtitle_lines / continuity_link / shot_state`，只修改必要字段。
- 所有 `segment` 仍必须保留非空 `timed_beats`，并覆盖该段完整时长。
{timeline_rule}- 如果只是尾部少了 1-3 秒，不要为了补 beat 新造剧情结果；优先补反应、停顿、目光、呼吸、手部动作、站位收束或镜头停点，让尾部真正落到当前段已经成立的结果。
- 不得回放当前 chunk 之前已经发生的事件，也不得提前写入当前 chunk 之后的剧情结果。
- 不得为了补尾部 beat 而重复前面已经发生过的同一句动作描述；新增 beat 必须承担“收束”或“落点确认”的作用。
- 如果失败项不是首段，不要改坏 `previous_segment_id` 与承接链；如果是首段，也不要破坏 scene 级过渡承接。
- 不要输出 `start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{scene_transition_rule.rstrip()}
{self._segment_field_concision_rule_block()}
{self._structured_output_guardrail_line()}

当前失败原因：
{failure_message}

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

上一轮失败 segment JSON：
{offending_segment_json}
""".strip()

    def _build_scene_segment_action_repair_user_prompt(
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
        action_node_count: int,
        current_duration_seconds: int,
        max_action_nodes: int,
        required_segment_count: int,
        max_segments_override: int,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="repair",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        chunk_json = self._prompt_json(self._build_prompt_chunk_payload(chunk_payload or {}))
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
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        chunk_order_index = int((chunk_payload or {}).get("order_index", 0) or 0)
        scene_transition_rule = ""
        if chunk_order_index == 1 and str(
            scene_transition_contract.get("previous_scene_id", "") or ""
        ).strip():
            scene_transition_rule = (
                "- 当前 chunk 是本 scene 的首段承接段；修复动作过载时，不得删掉 `scene_transition_contract` 已要求的开场承接。\n"
                "- 首个修复后 segment 仍必须保留 `next_scene_entry_match` 与 `bridge_action`，不要把跨 scene 过渡修掉成普通重新开场。\n"
            )
        return f"""
你是 StoryForge 的动作拆段修复 Agent。
你收到的是同一个 chunk 上一轮失败的完整合同。不要从零重写剧情；请基于失败合同做最小必要改写，把动作容量超载的片段拆成可执行的正式 segment。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次必须返回当前 chunk 的完整 `segments` 列表，不是 patch，不是 diff。
- 所有 `segment.chapter_number` 必须是 {chapter_number}；所有 `segment.scene_id` 必须是 `{scene_id}`。
- 上一轮失败的过载片段是 `{offending_segment_id}`。
- 该片段当前约有 {action_node_count} 个推进点，但 {current_duration_seconds} 秒片段最多只允许 {max_action_nodes} 个。
- 本次必须把当前 chunk 至少拆成 {required_segment_count} 个 segment，且最多只能输出 {max_segments_override} 个 segment。
- 如果上一轮 batch 里存在未过载的 segment，优先保留它们的事件顺序、角色承接、镜头状态和连续性，只重写必要片段。
- 不得再原样保留一个仍然塞入过多推进点的单段；必须按动作结果、对白轮次、入画变化、距离变化或关系推进点拆开。
- 每个拆出来的新段都必须承担一段更窄的推进，不要制造近义重复段。
- 不得回放当前 chunk 之前已经发生的事件，也不得提前写入当前 chunk 之后的剧情结果。
- 若当前过载段本来就是开口、回应、靠近、转身、停步、递出物件、关系落点这类连续链路，应按“前一拍建立 -> 中间推进 -> 尾拍收束”拆开，而不是平均切字数。
- 不要输出 `start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{scene_transition_rule.rstrip()}
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

上一轮失败 segment JSON：
{offending_segment_json}
""".strip()

    def _build_scene_segment_focus_repair_user_prompt(
        self,
        novel_package: NovelPackage,
        *,
        chapter_number: int,
        story_memory: StoryMemoryPackage,
        scene_payload: dict[str, object],
        chunk_payload: dict[str, object] | None = None,
        previous_chunk_exit_state: dict[str, object] | None = None,
        failed_contract_payload: dict[str, object],
        failure_message: str,
        offending_segment_id: str,
        field_name: str,
        frame_label: str,
        frame_characters: list[str],
        max_segments_override: int,
    ) -> str:
        allowed_names = "、".join(item.name for item in novel_package.outline.characters) or "无"
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="repair",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        chunk_json = self._prompt_json(self._build_prompt_chunk_payload(chunk_payload or {}))
        memory_json = self._prompt_json(memory_context)
        previous_chunk_exit_json = self._prompt_json(previous_chunk_exit_state or {})
        failed_contract_json = self._prompt_json(failed_contract_payload)
        offending_segment_payload = next(
            (
                item
                for item in list(failed_contract_payload.get("segments", []) or [])
                if str(item.get("segment_id", "")).strip() == offending_segment_id
            ),
            {},
        )
        offending_segment_json = self._prompt_json(offending_segment_payload)
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        frame_names_text = "、".join(frame_characters) or "未知角色"
        focus_name = frame_characters[0] if frame_characters else "主角"
        frame_specific_rule = ""
        if frame_label == "mid_frame":
            frame_specific_rule = (
                "- 如果你坚持把 `mid_frame` 改成单人特写，只允许使用 `mid_frame_mode=insert_cut`。\n"
                "- 一旦使用 `insert_cut`，就必须同步改对 `mid_frame_characters`、`timed_beats`、"
                "`mid_frame_prompt`、`shot_state.framing` 和 `shot_state.camera_motion`，"
                "写成“主镜头 -> 插入镜头 -> 主镜头”的往返结构。\n"
            )
        else:
            frame_specific_rule = (
                f"- 当前报错发生在 `{frame_label}` 主锚点。默认应保留 `{frame_names_text}` 这组角色作为该帧真实出镜角色，"
                "不要为了绕过校验，偷偷把主锚点改成单人特写。\n"
            )
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        chunk_order_index = int((chunk_payload or {}).get("order_index", 0) or 0)
        scene_transition_rule = ""
        if chunk_order_index == 1 and str(
            scene_transition_contract.get("previous_scene_id", "") or ""
        ).strip():
            scene_transition_rule = (
                "- 当前 chunk 是本 scene 的首段承接段；修当前镜头冲突时，不得删掉 `scene_transition_contract` 已要求的开场承接。\n"
                "- 首个修复后 segment 仍必须保留 `next_scene_entry_match` 与 `bridge_action`，不要把跨 scene 过渡修掉成普通重新开场。\n"
            )
        return f"""
你是 StoryForge 的多人同帧镜头冲突修复 Agent。
你收到的是同一个 chunk 上一轮失败的完整合同。不要从零重写剧情；请基于失败合同做最小必要改写，只修复“多人同帧却仍要求单人特写”的镜头冲突。

- 小说标题：{novel_package.outline.title}
- 当前章节：第 {chapter_number} 章
- 目标 scene：{scene_id}
- 角色原名白名单：{allowed_names}
- 只能使用小说中已存在的角色原名，不得改名，不得新增角色。
- 本次必须返回当前 chunk 的完整 `segments` 列表，不是 patch，不是 diff。
- 所有 `segment.chapter_number` 必须是 {chapter_number}；所有 `segment.scene_id` 必须是 `{scene_id}`。
- 当前 chunk 最多只能输出 {max_segments_override} 个 segment；不要为了修镜头冲突而额外加段。
- 上一轮失败 segment 是 `{offending_segment_id}`。
- 当前失败字段是 `{field_name}`，冲突帧是 `{frame_label}`，该帧当前角色组是 `{frame_names_text}`。
- 本次优先做“镜头一致性修复”，不要大改未报错 segment 的剧情推进、对白、承接和段数。
- 只要 `{frame_label}` 仍要求 `{frame_names_text}` 同框，就必须把 `shot_state.framing` 与 `shot_state.camera_motion` 都改成共享镜头语言，不要再写“{focus_name} 单人近景”“推向 {focus_name} 侧脸特写”“聚焦 {focus_name} 脸部”这类单人特写句。
- 合法方向示例：
  - `shot_state.framing=双人中近景，保持 {frame_names_text} 同框`
  - `shot_state.camera_motion=轻微前推，保持 {frame_names_text} 同框，只通过站位和表情差异突出 {focus_name} 情绪变化`
- 如果当前失败字段改对了，但另一个共享字段仍保留单人特写话术，这次仍会失败；请一起检查 `shot_state.framing` 和 `shot_state.camera_motion`。
{frame_specific_rule.rstrip()}
- 不要改坏 `timed_beats`、`continuity_link`、scene 边界承接和对白预算；如果它们本来已合理，就尽量保持不变。
- 不要输出 `start_frame_prompt`、`mid_frame_prompt`、`end_frame_prompt`。
- 不要输出 `sound_effects`、`music_direction`、`character_voice_notes`。
- 禁止在任何字段写工程注记或制作标签，例如 `第1段`、`第2段`、`当前子片段`、`重点呈现`、`收束状态`。
{self._frame_character_rule_block()}
{self._segment_audio_budget_rule_block()}
{self._segment_continuity_rule_block()}
{self._anti_micro_split_rule_block()}
{scene_transition_rule.rstrip()}
{self._segment_field_concision_rule_block()}
{self._structured_output_guardrail_line()}

当前失败原因：
{failure_message}

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

上一轮失败 segment JSON：
{offending_segment_json}
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
        focus_terms = self._build_scene_focus_terms(scene_payload=scene_payload)
        memory_context = self._build_story_memory_prompt_context(
            story_memory,
            chapter_number=chapter_number,
            context_mode="scene_chunk",
            focus_characters=list(scene_payload.get("involved_characters", []) or []),
        )
        chapter_block = self._build_chapter_segment_directive(
            novel_package,
            chapter_number=chapter_number,
            excerpt_max_chars=self.SCENE_CHUNK_PLANNER_EXCERPT_CHARS,
            focus_terms=focus_terms,
            compact=True,
        )
        scene_json = self._prompt_json(self._build_prompt_scene_payload(scene_payload))
        memory_json = self._prompt_json(memory_context)
        scene_id = str(scene_payload.get("scene_id", "")).strip()
        covered_event_summary_block = self._format_scene_covered_event_summary_block(scene_payload)
        scene_transition_contract = dict(scene_payload.get("scene_transition_contract", {}) or {})
        transition_rule = ""
        if str(scene_transition_contract.get("previous_scene_id", "") or "").strip():
            transition_rule = (
                "- 当前 scene 带有 `scene_transition_contract`；第一个 chunk 必须消费它，不得把上一场已完成的动作重新演一遍。\n"
                "- 首个 chunk 的 `summary / must_cover / transition_goal` 必须先覆盖 `next_scene_entry_match` 与 `bridge_action`，再进入本 scene 的新推进。\n"
                "- 如果是 `adjacent_move` 或 `motivated_cut`，第一个 chunk 还要体现新环境如何被 reveal，而不是直接瞬移到静止新画面。\n"
            )
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
- 当前 scene 已绑定这些关键事件 ID：{", ".join(str(item).strip() for item in list(scene_payload.get("covered_event_ids", []) or []) if str(item).strip()) or "无"}。
- 当前 scene 只允许覆盖下面这些绑定事件内容，不能提前吞掉未绑定的后续事件：
{covered_event_summary_block}
- 最后一个 chunk 必须真正落到当前 scene 的最后一个事件结果，不要把当前 scene 的结尾写成“即将表白 / 即将回应 / 即将亲近 / 即将离开”这类半停顿状态。
- 一个 scene 通常拆成 1-4 个 chunk；如果 scene 本身只有一个完整动作单元，就只输出 1 个 chunk。
- 对话、告白、回应类 scene 优先拆成 1-3 个 chunk；不要把同一轮告白、同一轮回应拆成多个近义重复 chunk。
- 整个 scene 的 `expected_segment_count` 总和通常控制在 2-8；不要为了拖时长把同一事件拆成大量 chunk。
- `expected_segment_count` 是后续 segment planner 的硬上限，也是你现在就要算准的最终执行数量；后续不得超过这个上限继续加段。
- `must_cover` 只写 1-3 条短句，`transition_goal` 只写一句短话，`expected_segment_count` 只填 1-4。
- 不要把整个 scene 的完整摘要复制到每个 chunk；每个 chunk 只保留自己负责的那一小段。
{transition_rule.rstrip()}
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
        context_mode: str = "chapter_scene",
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
        chapter_scoped = context_mode == "chapter_scene"
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
        previous_exit_payload = self._build_story_memory_exit_state_payload(
            previous_chapter_state.exit_state if previous_chapter_state else {}
        )
        current_chapter_payload = {
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
            "unresolved_threads": (
                current_chapter_state.unresolved_threads[:2] if current_chapter_state else []
            ),
        }
        continuity_payload = {
            "current_time_context": story_memory.continuity_state.current_time_context,
            "current_location_context": story_memory.continuity_state.current_location_context,
            "active_props": story_memory.continuity_state.active_props[:3],
            "active_relationship_state": story_memory.continuity_state.active_relationship_state[:3],
        }
        if context_mode == "repair":
            return {
                "focus_cast_bible": focus_cast,
                "previous_chapter_exit_state": previous_exit_payload,
            }
        if context_mode == "scene_chunk":
            return {
                "global_story_bible": {
                    "narrative_promise": story_memory.global_story_bible.narrative_promise,
                    "visual_motifs": story_memory.global_story_bible.visual_motifs[:3],
                },
                "focus_cast_bible": focus_cast,
                "current_chapter_state": {
                    "chapter_number": current_chapter_payload["chapter_number"],
                    "carry_over_summary": current_chapter_payload["carry_over_summary"],
                    "carry_over_visuals": current_chapter_payload["carry_over_visuals"],
                    "relationship_state": current_chapter_payload["relationship_state"],
                },
                "previous_chapter_exit_state": previous_exit_payload,
                "continuity_state": {
                    "current_time_context": continuity_payload["current_time_context"],
                    "current_location_context": continuity_payload["current_location_context"],
                },
            }
        if context_mode == "segment_contract":
            return {
                "focus_cast_bible": focus_cast,
                "current_chapter_state": {
                    "chapter_number": current_chapter_payload["chapter_number"],
                    "carry_over_summary": current_chapter_payload["carry_over_summary"],
                    "relationship_state": current_chapter_payload["relationship_state"],
                },
                "previous_chapter_exit_state": previous_exit_payload,
                "continuity_state": {
                    "current_time_context": continuity_payload["current_time_context"],
                    "current_location_context": continuity_payload["current_location_context"],
                    "active_relationship_state": continuity_payload["active_relationship_state"],
                },
            }
        return {
            "global_story_bible": {
                "core_theme": story_memory.global_story_bible.core_theme,
                "narrative_promise": story_memory.global_story_bible.narrative_promise,
                "visual_motifs": story_memory.global_story_bible.visual_motifs,
                "forbidden_deviations": story_memory.global_story_bible.forbidden_deviations,
            },
            "chapter_batch_view": chapter_batch_view,
            "focus_cast_bible": focus_cast,
            "current_chapter_state": {
                **current_chapter_payload,
                "entry_state": current_chapter_state.entry_state if current_chapter_state else {},
                "new_facts": current_chapter_state.new_facts[:3] if current_chapter_state else [],
                "resolved_threads": current_chapter_state.resolved_threads[:2] if current_chapter_state else [],
            },
            "previous_chapter_exit_state": previous_exit_payload,
            "recent_chapter_memory": recent_memory,
            "continuity_state": {
                **continuity_payload,
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
                "appearance_summary": self._compact_story_memory_text(item.appearance_summary, limit=56),
                "hard_constraints": list(item.hard_constraints[:1]),
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

    def _build_prompt_scene_payload(
        self,
        scene_payload: dict[str, object],
    ) -> dict[str, object]:
        scene_bible = scene_payload.get("scene_bible", {}) or {}
        return {
            "scene_id": str(scene_payload.get("scene_id", "") or ""),
            "title": self._compact_story_memory_text(str(scene_payload.get("title", "") or ""), limit=40),
            "summary": self._compact_story_memory_text(str(scene_payload.get("summary", "") or ""), limit=100),
            "scene_anchor": self._compact_story_memory_text(
                str(scene_payload.get("scene_anchor", "") or ""),
                limit=80,
            ),
            "involved_characters": list(scene_payload.get("involved_characters", []) or [])[:4],
            "covered_event_summaries": [
                self._compact_story_memory_text(str(item or ""), limit=56)
                for item in list(scene_payload.get("covered_event_summaries", []) or [])[:4]
                if str(item or "").strip()
            ],
            "scene_transition_contract": self._build_prompt_scene_transition_payload(
                scene_payload.get("scene_transition_contract")
            ),
            "scene_bible": self._build_prompt_scene_bible_payload(scene_bible),
        }

    def _build_prompt_scene_transition_payload(
        self,
        raw_contract: object,
    ) -> dict[str, object]:
        payload = raw_contract if isinstance(raw_contract, dict) else to_jsonable(raw_contract)
        if not isinstance(payload, dict):
            return {}
        return {
            "previous_scene_id": str(payload.get("previous_scene_id", "") or ""),
            "transition_mode": str(payload.get("transition_mode", "") or ""),
            "previous_scene_exit_state": self._compact_story_memory_text(
                str(payload.get("previous_scene_exit_state", "") or ""),
                limit=48,
            ),
            "next_scene_entry_match": self._compact_story_memory_text(
                str(payload.get("next_scene_entry_match", "") or ""),
                limit=48,
            ),
            "bridge_action": self._compact_story_memory_text(
                str(payload.get("bridge_action", "") or ""),
                limit=48,
            ),
            "carry_over_elements": [
                self._compact_story_memory_text(str(item or ""), limit=24)
                for item in list(payload.get("carry_over_elements", []) or [])[:3]
                if str(item or "").strip()
            ],
            "screen_direction_policy": self._compact_story_memory_text(
                str(payload.get("screen_direction_policy", "") or ""),
                limit=32,
            ),
            "visual_bridge": self._compact_story_memory_text(
                str(payload.get("visual_bridge", "") or ""),
                limit=40,
            ),
            "audio_bridge": str(payload.get("audio_bridge", "none") or "none"),
            "transition_focus_seconds": int(payload.get("transition_focus_seconds", 0) or 0),
        }

    def _build_prompt_chunk_payload(
        self,
        chunk_payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "chunk_id": str(chunk_payload.get("chunk_id", "") or ""),
            "title": self._compact_story_memory_text(str(chunk_payload.get("title", "") or ""), limit=40),
            "summary": self._compact_story_memory_text(str(chunk_payload.get("summary", "") or ""), limit=100),
            "must_cover": [
                self._compact_story_memory_text(str(item or ""), limit=40)
                for item in list(chunk_payload.get("must_cover", []) or [])[:3]
                if str(item or "").strip()
            ],
            "transition_goal": self._compact_story_memory_text(
                str(chunk_payload.get("transition_goal", "") or ""),
                limit=50,
            ),
            "expected_segment_count": int(chunk_payload.get("expected_segment_count", 0) or 0),
        }

    def _build_prompt_scene_bible_payload(
        self,
        scene_bible: object,
    ) -> dict[str, object]:
        payload = scene_bible if isinstance(scene_bible, dict) else to_jsonable(scene_bible)
        if not isinstance(payload, dict):
            return {}
        return {
            "location": self._compact_story_memory_text(str(payload.get("location", "") or ""), limit=40),
            "time_window": self._compact_story_memory_text(str(payload.get("time_window", "") or ""), limit=24),
            "weather": self._compact_story_memory_text(str(payload.get("weather", "") or ""), limit=20),
            "lighting": self._compact_story_memory_text(str(payload.get("lighting", "") or ""), limit=36),
            "background_anchors": [
                self._compact_story_memory_text(str(item or ""), limit=24)
                for item in list(payload.get("background_anchors", []) or [])[:3]
                if str(item or "").strip()
            ],
            "fixed_props": [
                self._compact_story_memory_text(str(item or ""), limit=24)
                for item in list(payload.get("fixed_props", []) or [])[:2]
                if str(item or "").strip()
            ],
            "spatial_layout": self._compact_story_memory_text(
                str(payload.get("spatial_layout", "") or ""),
                limit=48,
            ),
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
  - `start_frame_prompt`
  - `mid_frame_prompt`
  - `end_frame_prompt`
  - `start_frame_characters`
  - `mid_frame_characters`
  - `mid_frame_mode`
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
- 如果本段已经有 `dialogue_lines`，不要再用 `narration` 复述同一动作或同一句话；`subtitle_lines` 也不要重复写描述性动作旁白
- `timed_beats` 必须写出具体秒数，不要只写抽象节奏
- 如果本段存在 `dialogue_lines` 或 `narration`，`timed_beats` 必须直接写出哪一秒谁说了哪句，不能只写“他开口”“她回应”
- 修复对白相关问题时，优先把真实口播句子准确挂回 `timed_beats`，让后续视频 prompt 能直接看到“哪一秒谁说什么”
- `start_frame_characters` / `mid_frame_characters` / `end_frame_characters` 必须是 `involved_characters` 的子集
- 先判断中段属于哪一类：如果首尾是同一组双人 / 多人，而中段仍是这组角色的连续表演，就保留整组角色并写 `mid_frame_mode=continuous`
- 如果首尾是同一组双人 / 多人，而中段只保留其中一人的单人特写或反应镜头，才允许把 `mid_frame_characters` 缩成子集；这时必须把 `mid_frame_mode=insert_cut`，并把运镜写成“从主镜头切入，再切回主镜头收束”
- 不要输出这种非法结构：`start=[苏雨,林晨] / mid=[苏雨] / end=[苏雨,林晨] / mid_frame_mode=continuous`
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
        compact: bool = False,
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
        if compact:
            compact_beats = self._excerpt_text(beats, max_chars=72)
            return (
                f"- 第 {chapter.number} 章《{chapter.title}》\n"
                f"  摘要：{self._compact_story_memory_text(chapter.summary, limit=70)}\n"
                f"  节拍：{compact_beats}\n"
                f"{focus_line}"
                f"  正文摘录：{excerpt}"
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

    def _build_scene_focus_terms(
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

    def _build_character_sheet_prompt(
        self,
        name: str,
        gender: str,
        appearance: str,
        outfit: str,
    ) -> str:
        appearance_text = str(appearance or "").strip(" ，。；;\n\t")
        outfit_text = str(outfit or "").strip(" ，。；;\n\t")
        gender_text = str(gender or "").strip(" ，。；;\n\t") or "未指定"
        return (
            "原创虚构角色白底三视图，单角色，非真人摄影，非写实照片。"
            f"{self.CHARACTER_SHEET_LAYOUT_PROMPT}"
            f"画面唯一可见文字：{name}。"
            f"内部造型约束：性别 {gender_text}，仅用于稳定人物生理特征与服装轮廓，不要写成画面文字。"
            f"外观：{appearance_text}。"
            f"服装：{outfit_text}。"
            "只根据姓名、外观和服装生成同一个角色的正面、左侧面、背面三视图。"
            "保持同一张脸、同一发型、同一服装和同一身材比例，不要换脸，不要改变年龄感，不要出现额外角色、剧情场景、信息板或多余文字标签。"
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
        *,
        involved_characters: list[str] | None = None,
        scene_bible: object | None = None,
        shot_state: object | None = None,
        continuity_link: object | None = None,
    ) -> str:
        effective_involved_characters = list(involved_characters or frame_characters)
        sanitized_prompt = self._sanitize_frame_prompt_text(
            prompt,
            frame_characters,
            effective_involved_characters,
        )
        scene_bible_context = self._frame_scene_bible_prompt_context(
            scene_bible,
            frame_characters,
            effective_involved_characters,
        )
        shot_state_context = self._frame_shot_state_prompt_context(
            shot_state,
            frame_characters,
            effective_involved_characters,
            frame_type=frame_type,
        )
        continuity_link_context = self._frame_continuity_link_prompt_context(
            continuity_link,
            frame_characters,
            effective_involved_characters,
            frame_type=frame_type,
        )
        action_prompt = self._frame_action_prompt(
            sanitized_prompt,
            frame_characters,
            frame_type=frame_type,
        )
        parts = [
            f"{frame_type}。",
            self._frame_reference_binding_prompt(frame_characters),
            action_prompt,
            scene_bible_context,
            shot_state_context,
            continuity_link_context,
            self._frame_character_presence_prompt(frame_characters),
            self.FRAME_PURE_IMAGE_PROMPT,
        ]
        return "".join(part for part in parts if part)

    def _frame_reference_binding_prompt(self, frame_characters: list[str]) -> str:
        unique_characters = self._merge_unique_character_names(frame_characters)
        parts = ["图片1是场景参考"]
        for index, name in enumerate(unique_characters[:2], start=2):
            parts.append(f"图片{index}是{name}")
        if len(unique_characters) > 2:
            parts.append("其余当前帧角色也按对应参考图还原")
        return "，".join(parts) + "。"

    def _frame_action_prompt(
        self,
        prompt: str,
        frame_characters: list[str],
        *,
        frame_type: str,
    ) -> str:
        unique_characters = self._merge_unique_character_names(frame_characters)
        if not unique_characters:
            return "只保留图片1里的空场景，不要出现人物。"
        subject = self._frame_reference_subject_prompt(unique_characters)
        normalized_action = self._trim_frame_action_subject_prefix(prompt, unique_characters)
        if not normalized_action:
            normalized_action = "只保留当前这一拍真正可见的动作停点和空间关系"
        connector = "继续在图片1的场景里" if "首" not in frame_type else "出现在图片1的场景里"
        return f"{subject}{connector}，{normalized_action}。"

    def _frame_reference_subject_prompt(self, frame_characters: list[str]) -> str:
        if len(frame_characters) == 1:
            return f"让图片2中的{frame_characters[0]}"
        if len(frame_characters) == 2:
            return f"让图片2和图片3中的{frame_characters[0]}、{frame_characters[1]}"
        return "让当前帧角色"

    def _trim_frame_action_subject_prefix(
        self,
        prompt: str,
        frame_characters: list[str],
    ) -> str:
        cleaned = str(prompt or "").strip(" ，。；;")
        if not cleaned:
            return ""
        if len(frame_characters) == 1:
            patterns = (
                rf"^{re.escape(frame_characters[0])}(?:独自|一个人)?(?:正在|继续|仍然)?",
            )
        else:
            joined_names = "、".join(frame_characters[:2])
            patterns = (
                rf"^{re.escape(joined_names)}(?:一起|并肩|相对)?",
                rf"^{re.escape(frame_characters[0])}(?:和|与|、){re.escape(frame_characters[1])}(?:一起|并肩|相对)?",
                rf"^{re.escape(frame_characters[1])}(?:和|与|、){re.escape(frame_characters[0])}(?:一起|并肩|相对)?",
            )
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, count=1).strip(" ，。；;")
        return cleaned

    def _frame_character_presence_prompt(self, frame_characters: list[str]) -> str:
        unique_characters = self._merge_unique_character_names(frame_characters)
        if not unique_characters:
            return "不要出现人物。"
        return "只画当前帧真正出镜的角色，不要多画、少画或重复同一角色。"

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

    def _strip_character_style_overrides(self, text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        for pattern in self.CHARACTER_STYLE_OVERRIDE_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s*([，。；：,:;!?！？])\s*", r"\1", cleaned)
        cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
        cleaned = re.sub(r"[；;]{2,}", "；", cleaned)
        return cleaned.strip(" ，。；：,:;!?！？")

    def _contains_off_frame_character_name(
        self,
        text: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> bool:
        frame_set = {
            str(name).strip()
            for name in frame_characters
            if str(name).strip()
        }
        return any(
            normalized_name in text
            for name in involved_characters
            if (normalized_name := str(name).strip()) and normalized_name not in frame_set
        )

    def _split_prompt_clauses(self, text: str) -> list[str]:
        return [
            clause.strip(" ，。；;")
            for clause in re.split(r"[，。；;]+", str(text or ""))
            if clause.strip(" ，。；;")
        ]

    def _sanitize_frame_context_value(
        self,
        text: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> str:
        cleaned = self._strip_character_style_overrides(text)
        if not cleaned:
            return ""
        if self._contains_off_frame_character_name(
            cleaned,
            frame_characters,
            involved_characters,
        ):
            return ""
        if self._has_multi_character_single_subject_focus(cleaned, frame_characters):
            return ""
        return cleaned

    def _sanitize_frame_context_list(
        self,
        values: list[str],
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> list[str]:
        return [
            cleaned
            for item in values
            if (cleaned := self._sanitize_frame_context_value(item, frame_characters, involved_characters))
        ]

    def _sanitize_frame_prompt_text(
        self,
        prompt: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> str:
        sanitized = self._sanitize_image_prompt_text(prompt)
        sanitized = self._strip_internal_segment_markers(sanitized)
        sanitized = self._strip_character_style_overrides(sanitized)
        if not sanitized:
            return ""

        filtered_clauses = [
            clause
            for clause in self._split_prompt_clauses(sanitized)
            if not self._contains_off_frame_character_name(
                clause,
                frame_characters,
                involved_characters,
            )
            and not self._has_multi_character_single_subject_focus(
                clause,
                frame_characters,
            )
            and not self._contains_single_character_frame_multi_subject_signal(
                clause,
                frame_characters,
                involved_characters,
            )
        ]
        if filtered_clauses:
            return "，".join(filtered_clauses)
        if self._contains_off_frame_character_name(
            sanitized,
            frame_characters,
            involved_characters,
        ):
            return ""
        if self._has_multi_character_single_subject_focus(
            sanitized,
            frame_characters,
        ):
            return ""
        if self._contains_single_character_frame_multi_subject_signal(
            sanitized,
            frame_characters,
            involved_characters,
        ):
            return ""
        return sanitized

    def _contains_single_character_frame_multi_subject_signal(
        self,
        text: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> bool:
        unique_frame_characters = [
            str(name).strip()
            for name in frame_characters
            if str(name).strip()
        ]
        if len(unique_frame_characters) != 1:
            return False
        involved_count = len(
            [
                str(name).strip()
                for name in involved_characters
                if str(name).strip()
            ]
        )
        if involved_count < 2:
            return False
        normalized = str(text or "").strip()
        if not normalized:
            return False
        multi_subject_tokens = (
            "两人",
            "双人",
            "双方",
            "二人",
            "一起",
            "并肩",
            "相对",
            "面对面",
            "对视",
            "对话",
            "交谈",
            "会面",
            "站定",
            "相遇",
        )
        return any(token in normalized for token in multi_subject_tokens)

    def _has_multi_character_single_subject_focus(
        self,
        text: str,
        frame_characters: list[str],
    ) -> bool:
        unique_frame_characters = [
            str(name).strip()
            for name in frame_characters
            if str(name).strip()
        ]
        if len(unique_frame_characters) < 2:
            return False
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
        focus_tokens = (
            "特写",
            "大特写",
            "近景",
            "中近景",
            "侧脸",
            "脸部",
            "面部",
            "半脸",
        )
        if not any(token in normalized for token in focus_tokens):
            return False
        if any(name in normalized for name in unique_frame_characters):
            return True
        return any(
            token in normalized
            for token in (
                "推向",
                "推近",
                "推进到",
                "聚焦到",
                "切到",
                "拉到",
                "摇到",
            )
        )

    def _frame_scene_bible_prompt_context(
        self,
        scene_bible: object | None,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> str:
        if scene_bible is None:
            return ""
        parts: list[str] = []
        for value in (
            self._scene_bible_value(scene_bible, "location"),
            self._scene_bible_value(scene_bible, "lighting"),
        ):
            normalized = self._sanitize_frame_context_value(
                value,
                frame_characters,
                involved_characters,
            )
            if normalized and normalized not in parts:
                parts.append(normalized)
        anchor_values = self._sanitize_frame_context_list(
            self._scene_bible_list(scene_bible, "background_anchors"),
            frame_characters,
            involved_characters,
        )
        prop_values = self._sanitize_frame_context_list(
            self._scene_bible_environment_fixed_props(scene_bible),
            frame_characters,
            involved_characters,
        )
        time_window = self._sanitize_frame_context_value(
            self._scene_bible_value(scene_bible, "time_window"),
            frame_characters,
            involved_characters,
        )
        ordered_details = [
            *anchor_values[:1],
            *prop_values[:1],
            *anchor_values[1:2],
            time_window,
        ]
        for value in ordered_details:
            if value and value not in parts:
                parts.append(value)
        if not parts:
            return ""
        return f"保持图片1里的{'、'.join(parts[:4])}。"

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

    def _scene_master_frame_prompt_context(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        line = self._scene_master_frame_prompt_line(scene_bible, involved_characters)
        if not line:
            return ""
        return f"空场景环境约束：{line}。"

    def _frame_shot_state_prompt_context(
        self,
        shot_state: object | None,
        frame_characters: list[str],
        involved_characters: list[str],
        *,
        frame_type: str,
    ) -> str:
        if shot_state is None:
            return ""
        normalized_frame_type = "mid"
        if "首" in frame_type:
            normalized_frame_type = "start"
        elif "尾" in frame_type:
            normalized_frame_type = "end"
        if normalized_frame_type == "end":
            candidate_keys = ("end_state_lock", "blocking", "framing")
            prefix = "尾帧收在"
        elif normalized_frame_type == "mid":
            candidate_keys = ("blocking", "framing")
            prefix = "中段停在"
        else:
            candidate_keys = ("blocking", "framing")
            prefix = "开场落在"
        for key in candidate_keys:
            normalized = self._sanitize_frame_context_value(
                self._shot_state_value(shot_state, key),
                frame_characters,
                involved_characters,
            )
            if self._contains_single_character_frame_multi_subject_signal(
                normalized,
                frame_characters,
                involved_characters,
            ):
                continue
            if normalized:
                return f"{prefix}{normalized}。"
        return ""

    def _frame_continuity_link_prompt_context(
        self,
        continuity_link: object | None,
        frame_characters: list[str],
        involved_characters: list[str],
        *,
        frame_type: str,
    ) -> str:
        if continuity_link is None:
            return ""
        if "首" in frame_type:
            opening_match = self._sanitize_frame_context_value(
                self._continuity_link_value(continuity_link, "opening_match"),
                frame_characters,
                involved_characters,
            )
            if opening_match:
                return f"开场先承接{opening_match}。"
            return ""
        if "尾" in frame_type:
            return "保持前一拍已经建立的机位、朝向和动作方向，在当前尾部停点自然收束。"
        return "延续前后关键帧之间已经建立的机位、朝向和动作方向。"

    def _derive_scene_master_spatial_contract(
        self,
        *texts: str,
        involved_characters: list[str],
        max_clauses: int = 3,
    ) -> str:
        clauses: list[str] = []
        for text in texts:
            normalized_text = self._strip_internal_segment_markers(
                self._strip_character_style_overrides(
                    self._sanitize_image_prompt_text(text)
                )
            )
            if not normalized_text:
                continue
            for clause in re.split(r"[，。；;]+", normalized_text):
                candidate = self._normalize_scene_master_spatial_clause(
                    clause,
                    involved_characters,
                )
                if not candidate or candidate in clauses:
                    continue
                clauses.append(candidate)
                if len(clauses) >= max_clauses:
                    return "；".join(clauses)
        return "；".join(clauses)

    def _normalize_scene_master_spatial_clause(
        self,
        text: str,
        involved_characters: list[str],
    ) -> str:
        cleaned = self._strip_scene_master_human_staging(text, involved_characters)
        if len(cleaned) < 2:
            return ""
        if self._contains_scene_master_human_signal(cleaned, involved_characters):
            return ""
        if not self._looks_like_scene_master_spatial_clause(cleaned):
            return ""
        return cleaned

    def _strip_scene_master_human_staging(
        self,
        text: str,
        involved_characters: list[str],
    ) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        for name in involved_characters:
            normalized_name = str(name).strip()
            if normalized_name:
                cleaned = cleaned.replace(normalized_name, "")
        for token in (
            "一人",
            "单人",
            "两人",
            "双人",
            "三人",
            "多人",
            "一男一女",
            "男女",
            "情侣",
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
            "剪影",
            "背影",
        ):
            cleaned = cleaned.replace(token, "")
        for pattern in self.SCENE_MASTER_SPATIAL_HUMAN_STRIP_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"^(?:他|她|他们|她们|对方)\s*", "", cleaned)
        cleaned = re.sub(r"^(?:从|沿|朝|向|往|于|在)\s*", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s*([，。；：,:;!?！？])\s*", r"\1", cleaned)
        cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
        cleaned = re.sub(r"[；;]{2,}", "；", cleaned)
        return cleaned.strip(" ，。；：,:;!?！？")

    def _looks_like_scene_master_spatial_clause(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        has_spatial_relation = (
            any(token in normalized for token in self.SCENE_MASTER_SPATIAL_RELATION_TOKENS)
            or normalized.endswith(self.SCENE_MASTER_SPATIAL_SUFFIXES)
            or bool(self.SCENE_MASTER_SPATIAL_DISTANCE_PATTERN.search(normalized))
        )
        has_environment_signal = any(
            keyword in normalized for keyword in self.SCENE_MASTER_ENVIRONMENT_SIGNAL_KEYWORDS
        )
        if not has_environment_signal and not has_spatial_relation:
            return False
        return bool(self.SCENE_MASTER_SPATIAL_NOUN_HINT_PATTERN.search(normalized))

    def _scene_master_frame_prompt_line(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        spatial_layout = self._derive_scene_master_spatial_contract(
            self._scene_bible_value(scene_bible, "spatial_layout"),
            self._scene_bible_value(scene_bible, "character_blocking"),
            involved_characters=involved_characters,
            max_clauses=3,
        ) or self._scene_bible_value(scene_bible, "spatial_layout")
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", spatial_layout),
        ):
            normalized = self._strip_character_style_overrides(str(value or "").strip())
            if normalized and not self._contains_scene_master_human_signal(
                normalized,
                involved_characters,
            ):
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_environment_fixed_props(scene_bible)),
        ):
            filtered_values = [
                cleaned
                for item in values
                if (cleaned := self._strip_character_style_overrides(str(item).strip()))
                and not self._contains_scene_master_human_signal(cleaned, involved_characters)
            ]
            normalized_values = [str(item).strip() for item in filtered_values if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

        return "；".join(parts)

    def _scene_master_baseline_prompt_line(
        self,
        scene_bible: object,
        involved_characters: list[str],
    ) -> str:
        spatial_layout = self._derive_scene_master_spatial_contract(
            self._scene_bible_value(scene_bible, "spatial_layout"),
            self._scene_bible_value(scene_bible, "character_blocking"),
            involved_characters=involved_characters,
            max_clauses=3,
        ) or self._scene_bible_value(scene_bible, "spatial_layout")
        parts: list[str] = []
        for label, value in (
            ("地点", self._scene_bible_value(scene_bible, "location")),
            ("时间", self._scene_bible_value(scene_bible, "time_window")),
            ("天气", self._scene_bible_value(scene_bible, "weather")),
            ("光线", self._scene_bible_value(scene_bible, "lighting")),
            ("空间布局", spatial_layout),
        ):
            normalized = self._strip_character_style_overrides(str(value or "").strip())
            if normalized and not self._contains_scene_master_human_signal(
                normalized,
                involved_characters,
            ):
                parts.append(f"{label}：{normalized}")

        for label, values in (
            ("主色调", self._scene_bible_list(scene_bible, "dominant_palette")),
            ("背景锚点", self._scene_bible_list(scene_bible, "background_anchors")),
            ("固定道具", self._scene_bible_environment_fixed_props(scene_bible)),
        ):
            filtered_values = [
                cleaned
                for item in values
                if (cleaned := self._strip_character_style_overrides(str(item).strip()))
                and not self._contains_scene_master_human_signal(cleaned, involved_characters)
            ]
            normalized_values = [str(item).strip() for item in filtered_values if str(item).strip()]
            if normalized_values:
                parts.append(f"{label}：{'、'.join(normalized_values[:4])}")

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

    def _scene_bible_environment_fixed_props(self, scene_bible: object) -> list[str]:
        return self._filter_environment_fixed_props(
            self._scene_bible_list(scene_bible, "fixed_props")
        )

    def _filter_environment_fixed_props(self, values: list[str]) -> list[str]:
        filtered: list[str] = []
        for item in values or []:
            cleaned = self._strip_character_style_overrides(str(item).strip())
            if not cleaned or self._is_transient_carried_prop(cleaned):
                continue
            filtered.append(cleaned)
        return filtered

    def _is_transient_carried_prop(self, value: str) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return False
        if any(token in normalized for token in self.ENVIRONMENT_PROP_ANCHOR_TOKENS):
            return False
        return any(pattern.search(normalized) for pattern in self.TRANSIENT_FIXED_PROP_PATTERNS)

    def _sanitize_segment_sound_effects(
        self,
        sound_effects: list[str],
        *,
        scene_bible: object | None = None,
        prop_continuity: str = "",
    ) -> list[str]:
        environment_props = {
            item
            for item in self._scene_bible_environment_fixed_props(scene_bible)
            if str(item).strip()
        } if scene_bible is not None else set()
        continuity_text = self._strip_character_style_overrides(str(prop_continuity or "").strip())
        sanitized: list[str] = []
        for item in sound_effects or []:
            cleaned = self._strip_character_style_overrides(str(item).strip())
            if not cleaned:
                continue
            prop_match = self.PROP_SOUND_EFFECT_PATTERN.search(cleaned)
            if prop_match is not None:
                prop_name = prop_match.group("prop").strip()
                if prop_name and self._is_transient_carried_prop(prop_name):
                    if prop_name not in continuity_text:
                        continue
                if environment_props and prop_name and prop_name not in environment_props and prop_name not in continuity_text:
                    continue
            if cleaned not in sanitized:
                sanitized.append(cleaned)
        return sanitized

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
                "一人",
                "单人",
                "两人",
                "双人",
                "三人",
                "多人",
                "一男一女",
                "男女",
                "情侣",
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
                "剪影",
                "背影",
                "站位",
                "走位",
                "站在",
                "站立",
                "坐在",
                "走近",
                "走向",
                "走进",
                "并肩",
                "相对",
                "面对面",
                "牵手",
                "拉手",
                "对视",
                "靠近",
                "等待",
                "追逐",
                "奔跑",
                "拥抱",
                "亲吻",
                "接吻",
                "拥吻",
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

    def _seedance_frame_prompt_text(
        self,
        prompt: str,
        frame_characters: list[str],
        involved_characters: list[str],
    ) -> str:
        effective_frame_characters = (
            frame_characters
            if any(str(name).strip() for name in frame_characters)
            else involved_characters
        )
        sanitized = self._sanitize_frame_prompt_text(
            prompt,
            effective_frame_characters,
            involved_characters,
        )
        if not sanitized:
            return ""
        return sanitized

    def _character_set_label(self, characters: list[str]) -> str:
        normalized = [str(name).strip() for name in characters if str(name).strip()]
        return "、".join(normalized) if normalized else "环境镜头"

    def _same_character_set(self, left: list[str], right: list[str]) -> bool:
        left_names = {str(name).strip() for name in left if str(name).strip()}
        right_names = {str(name).strip() for name in right if str(name).strip()}
        return left_names == right_names

    def _normalized_mid_frame_mode(self, value: object) -> str:
        return "insert_cut" if str(value or "").strip().lower() == "insert_cut" else "continuous"

    def _segment_uses_mid_insert_cut(self, segment: VideoSegment) -> bool:
        return (
            segment.requires_mid_frame
            and self._normalized_mid_frame_mode(getattr(segment, "mid_frame_mode", "continuous")) == "insert_cut"
        )

    def _segment_has_mid_anchor(self, segment: VideoSegment) -> bool:
        return bool(segment.requires_mid_frame and str(segment.mid_frame_prompt or "").strip())

    def _segment_stage_time_labels(
        self,
        duration_seconds: int,
        stage_count: int,
    ) -> list[str]:
        labels: list[str] = []
        for index in range(max(stage_count, 1)):
            start = round(index * duration_seconds / max(stage_count, 1))
            end = round((index + 1) * duration_seconds / max(stage_count, 1))
            if index == stage_count - 1:
                end = duration_seconds
            if end <= start:
                end = min(duration_seconds, start + 1)
            if start == end:
                start = max(0, end - 1)
            labels.append(f"{start}-{end}秒")
        return labels

    def _timed_beat_parts(self, beat: str) -> tuple[str, str]:
        normalized = str(beat or "").strip()
        if not normalized:
            return "", ""
        prefix, separator, suffix = normalized.partition("：")
        if not separator:
            prefix, separator, suffix = normalized.partition(":")
        if not separator:
            return "", normalized
        return prefix.strip(), suffix.strip()

    def _timed_beat_focus_text(self, beat: str) -> str:
        _, description = self._timed_beat_parts(beat)
        return str(description or "").strip(" ，。；;")

    def _segment_stage_beat_specs(
        self,
        segment: VideoSegment,
        stage_count: int,
    ) -> list[tuple[str, str]]:
        stage_time_labels = self._segment_stage_time_labels(
            segment.duration_seconds,
            stage_count,
        )
        beats = [
            str(beat).strip()
            for beat in segment.timed_beats
            if str(beat).strip()
        ]
        if not beats:
            return [(label, "") for label in stage_time_labels]
        if stage_count <= 1:
            selected_beats = [beats[0]]
        elif stage_count == 2:
            selected_beats = [beats[0], beats[-1] if len(beats) > 1 else beats[0]]
        else:
            selected_beats = [
                beats[0],
                beats[len(beats) // 2],
                beats[-1],
            ]
        specs: list[tuple[str, str]] = []
        prefer_beat_time_label = len(beats) >= stage_count
        for index in range(stage_count):
            beat = selected_beats[index] if index < len(selected_beats) else ""
            beat_time_label, beat_focus = self._timed_beat_parts(beat)
            specs.append(
                (
                    (beat_time_label if prefer_beat_time_label else "") or stage_time_labels[index],
                    beat_focus.strip(" ，。；;"),
                )
            )
        return specs

    def _stage_prefers_spoken_content(self, focus: str) -> bool:
        normalized = str(focus or "").strip()
        if not normalized:
            return False
        speech_tokens = (
            "说",
            "开口",
            "回应",
            "回答",
            "问",
            "喊",
            "低声",
            "轻声",
            "告白",
            "表白",
            "对白",
            "台词",
        )
        return any(token in normalized for token in speech_tokens)

    def _segment_stage_spoken_notes(
        self,
        *,
        segment: VideoSegment,
        stage_beat_specs: list[tuple[str, str]],
    ) -> list[str]:
        stage_count = len(stage_beat_specs)
        if stage_count <= 0:
            return []
        notes = [""] * stage_count
        narration = str(segment.narration or "").strip()
        dialogue_lines = [
            str(line).strip()
            for line in segment.dialogue_lines
            if str(line).strip()
        ]

        if narration:
            notes[0] = f"旁白：{narration}"

        if not dialogue_lines:
            return notes

        preferred_indexes = [
            index
            for index, (_, focus) in enumerate(stage_beat_specs)
            if self._stage_prefers_spoken_content(focus)
        ]
        if not preferred_indexes:
            start_index = 1 if narration and stage_count > 1 else 0
            preferred_indexes = list(range(start_index, stage_count)) or [stage_count - 1]

        if len(dialogue_lines) == 1 and len(preferred_indexes) > 1:
            target_indexes = [preferred_indexes[-1]]
        else:
            target_indexes = preferred_indexes

        grouped_dialogues = self._chunk_list(dialogue_lines, len(target_indexes))
        for index, chunk in zip(target_indexes, grouped_dialogues):
            if not chunk:
                continue
            dialogue_note = " / ".join(chunk)
            if notes[index]:
                notes[index] += f"；对白：{dialogue_note}"
            else:
                notes[index] = f"对白：{dialogue_note}"
        return notes

    def _build_motion_stage_line(
        self,
        *,
        time_label: str,
        base: str,
        beat_focus: str = "",
        anchor_text: str = "",
        spoken_note: str = "",
    ) -> str:
        line = f"画面推进 {time_label}：{base}"
        normalized_focus = str(beat_focus or "").strip(" ，。；;")
        if normalized_focus:
            if normalized_focus in str(anchor_text or ""):
                line += f"，这一段延续“{normalized_focus}”"
            else:
                line += f"，这一段拍出“{normalized_focus}”"
        if spoken_note:
            line += f"，这一段口播：{spoken_note}"
        return line + "。"

    def _segment_visible_characters(self, segment: VideoSegment) -> list[str]:
        ordered: list[str] = []
        frame_groups = [segment.start_frame_characters, segment.end_frame_characters]
        if segment.requires_mid_frame:
            frame_groups.insert(1, segment.mid_frame_characters)
        for group in frame_groups:
            for name in group or []:
                normalized = str(name).strip()
                if normalized and normalized not in ordered:
                    ordered.append(normalized)
        if ordered:
            return ordered
        return [str(name).strip() for name in segment.involved_characters if str(name).strip()]

    def _seedance_transition_guard_lines(self, segment: VideoSegment) -> list[str]:
        lines: list[str] = []
        has_mid_anchor = self._segment_has_mid_anchor(segment)
        stage_beat_specs = self._segment_stage_beat_specs(
            segment,
            3 if has_mid_anchor else 2,
        )
        stage_spoken_notes = self._segment_stage_spoken_notes(
            segment=segment,
            stage_beat_specs=stage_beat_specs,
        )
        start_chars = segment.start_frame_characters
        mid_chars = segment.mid_frame_characters
        end_chars = segment.end_frame_characters
        start_anchor_line = self._seedance_frame_prompt_text(
            segment.start_frame_prompt,
            start_chars,
            segment.involved_characters,
        )
        mid_anchor_line = (
            self._seedance_frame_prompt_text(
                segment.mid_frame_prompt,
                mid_chars,
                segment.involved_characters,
            )
            if has_mid_anchor
            else ""
        )
        end_anchor_line = self._seedance_frame_prompt_text(
            segment.end_frame_prompt,
            end_chars,
            segment.involved_characters,
        )

        if has_mid_anchor and self._segment_uses_mid_insert_cut(segment):
            start_stage_label, start_stage_focus = stage_beat_specs[0]
            mid_stage_label, mid_stage_focus = stage_beat_specs[1]
            end_stage_label, end_stage_focus = stage_beat_specs[2]
            lines.append(
                self._build_motion_stage_line(
                    time_label=start_stage_label,
                    base=f"先按图片1建立“{start_anchor_line}”的主镜头关系，先把 {self._character_set_label(start_chars)} 的同框关系拍稳，不要刚开场就跳图",
                    beat_focus=start_stage_focus,
                    anchor_text=start_anchor_line,
                    spoken_note=stage_spoken_notes[0],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=mid_stage_label,
                    base=f"再短促切到图片2，对应“{mid_anchor_line}”，这里只拍 {self._character_set_label(mid_chars)} 的反应或局部动作，不要把它拍成少人版主镜头",
                    beat_focus=mid_stage_focus,
                    anchor_text=mid_anchor_line,
                    spoken_note=stage_spoken_notes[1],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=end_stage_label,
                    base=f"最后明确切回图片3，对应“{end_anchor_line}”，恢复 {self._character_set_label(end_chars)} 的主镜头关系并自然收束，不要到片尾最后一瞬间才跳回收束图",
                    beat_focus=end_stage_focus,
                    anchor_text=end_anchor_line,
                    spoken_note=stage_spoken_notes[2],
                )
            )
        elif has_mid_anchor and self._same_character_set(start_chars, mid_chars) and self._same_character_set(mid_chars, end_chars):
            start_stage_label, start_stage_focus = stage_beat_specs[0]
            mid_stage_label, mid_stage_focus = stage_beat_specs[1]
            end_stage_label, end_stage_focus = stage_beat_specs[2]
            lines.append(
                self._build_motion_stage_line(
                    time_label=start_stage_label,
                    base=f"先按图片1建立“{start_anchor_line}”的开场状态，把当前角色关系、站位和空间方向先拍稳",
                    beat_focus=start_stage_focus,
                    anchor_text=start_anchor_line,
                    spoken_note=stage_spoken_notes[0],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=mid_stage_label,
                    base=f"镜头继续自然推进到图片2，对应“{mid_anchor_line}”，中间要拍出可见的动作推进、走位变化或镜头推进，不要停成静帧",
                    beat_focus=mid_stage_focus,
                    anchor_text=mid_anchor_line,
                    spoken_note=stage_spoken_notes[1],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=end_stage_label,
                    base=f"最后稳定落到图片3，对应“{end_anchor_line}”，尾部要顺着前面的运动自然收束，不要临近片尾才突然跳图",
                    beat_focus=end_stage_focus,
                    anchor_text=end_anchor_line,
                    spoken_note=stage_spoken_notes[2],
                )
            )
        elif has_mid_anchor:
            start_stage_label, start_stage_focus = stage_beat_specs[0]
            mid_stage_label, mid_stage_focus = stage_beat_specs[1]
            end_stage_label, end_stage_focus = stage_beat_specs[2]
            lines.append(
                self._build_motion_stage_line(
                    time_label=start_stage_label,
                    base=f"先按图片1建立“{start_anchor_line}”的起步状态，把开场构图和角色起始关系拍清楚",
                    beat_focus=start_stage_focus,
                    anchor_text=start_anchor_line,
                    spoken_note=stage_spoken_notes[0],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=mid_stage_label,
                    base=f"再推进到图片2，对应“{mid_anchor_line}”，要把 {self._character_set_label(start_chars)} 到 {self._character_set_label(mid_chars)} 的入画、靠近、让位、转身或镜头重构过程拍清楚",
                    beat_focus=mid_stage_focus,
                    anchor_text=mid_anchor_line,
                    spoken_note=stage_spoken_notes[1],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=end_stage_label,
                    base=f"最后稳定落到图片3，对应“{end_anchor_line}”，收束前先完成 {self._character_set_label(mid_chars)} 到 {self._character_set_label(end_chars)} 的站位与构图变化",
                    beat_focus=end_stage_focus,
                    anchor_text=end_anchor_line,
                    spoken_note=stage_spoken_notes[2],
                )
            )
        elif self._same_character_set(start_chars, end_chars):
            start_stage_label, start_stage_focus = stage_beat_specs[0]
            end_stage_label, end_stage_focus = stage_beat_specs[1]
            lines.append(
                self._build_motion_stage_line(
                    time_label=start_stage_label,
                    base=f"先按图片1建立“{start_anchor_line}”的开场状态，把当前角色和空间关系先拍稳",
                    beat_focus=start_stage_focus,
                    anchor_text=start_anchor_line,
                    spoken_note=stage_spoken_notes[0],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=end_stage_label,
                    base=f"在同一组角色和空间里连续推进，最后落到图片2的“{end_anchor_line}”，中间要拍出可见动作推进，不要在片尾突然跳变",
                    beat_focus=end_stage_focus,
                    anchor_text=end_anchor_line,
                    spoken_note=stage_spoken_notes[1],
                )
            )
        else:
            start_stage_label, start_stage_focus = stage_beat_specs[0]
            end_stage_label, end_stage_focus = stage_beat_specs[1]
            lines.append(
                self._build_motion_stage_line(
                    time_label=start_stage_label,
                    base=f"先按图片1建立“{start_anchor_line}”的开场状态，把起步构图和角色初始位置拍清楚",
                    beat_focus=start_stage_focus,
                    anchor_text=start_anchor_line,
                    spoken_note=stage_spoken_notes[0],
                )
            )
            lines.append(
                self._build_motion_stage_line(
                    time_label=end_stage_label,
                    base=f"再把角色增减、入画、靠近或构图变化拍成连续过程，最后落到图片2的“{end_anchor_line}”，不要片尾突然换人或换构图",
                    beat_focus=end_stage_focus,
                    anchor_text=end_anchor_line,
                    spoken_note=stage_spoken_notes[1],
                )
            )
        if (
            has_mid_anchor
            and self._segment_uses_mid_insert_cut(segment)
            and self._same_character_set(start_chars, end_chars)
            and not self._same_character_set(start_chars, mid_chars)
        ):
            lines.append(
                f"插入镜头：图片2 只切 {self._character_set_label(mid_chars)} 的反应或局部动作，切完必须回到图片3 的主镜头关系。"
            )
        if has_mid_anchor and not self._same_character_set(start_chars, mid_chars):
            lines.append(
                "角色变化：图片1 为 "
                f"{self._character_set_label(start_chars)}，图片2 为 {self._character_set_label(mid_chars)}。"
                "人数或角色集合变化时，必须拍出真实入画、切入、靠近或让位过程。"
            )
        if has_mid_anchor and not self._same_character_set(mid_chars, end_chars):
            lines.append(
                "角色变化：图片2 为 "
                f"{self._character_set_label(mid_chars)}，图片3 为 {self._character_set_label(end_chars)}。"
                "尾部收束前先完成站位与构图变化，再稳定落到图片3。"
            )
        if not has_mid_anchor and not self._same_character_set(start_chars, end_chars):
            lines.append(
                "角色变化：图片1 为 "
                f"{self._character_set_label(start_chars)}，图片2 为 {self._character_set_label(end_chars)}。"
                "必须把角色增减、站位变化和景别变化拍成连续过程。"
            )
        return lines

    def _seedance_scene_transition_lines(
        self,
        segment: VideoSegment,
        scene: VideoScene | None,
    ) -> list[str]:
        if scene is None or segment.scene_id.strip() != scene.scene_id.strip():
            return []
        contract = scene.scene_transition_contract
        previous_scene_id = str(contract.previous_scene_id or "").strip()
        if not previous_scene_id:
            return []
        if scene.segments and segment.segment_id.strip() != scene.segments[0].segment_id.strip():
            return []

        focus_seconds = max(int(contract.transition_focus_seconds or 0), 1)
        entry_match = str(contract.next_scene_entry_match or "").strip()
        bridge_action = str(contract.bridge_action or "").strip()
        visual_bridge = str(contract.visual_bridge or "").strip()
        carry_over = [str(item).strip() for item in contract.carry_over_elements if str(item).strip()]
        screen_direction_policy = str(contract.screen_direction_policy or "").strip()
        lines = [
            "跨场承接：这是当前 scene 的首段，开场先承接上一场尾部，不要把图片1 当成重新开场。",
        ]
        if entry_match:
            lines.append(f"跨场承接：前 {focus_seconds} 秒先把图片1 长成“{entry_match}”。")
        if bridge_action:
            lines.append(f"跨场承接：随后按“{bridge_action}”推进，再稳定落到后续关键图。")
        if visual_bridge:
            lines.append(f"视觉过桥：{visual_bridge}")
        if carry_over:
            lines.append("延续元素：" + "、".join(carry_over[:4]))
        if screen_direction_policy:
            lines.append(f"方向：{screen_direction_policy}")
        audio_bridge_line = self._scene_transition_audio_bridge_line(contract.audio_bridge)
        if audio_bridge_line:
            lines.append(audio_bridge_line)
        return lines

    def _scene_transition_audio_bridge_line(self, audio_bridge: str) -> str:
        normalized = str(audio_bridge or "").strip().lower()
        if normalized == "ambient_bridge":
            return "音频承接：开头先延续上一场环境底噪或空间尾韵，再自然过渡到当前场环境。"
        if normalized == "dialogue_carry":
            return "音频承接：如果有说话声、呼吸或停顿，先延续上一场尾部余韵，再进入当前场口播。"
        if normalized == "music_hold":
            return "音频承接：音乐和情绪先接住上一场尾韵，不要在开头突然换成完全不同的段落。"
        return ""

    def _build_seedance_clip_prompt(
        self,
        segment: VideoSegment,
        *,
        scene: VideoScene | None = None,
    ) -> str:
        speech_budget = segment.duration_seconds * self.SPEECH_CHARS_PER_SECOND
        narration = str(segment.narration or "").strip()
        dialogue_lines = [
            str(line).strip()
            for line in segment.dialogue_lines
            if str(line).strip()
        ]
        subtitle_lines = [
            str(line).strip()
            for line in (
                segment.subtitle_lines
                or self._build_subtitle_lines(
                    narration=narration,
                    dialogue_lines=dialogue_lines,
                    timed_beats=segment.timed_beats,
                )
            )
            if str(line).strip()
        ]
        sound_effects = self._sanitize_segment_sound_effects(
            segment.sound_effects,
            scene_bible=segment.scene_bible,
            prop_continuity=self._shot_state_value(segment.shot_state, "prop_continuity"),
        )
        has_spoken_content = bool(narration or dialogue_lines or subtitle_lines)
        has_mid_anchor = self._segment_has_mid_anchor(segment)
        lines = [
            f"请生成带原生音频的中文剧情短视频片段，时长 {segment.duration_seconds} 秒。",
        ]
        if has_spoken_content:
            lines.append(
                f"口播预算：若有对白或旁白，总量控制在约 {speech_budget} 字以内，所有口播必须在片尾前自然说完。"
            )
        else:
            lines.append("本段无对白、无旁白、无字幕，只保留环境音、拟音和音乐。")

        lines.append("参考图：")
        start_anchor_line = self._seedance_frame_prompt_text(
            segment.start_frame_prompt,
            segment.start_frame_characters,
            segment.involved_characters,
        )
        if start_anchor_line:
            lines.append(f"- 图片1：{start_anchor_line}")
        if has_mid_anchor:
            lines.append(
                "- 图片2："
                + self._seedance_frame_prompt_text(
                    segment.mid_frame_prompt,
                    segment.mid_frame_characters,
                    segment.involved_characters,
                )
            )
        end_anchor_line = self._seedance_frame_prompt_text(
            segment.end_frame_prompt,
            segment.end_frame_characters,
            segment.involved_characters,
        )
        if end_anchor_line:
            end_image_label = "图片3" if has_mid_anchor else "图片2"
            lines.append(f"- {end_image_label}：{end_anchor_line}")
        lines.extend(self._seedance_transition_guard_lines(segment))
        lines.extend(self._seedance_scene_transition_lines(segment, scene))
        if narration:
            lines.append(f"旁白：{narration}")
        if dialogue_lines:
            lines.append("对白：")
            lines.extend(f"- {line}" for line in dialogue_lines)
        if has_spoken_content and segment.character_voice_notes:
            lines.append("角色音色：")
            lines.extend(f"- {item}" for item in segment.character_voice_notes)
        if sound_effects:
            lines.append("环境音/拟音：" + "；".join(sound_effects))
        if segment.music_direction:
            lines.append(f"音乐：{segment.music_direction}")
        if segment.timed_beats:
            lines.append("时间节拍：" + "；".join(segment.timed_beats))
        if self.seedance_config.subtitle_mode == "burned_in":
            if subtitle_lines:
                lines.append(f"硬字幕样式：{self.seedance_config.subtitle_style}")
                lines.append("硬字幕文案：")
                lines.extend(f"- {item}" for item in subtitle_lines)
                lines.append("请把上述字幕直接烧录到画面底部，不要输出外挂字幕文件；字幕必须和实际口播同步，不要提前出字。")
            else:
                lines.append("字幕约束：本段没有可烧录字幕，不要生成硬字幕、外挂字幕或画面内文字。")
        else:
            if has_spoken_content:
                lines.append("要求口播、对白、环境音与镜头动作自然同步，不要额外添加字幕。")
            else:
                lines.append("本段不要生成任何字幕或人声。")
        if has_spoken_content:
            lines.append(
                "一致性要求：同一角色跨镜头保持稳定音色、脸部身份、年龄感和体型，不要突然变声或换脸。"
            )
        else:
            lines.append(
                "一致性要求：同一角色跨镜头保持稳定脸部身份、年龄感和体型，不要突然换脸。"
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
