from __future__ import annotations

import re

from storyforge.domains.novel.contracts import DraftChapter, StoryBrief, StoryOutline
from storyforge.domains.novel.schemas import CastAnalysisSchema, CastSlotSchema


def build_architect_system_prompt() -> str:
    return (
        "你是小说总策划。"
        "你的职责是先搭好故事引擎、主题、设定和视觉母题，"
        "确保这个项目既适合小说阅读，也适合拆成短视频片段。"
        "这个阶段不是角色解析阶段，不要提前把角色数量、关系模板或命名方案钉死。"
    )


def build_architect_user_prompt(
    brief: StoryBrief,
    story_draft_context: str = "",
) -> str:
    project_scope = _project_scope(brief)
    if story_draft_context.strip():
        return f"""
请基于这部已经完成的小说正文，提炼出当前项目的结构化底稿。

- 标题参考：{brief.title_hint}
- 核心创意：{brief.idea}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 目标读者：{brief.target_audience}
- 章节数：{brief.chapter_count}
- 总字数目标：{brief.total_word_target}
- 已有小说正文：
{story_draft_context}

要求：
1. 以已有小说正文为事实基础，不要反过来用 brief 覆盖正文里已经成立的故事设定
2. 提炼出 title、premise、theme、setting、story_engine、visual_motifs、tone_notes
3. 这是分析阶段，不要重写小说，也不要输出章节正文
4. visual_motifs 和 tone_notes 要能服务后续角色图、场景图和视频镜头规划
""".strip()
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
4. 除非 brief 已明确写死，否则不要在这个阶段预设固定角色人数或固定双人模板；角色事实以后续小说草稿为准
""".strip()


def build_story_drafter_system_prompt() -> str:
    return (
        "你是小说起稿 Agent。"
        "请先根据 brief 和项目底稿写出一版完整小说草稿。"
        "这版草稿会成为后续角色解析、角色设定和视频分段的事实基础。"
    )


def build_story_drafter_user_prompt(
    brief: StoryBrief,
    architecture_summary: str,
) -> str:
    chapter_word_target = _chapter_word_target(brief)
    return f"""
请先为这个项目生成一版完整小说草稿。

- 标题参考：{brief.title_hint}
- 核心创意：{brief.idea}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 目标读者：{brief.target_audience}
- 章节数：{brief.chapter_count}
- 总字数目标：{brief.total_word_target}
- 每章参考字数：约 {chapter_word_target} 字
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}
- 项目底稿：{architecture_summary}

要求：
1. 必须生成完整故事草稿，而不是设定说明或提纲
2. 严格输出 {brief.chapter_count} 章，每章都要有 title、summary、markdown
3. 每章 summary 必须写清这一章真实发生了什么、谁参与了事件、关系如何变化
4. 每章 markdown 必须是可读的小说正文，不要只写提纲句
5. 这版草稿是后续角色解析和章节分段的事实依据，所以关键角色必须在草稿里真实出场，而不是只停留在设定里
6. 角色名字此阶段可以先定下来，但后续允许基于角色卡再做统一修订
7. 每章都要保留适合转视频的视觉抓手和连续性线索
8. 如果核心事件天然涉及双方或多方参与，例如告白、对峙、交易、分别、重逢、合作破局，则相关角色都必须在草稿里真实参与事件，不能把双人或多人事件压成单人独白
""".strip()


def build_cast_system_prompt() -> str:
    return (
        "你是 Cast Analyzer。"
        "请从已经生成的小说草稿中提炼角色层级、关系图和出场结构，"
        "不要开始命名角色，也不要直接写小说正文。"
    )


def build_cast_user_prompt(
    brief: StoryBrief,
    architecture_summary: str,
    story_draft_context: str = "",
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
- 已生成小说草稿：
{story_draft_context or "无"}

要求：
1. 以已生成小说草稿为主，brief 和项目底稿只作为边界约束，不要反过来用 brief 覆盖小说草稿里已经成立的角色结构
2. 先从小说草稿中抽取所有“不可替代的角色指代”，再判断这是单主角、双主角、双人关系带配角，还是群像，不要先入为主按固定双人模板输出
3. 所谓“不可替代的角色指代”，包括职业、亲属、身份、关系对象、证人、对手、盟友、掌握关键信息的人；例如“记者、昔日恋人、地下线人、地方势力继承人、退休警察”应拆成独立槽位，不能合并成“几名配角”
4. 只有在小说草稿明确说明是同一人时才能合并指代；否则宁可保留多个 slot，也不要把两个剧情功能不同的人压成一个角色
5. 输出 recommended_core_cast_count，表示当前篇幅真正建议稳定展开的核心角色数；它应等于当前篇幅中必须稳定命名和持续使用的核心槽位数，而不是默认写 2
6. 输出 slots，每个 slot 代表一个角色槽位，而不是正式角色名
7. slot 的 brief_label 优先使用小说草稿里已经出现的角色指代或称呼；如果草稿没有稳定称呼，再回退到 brief 指代
8. 每个 slot 都必须填写 source_evidence，写出小说草稿或 brief 中支撑这个槽位存在的短语或原文片段，方便后续 repair 校验
9. slot 必须区分 tier，例如 lead / core_support / supporting / minor；lead 是当前篇幅离开就无法成立的角色，core_support 是高频关键配角，supporting 是关键节点角色，minor 是一次性功能角色
10. slot 必须区分 story_function，例如 protagonist / love_interest / ally / antagonist / witness / mentor / handler / obstacle；不要把所有非主角都写成 ally
11. 如果小说草稿存在明确关系双方，前两个高优先级 slot 必须保留给双方，并保持草稿叙事顺序
12. 如果是“一个主角 + 多个围绕主角展开的关键角色”，应优先输出 single_lead_with_supporting_cast，而不是硬改成双主角
13. relationships 必须描述核心关系图，而不是重复写 slots 内容；要覆盖主角与关键配角之间真正驱动情节的关系
14. chapter_participation_rule 必须说明哪些层级角色需要持续出场，哪些只在关键节点出场
15. ordering_rule 必须说明后续角色表如何按 slot 顺序展开
16. cast_strategy 必须写成后续角色生成必须遵守的明确约束，尤其要说明哪些槽位绝不能丢
17. gender_hint 优先依据小说草稿中的明确性别线索；没有线索才回退到 brief；都没有就写“未指定”
18. 如果是恋爱、告白、暧昧、情侣、前任、重逢类故事，且小说草稿与 brief 都没明确同性关系，可以设置 prefers_male_female_pair=true；但如果草稿已给出性别线索，必须遵守
19. source_evidence 必须尽量直接引用小说草稿里的短语、称呼或原文片段，不能写“关系见证者”“外部阻力来源”“补位角色”这类抽象概括来冒充证据
20. 如果某个角色没有在小说草稿中稳定出场，或无法用 source_evidence 明确指向，就不要为它创建 slot；宁可少，不要为了凑阵容补人
21. 对单章或短篇故事，如果小说草稿稳定成立的关键角色只有 1 到 2 个，就只输出这 1 到 2 个核心槽位，不要额外补 core_support
22. recommended_core_cast_count 必须等于当前真正需要稳定命名建卡的核心槽位数，不能大于 slots 数量，也不要为了后续扩写而抬高
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
    story_draft_context: str = "",
) -> str:
    participation_rule = (
        "每个角色只需要服务当前短篇，不要为了长线连载额外扩展角色"
        if brief.chapter_count <= 1
        else "每个角色都要能持续参与多个章节"
    )
    intended_slots = cast_analysis.primary_slots(
        max(1, cast_analysis.recommended_core_cast_count)
    )
    primary_slots = intended_slots[:2]
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
    intended_slot_ids = [slot.slot_id for slot in intended_slots]
    intended_slot_summary = (
        "；".join(
            f"{slot.slot_id}={slot.brief_label}（证据：{' / '.join(slot.source_evidence)}）"
            for slot in intended_slots
        )
        if intended_slots
        else "无"
    )
    exact_character_rule = (
        f"characters 数组长度必须恰好等于 {len(intended_slot_ids)}，不多不少。"
    )
    slot_mapping_rule = (
        "characters 中的每个角色都必须显式填写 cast_slot_id，并与上游 cast slots 一一对应。"
    )
    slot_set_rule = (
        "只允许输出这些 cast_slot_id："
        + ("、".join(intended_slot_ids) if intended_slot_ids else "无")
        + "；不得遗漏，不得新增，也不得重复。"
    )
    slot_evidence_rule = (
        "同时参考每个 slot 的 source_evidence，不要把多个指代压成一个角色，也不要把不存在于上游 slots 的人写进角色表。"
    )
    counterpart_rule = (
        "前两名核心角色都要写清对另一方的态度、互动目标和关系风险；如果 cast slots 已明确双方顺序，前两位角色必须严格按 slot 优先级输出"
        if cast_analysis.explicit_counterpart
        else "每个角色都要写清自己与其他核心角色的关系和冲突，并与对应 slot 的 story_function 对齐"
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
- 已生成小说草稿：
{story_draft_context or "无"}
- 上游 Cast Analysis：
{_build_cast_analysis_context(cast_analysis)}
- 本次必须严格覆盖的 slots：
{intended_slot_summary}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}

要求：
1. 必须以上游 Cast Analysis 结果为准，并以已生成小说草稿为事实基础，不要凭空发明与草稿不一致的新核心角色
2. {exact_character_rule}
3. {slot_mapping_rule}
4. {slot_set_rule}
5. {slot_evidence_rule}
6. {slot_priority_rule}
7. 角色之间形成互补和对冲
8. 角色外观与气质可直接用于角色图 prompt
9. {participation_rule}
10. 每个角色都要输出一句 voice_style 总结
11. 每个角色都要输出结构化 voice_profile，至少包含 timbre、speaking_rate、emotional_baseline、accent_or_texture、dialogue_delivery、forbidden_voice_changes
12. forbidden_voice_changes 必须明确写出不能出现的变声、年龄感漂移、语速漂移或口音漂移
13. 每个角色必须明确输出 gender 字段，角色图 prompt 中也必须写清性别、年龄段和体型，避免文生图随机偏差
14. 所有核心角色名必须唯一，不得出现两个角色使用同一个正式名字，也不要只靠“她 / 他 / 对方”充当角色名
15. 所有 cast_slot_id 必须唯一，严禁出现两个角色共用同一个 cast_slot_id
16. 如果某个 slot 在小说草稿里找不到对应角色，就应该回到该 slot 的 source_evidence 去还原同一人，而不是凭空新造一个名字
17. {dual_lead_rule}
18. {counterpart_rule}
19. {gender_pair_rule}
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
    story_draft_context: str = "",
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
- 已生成小说草稿：
{story_draft_context or "无"}
- 上游 Cast Analysis：
{_build_cast_analysis_context(cast_analysis)}
- 角色阵容：{character_summary}
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}

要求：
1. 必须以已生成小说草稿为事实基础，不要重新发明章节顺序或核心事件
2. 必须以上游 Cast Analysis 结果为准，不要擅自删掉高优先级 cast slots
3. 每章都要有清晰目标和冲突
4. 要把小说草稿中的真实事件，整理成适合后续视频拆分的结构化章节蓝图
5. {beat_rule}
6. 章末必须给出强钩子
7. {dual_scene_rule}
8. {interaction_rule}
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


def build_story_draft_context(chapters: list[DraftChapter]) -> str:
    if not chapters:
        return "- 无小说草稿"

    lines: list[str] = []
    for item in chapters:
        excerpt = _markdown_excerpt(item.markdown, limit=260)
        lines.append(
            f"- 第 {item.number} 章《{item.title}》\n"
            f"  摘要：{item.summary}\n"
            f"  节选：{excerpt}"
        )
    return "\n".join(lines)


def _project_scope(brief: StoryBrief) -> str:
    if brief.chapter_count <= 1 or brief.total_word_target <= 1500:
        return "一篇短小完整的单章短篇"
    return "一个可持续展开的小说项目"


def _chapter_word_target(brief: StoryBrief) -> int:
    chapter_count = max(1, brief.chapter_count)
    return max(120, round(brief.total_word_target / chapter_count))


def _markdown_excerpt(markdown: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", markdown).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."
