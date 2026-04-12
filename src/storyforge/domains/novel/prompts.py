from __future__ import annotations

from storyforge.domains.novel.contracts import ChapterPlan, DraftChapter, StoryBrief, StoryOutline


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


def build_character_system_prompt() -> str:
    return (
        "你是角色设计 Agent。"
        "请输出可直接进入角色图生成和后续章节写作的角色卡，"
        "尤其要保证角色的欲望、冲突、外观和声音都高度可识别。"
    )


def build_character_user_prompt(brief: StoryBrief, architecture_summary: str) -> str:
    participation_rule = (
        "每个角色只需要服务当前短篇，不要为了长线连载额外扩展角色"
        if brief.chapter_count <= 1
        else "每个角色都要能持续参与多个章节"
    )
    dual_lead_rule = (
        "这是明显依赖双人关系推进的故事，至少输出 2 个核心角色，并明确两人的关系张力与互动目标"
        if _brief_requires_dual_leads(brief)
        else "根据故事需要决定核心角色数量，但不要只给没有互动对象的孤立角色"
    )
    gender_pair_rule = (
        "如果这是告白、恋爱、暧昧、情侣、前任、重逢类关系故事，且 brief 没有明确说明同性关系，则前两名核心角色默认按一男一女设计，不要输出两个男核心角色或两个女核心角色"
        if _brief_prefers_male_female_pair(brief)
        else "角色性别按故事需要设计，但必须明确、稳定、可用于后续生图"
    )
    return f"""
请基于以下小说信息，设计主要角色阵容。

- 标题：{brief.title_hint}
- 类型：{brief.genre}
- 语气：{brief.tone}
- 项目底稿：{architecture_summary}
- 风格关键词：{", ".join(brief.style_keywords) if brief.style_keywords else "无"}

要求：
1. 角色之间形成互补和对冲
2. 角色外观与气质可直接用于角色图 prompt
3. {participation_rule}
4. 每个角色都要输出一句 voice_style 总结
5. 每个角色都要输出结构化 voice_profile，至少包含 timbre、speaking_rate、emotional_baseline、accent_or_texture、dialogue_delivery、forbidden_voice_changes
6. forbidden_voice_changes 必须明确写出不能出现的变声、年龄感漂移、语速漂移或口音漂移
7. 每个角色必须明确输出 gender 字段，角色图 prompt 中也必须写清性别、年龄段和体型，避免文生图随机偏差
8. {dual_lead_rule}
9. {gender_pair_rule}
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
) -> str:
    beat_rule = (
        "单章短篇只规划 3-5 个核心节拍，确保后续正文短小完整"
        if brief.chapter_count <= 1
        else "每章至少拆出多个节拍，便于转成视频片段"
    )
    dual_scene_rule = (
        "如果项目核心是告白、表白、对峙、争吵或双人对话，相关章节的 featured_characters 必须覆盖互动双方"
        if _brief_requires_dual_leads(brief)
        else "featured_characters 必须覆盖该章真正推动事件的角色"
    )
    return f"""
请为以下项目设计完整章节规划。

- 标题：{brief.title_hint}
- 类型：{brief.genre}
- 章节数：{brief.chapter_count}
- 项目底稿：{architecture_summary}
- 角色阵容：{character_summary}
- 必须包含：{", ".join(brief.must_include) if brief.must_include else "无"}

要求：
1. 每章都要有清晰目标和冲突
2. {beat_rule}
3. 章末必须给出强钩子
4. {dual_scene_rule}
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
    return f"""
请根据以下内容生成章节草稿。

- 小说标题：{outline.title}
- premise：{outline.premise}
- 主题：{outline.theme}
- 类型：{brief.genre}
- 风格：{brief.tone}
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
2. {short_form_rule}
3. 保留适合拆视频的视觉锚点
4. 重点角色对白要保持各自 voice_profile，不要所有人说话像同一个人
5. 严格控制篇幅，不要超过本章字数允许范围；如果信息过多，优先压缩环境描写和解释性背景
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


def _project_scope(brief: StoryBrief) -> str:
    if brief.chapter_count <= 1 or brief.total_word_target <= 1500:
        return "一篇短小完整的单章短篇"
    return "一个可持续展开的小说项目"


def _chapter_word_target(brief: StoryBrief) -> int:
    chapter_count = max(1, brief.chapter_count)
    return max(120, round(brief.total_word_target / chapter_count))


def _brief_requires_dual_leads(brief: StoryBrief) -> bool:
    text = " ".join(
        [
            brief.title_hint,
            brief.idea,
            brief.genre,
            brief.tone,
            " ".join(brief.must_include),
            " ".join(brief.style_keywords),
        ]
    )
    keywords = (
        "告白",
        "表白",
        "暗恋",
        "恋人",
        "情侣",
        "前任",
        "重逢",
        "求婚",
        "情书",
        "约会",
        "夫妻",
        "对峙",
        "争吵",
        "谈判",
        "审问",
        "质问",
        "双人",
        "对话",
    )
    return any(keyword in text for keyword in keywords)


def _brief_prefers_male_female_pair(brief: StoryBrief) -> bool:
    if not _brief_requires_dual_leads(brief):
        return False
    text = " ".join(
        [
            brief.title_hint,
            brief.idea,
            brief.genre,
            brief.tone,
            " ".join(brief.must_include),
            " ".join(brief.style_keywords),
        ]
    )
    same_gender_keywords = (
        "双男",
        "双女",
        "男男",
        "女女",
        "耽美",
        "百合",
        "bl",
        "gl",
        "同性",
        "男同",
        "女同",
    )
    return not any(keyword.lower() in text.lower() for keyword in same_gender_keywords)
