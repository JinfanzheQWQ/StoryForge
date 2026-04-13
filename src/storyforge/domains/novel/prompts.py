from __future__ import annotations

from storyforge.domains.novel.contracts import ChapterPlan, DraftChapter, StoryBrief, StoryOutline
from storyforge.domains.novel.schemas import CastAnalysisSchema, CastSlotSchema


def build_architect_system_prompt() -> str:
    return (
        "你是小说总策划。"
        "你的职责是先搭好故事引擎、主题、设定和视觉母题，"
        "确保这个项目既适合小说阅读，也适合拆成短视频片段。"
    )


def build_architect_user_prompt(brief: StoryBrief) -> str:
    project_scope = _project_scope(brief)
    return f"""
请把以下创意 brief 提炼成{project_scope}底稿。

- 标题参考：{brief.title_hint}
- 核心创意：{brief.idea}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 目标读者：{brief.target_audience}
- 章节数：{brief.chapter_count}
- 总字数目标：{brief.total_word_target}
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}

要求：
1. 明确世界与舞台
2. 明确故事引擎如何服务当前篇幅，不要把短篇强行扩写成长篇连载
3. 给出稳定的视觉母题和语气控制点
""".strip()


def build_cast_system_prompt() -> str:
    return (
        "你是 Cast Analyzer。"
        "请先从 brief 中提炼角色层级、关系图和出场结构，"
        "不要开始命名角色，也不要直接写小说正文。"
    )


def build_cast_user_prompt(
    brief: StoryBrief,
    architecture_summary: str,
) -> str:
    return f"""
请先解析这个小说项目的 cast 结构。

- 标题参考：{brief.title_hint}
- 核心创意：{brief.idea}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 目标读者：{brief.target_audience}
- 章节数：{brief.chapter_count}
- 总字数目标：{brief.total_word_target}
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}
- 项目底稿：{architecture_summary}

要求：
1. 先从 brief 中抽取所有“不可替代的角色指代”，再判断这是单主角、双主角、双人关系带配角，还是群像，不要先入为主按固定双人模板输出
2. 所谓“不可替代的角色指代”，包括职业、亲属、身份、关系对象、证人、对手、盟友、掌握关键信息的人；例如“记者、昔日恋人、地下线人、地方势力继承人、退休警察”应拆成独立槽位，不能合并成“几名配角”
3. 只有在 brief 明确说明是同一人时才能合并指代；否则宁可保留多个 slot，也不要把两个剧情功能不同的人压成一个角色
4. 输出 recommended_core_cast_count，表示当前篇幅真正建议稳定展开的核心角色数；它应等于当前篇幅中必须稳定命名和持续使用的核心槽位数，而不是默认写 2
5. 输出 slots，每个 slot 代表一个角色槽位，而不是正式角色名
6. slot 的 brief_label 只能使用 brief 里已有指代，例如“告白的女生”“她的朋友”“班主任”“地下线人”，不要擅自起正式角色名
7. 每个 slot 都必须填写 source_evidence，写出 brief 中支撑这个槽位存在的短语或原文片段，方便后续 repair 校验
8. slot 必须区分 tier，例如 lead / core_support / supporting / minor；lead 是当前篇幅离开就无法成立的角色，core_support 是高频关键配角，supporting 是关键节点角色，minor 是一次性功能角色
9. slot 必须区分 story_function，例如 protagonist / love_interest / ally / antagonist / witness / mentor / handler / obstacle；不要把所有非主角都写成 ally
10. 如果 brief 存在明确关系双方，前两个高优先级 slot 必须保留给双方，并保持 brief 叙事顺序
11. 如果是“一个主角 + 多个围绕主角展开的关键角色”，应优先输出 single_lead_with_supporting_cast，而不是硬改成双主角
12. relationships 必须描述核心关系图，而不是重复写 slots 内容；要覆盖主角与关键配角之间真正驱动情节的关系
13. chapter_participation_rule 必须说明哪些层级角色需要持续出场，哪些只在关键节点出场
14. ordering_rule 必须说明后续角色表如何按 slot 顺序展开
15. cast_strategy 必须写成后续角色生成必须遵守的明确约束，尤其要说明哪些槽位绝不能丢
16. gender_hint 只有在 brief 给出明确线索时才填写“男”或“女”；没有线索就写“未指定”，不要靠职业或刻板印象瞎猜
17. 如果是恋爱、告白、暧昧、情侣、前任、重逢类故事，且 brief 没明确同性关系，可以设置 prefers_male_female_pair=true；但如果 brief 已给出性别线索，必须遵守
""".strip()


def build_character_system_prompt() -> str:
    return (
        "你是角色设计 Agent。"
        "请基于上游已经完成的 Cast Analysis 结果输出角色卡，"
        "尤其要保证角色的欲望、冲突、外观和声音都高度可识别。"
    )


def build_character_user_prompt(
    brief: StoryBrief,
    architecture_summary: str,
    cast_analysis: CastAnalysisSchema,
) -> str:
    participation_rule = (
        "每个角色只需要服务当前短篇，不要为了长线连载额外扩展角色"
        if brief.chapter_count <= 1
        else "每个角色都要能持续参与多个章节"
    )
    primary_slots = cast_analysis.primary_slots(2)
    if cast_analysis.explicit_counterpart:
        dual_lead_rule = (
            "这是明确的双人关系故事，characters 数组前两位必须就是这段关系的双方。"
            "不得只输出单主角，也不得把另一方降成背景板、旁白对象或“喜欢的人/对方”这类泛称。"
        )
    elif cast_analysis.requires_dual_leads:
        dual_lead_rule = (
            "这是明显依赖双人关系推进的故事，至少输出 2 个核心角色，并明确两人的关系张力与互动目标。"
        )
    else:
        dual_lead_rule = "根据 cast 结构展开角色，不要把所有配角都压成背景板，也不要凭空扩写过多核心角色。"
    gender_pair_rule = (
        "如果这是告白、恋爱、暧昧、情侣、前任、重逢类关系故事，且 brief 没有明确说明同性关系，则前两名核心角色默认按一男一女设计，不要输出两个男核心角色或两个女核心角色"
        if cast_analysis.prefers_male_female_pair
        else "角色性别按故事需要设计，但必须明确、稳定、可用于后续生图"
    )
    slot_mapping_rule = (
        "characters 中的每个角色都必须显式填写 cast_slot_id，并一一对应到上游 cast slots。"
    )
    slot_evidence_rule = "同时参考每个 slot 的 source_evidence，不要把多个 brief 指代压成一个角色。"
    counterpart_rule = (
        "前两名核心角色都要写清对另一方的态度、互动目标和关系风险；如果 cast slots 已明确双方顺序，前两位角色必须严格按 slot 优先级输出"
        if cast_analysis.explicit_counterpart
        else "每个角色都要写清自己与其他核心角色的关系和冲突，并与对应 slot 的 story_function 对齐"
    )
    minimum_character_rule = (
        f"至少输出 {max(1, cast_analysis.recommended_core_cast_count)} 个核心角色，不要低于上游 cast analysis 给出的数量"
    )
    slot_priority_rule = (
        "前两位角色必须对应最高优先级 slots："
        + " / ".join(
            f"{slot.slot_id}:{slot.brief_label}" for slot in primary_slots
        )
        if primary_slots
        else "按上游 slots 的 order_priority 顺序展开角色"
    )
    return f"""
请基于以下小说信息，设计主要角色阵容。

- 标题：{brief.title_hint}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 项目底稿：{architecture_summary}
- 上游 Cast Analysis：
{_build_cast_analysis_context(cast_analysis)}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}

要求：
1. 必须以上游 Cast Analysis 结果为准，不要自行减少核心角色数量，也不要改写高优先级 slot 顺序
2. {minimum_character_rule}
3. {slot_mapping_rule}
4. {slot_evidence_rule}
5. {slot_priority_rule}
6. 角色之间形成互补和对冲
7. 角色外观与气质可直接用于角色图 prompt
8. {participation_rule}
9. 每个角色都要输出一句 voice_style 总结
10. 每个角色都要输出结构化 voice_profile，至少包含 timbre、speaking_rate、emotional_baseline、accent_or_texture、dialogue_delivery、forbidden_voice_changes
11. forbidden_voice_changes 必须明确写出不能出现的变声、年龄感漂移、语速漂移或口音漂移
12. 每个角色必须明确输出 gender 字段，角色图 prompt 中也必须写清性别、年龄段和体型，避免文生图随机偏差
13. {dual_lead_rule}
14. {counterpart_rule}
15. {gender_pair_rule}
""".strip()


def build_chapter_planner_system_prompt() -> str:
    return (
        "你是章节规划 Agent。"
        "请把故事拆成强推进的章节蓝图，每章都要能独立产出一个或多个视频片段。"
    )


def build_chapter_planner_user_prompt(
    brief: StoryBrief,
    architecture_summary: str,
    character_summary: str,
    cast_analysis: CastAnalysisSchema,
) -> str:
    beat_rule = (
        "单章短篇只规划 3-5 个核心节拍，确保后续正文短小完整"
        if brief.chapter_count <= 1
        else "每章至少拆出多个节拍，便于转成视频片段"
    )
    if cast_analysis.explicit_counterpart:
        dual_scene_rule = (
            "这是双人关系故事，featured_characters 前两位必须优先放关系双方。"
            "凡是推进告白、重逢、对峙、和解、摊牌的章节，不得遗漏任意一方。"
        )
        interaction_rule = "相关章节的 goal、summary、beats 必须写出双方真实互动，不能只写单人心理活动。"
    elif cast_analysis.requires_dual_leads:
        dual_scene_rule = "如果项目核心是告白、表白、对峙、争吵或双人对话，相关章节的 featured_characters 必须覆盖互动双方。"
        interaction_rule = "双人推进章节必须让双方都实际参与事件，不要只保留一方。"
    else:
        dual_scene_rule = "featured_characters 必须覆盖该章真正推动事件的角色，至少先覆盖 lead 和 core_support 层。"
        interaction_rule = "章节摘要和节拍要准确反映 slot 对应角色的参与方式，不要让高优先级角色长期消失。"
    return f"""
请为以下项目设计完整章节规划。

- 标题：{brief.title_hint}
- 类型：{brief.genre}
- 章节数：{brief.chapter_count}
- 项目底稿：{architecture_summary}
- 上游 Cast Analysis：
{_build_cast_analysis_context(cast_analysis)}
- 角色阵容：{character_summary}
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}

要求：
1. 必须以上游 Cast Analysis 结果为准，不要擅自删掉高优先级 cast slots
2. 每章都要有清晰目标和冲突
3. {beat_rule}
4. 章末必须给出强钩子
5. {dual_scene_rule}
6. {interaction_rule}
""".strip()


def build_writer_system_prompt() -> str:
    return (
        "你是章节写作 Agent。"
        "请写出兼顾小说阅读感和影视化想象空间的章节草稿，"
        "不要空洞概述，要有真实场景、动作和情绪推进。"
    )


def build_writer_user_prompt(
    brief: StoryBrief,
    outline: StoryOutline,
    chapter: ChapterPlan,
    previous_chapters: list[DraftChapter],
    cast_analysis: CastAnalysisSchema,
) -> str:
    previous_summary = "\n".join(
        f"- 第 {item.number} 章：{item.summary}" for item in previous_chapters[-2:]
    ) or "无前文摘要"
    character_context = _build_character_context(outline, chapter.featured_characters)
    word_target = _chapter_word_target(brief)
    lower_bound = max(120, int(word_target * 0.8))
    upper_bound = max(lower_bound, int(word_target * 1.2))
    short_form_rule = (
        "这是单章短篇，必须在本章内完成一个完整微型故事，不要扩写成长篇开头。"
        if brief.chapter_count <= 1
        else "按章节规划推进长线故事，不要跳过本章核心冲突。"
    )
    interaction_rule = (
        "这是双人关系故事，本章必须让关系双方都实际出场并发生动作、对白或明确回应，不能只让另一方停留在回忆、旁白或代称里。"
        if cast_analysis.explicit_counterpart
        else "重点角色要以实际场景行动推动情节，并优先保证 lead 与 core_support 角色的存在感。"
    )
    return f"""
请根据以下内容生成章节草稿。

- 小说标题：{outline.title}
- premise：{outline.premise}
- 主题：{outline.theme}
- 类型：{brief.genre}
- 风格：{brief.tone}
- 上游 Cast Analysis：
{_build_cast_analysis_context(cast_analysis)}
- 前文摘要：
{previous_summary}
- 当前章节标题：{chapter.title}
- 本章目标：{chapter.goal}
- 本章摘要：{chapter.summary}
- 关键冲突：{chapter.key_conflict}
- 场景节拍：{", ".join(chapter.beats)}
- 重点角色：{", ".join(chapter.featured_characters) if chapter.featured_characters else "无"}
- 重点角色设定：
{character_context}
- 章末钩子：{chapter.cliffhanger}
- 本章字数硬目标：{word_target} 字，允许范围 {lower_bound}-{upper_bound} 字

要求：
1. 输出可以直接保存成 Markdown 章节
2. 必须延续上游 Cast Analysis 和章节规划，不要自行重写人物层级和关系结构
3. {short_form_rule}
4. 保留适合拆视频的视觉锚点
5. 重点角色对白要保持各自 voice_profile，不要所有人说话像同一个人
6. 严格控制篇幅，不要超过本章字数允许范围；如果信息过多，优先压缩环境描写和解释性背景
7. {interaction_rule}
""".strip()


def build_editor_system_prompt() -> str:
    return (
        "你是编辑审校 Agent。"
        "请检查故事在结构、角色一致性和视频改编潜力上的问题，"
        "输出可执行的修改建议。"
    )


def build_editor_user_prompt(
    brief: StoryBrief,
    outline: StoryOutline,
    chapters: list[DraftChapter],
) -> str:
    chapter_summary = "\n".join(f"- {item.title}: {item.summary}" for item in chapters)
    character_context = _build_character_context(outline)
    return f"""
请审校以下小说项目。

- 标题：{outline.title}
- 核心创意：{brief.idea}
- 类型：{brief.genre}
- 主题：{outline.theme}
- 视觉母题：{", ".join(outline.visual_motifs)}
- 角色声线与人设：
{character_context}
- 章节摘要：
{chapter_summary}

请重点检查：
1. 角色弧光是否连续
2. 每章悬念是否有效
3. 是否便于进一步拆成视频片段
4. 同一角色的对白声线、情绪基线和说话习惯是否稳定
""".strip()


def _build_character_context(
    outline: StoryOutline,
    featured_characters: list[str] | None = None,
) -> str:
    featured = set(featured_characters or [])
    selected = [
        item for item in outline.characters if not featured or item.name in featured
    ]
    if not selected:
        selected = list(outline.characters[:3])
    if not selected:
        return "- 无角色信息"

    lines: list[str] = []
    for item in selected:
        voice_profile = item.voice_profile
        forbidden = "、".join(voice_profile.forbidden_voice_changes) or "无"
        lines.append(
            f"- {item.name} | 性别：{item.gender} | 身份：{item.role} | 欲望：{item.desire} | "
            f"声音总结：{item.voice_style or voice_profile.resolved_voice_style()} | "
            f"音色：{voice_profile.timbre or '未指定'} | "
            f"语速：{voice_profile.speaking_rate or '未指定'} | "
            f"情绪基线：{voice_profile.emotional_baseline or '未指定'} | "
            f"口音/质感：{voice_profile.accent_or_texture or '未指定'} | "
            f"说话方式：{voice_profile.dialogue_delivery or '未指定'} | "
            f"禁止漂移：{forbidden}"
        )
    return "\n".join(lines)


def _build_cast_analysis_context(
    analysis: CastAnalysisSchema,
) -> str:
    lines = [
        f"- 故事形态：{analysis.story_shape}",
        f"- 建议核心角色数：{analysis.recommended_core_cast_count}",
        f"- 需要双主导角色：{'是' if analysis.requires_dual_leads else '否'}",
        f"- 明确关系对位：{'是' if analysis.explicit_counterpart else '否'}",
        f"- Cast 策略：{analysis.cast_strategy}",
        f"- 章节出场规则：{analysis.chapter_participation_rule}",
        f"- 排序规则：{analysis.ordering_rule}",
    ]
    for slot in analysis.primary_slots():
        lines.append(_build_cast_slot_line(slot))
    if analysis.relationships:
        relationship_lines = [
            f"{item.source_slot_id}->{item.target_slot_id}:{item.relationship_type}({item.summary})"
            for item in sorted(analysis.relationships, key=lambda item: item.priority)[:6]
        ]
        lines.append("- 关系图：" + "；".join(relationship_lines))
    return "\n".join(lines)


def _build_cast_slot_line(slot: CastSlotSchema) -> str:
    evidence = "、".join(slot.source_evidence) if slot.source_evidence else "无"
    return (
        f"- 槽位：{slot.slot_id} | 层级：{slot.tier} | 功能：{slot.story_function} | "
        f"brief 指代：{slot.brief_label} | 性别线索：{slot.gender_hint} | "
        f"证据：{evidence} | 目标：{slot.objective} | "
        f"必须出场：{'、'.join(slot.must_appear_in) if slot.must_appear_in else '无'}"
    )


def _project_scope(brief: StoryBrief) -> str:
    if brief.chapter_count <= 1 or brief.total_word_target <= 1500:
        return "一篇短小完整的单章短篇"
    return "一个可持续展开的小说项目"


def _chapter_word_target(brief: StoryBrief) -> int:
    chapter_count = max(1, brief.chapter_count)
    return max(120, round(brief.total_word_target / chapter_count))
