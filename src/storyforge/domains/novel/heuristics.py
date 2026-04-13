from __future__ import annotations

import re

from storyforge.domains.novel.contracts import StoryBrief


MULTI_CHARACTER_KEYWORDS = (
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
    "两人",
    "二人",
    "彼此",
    "互相",
    "相互",
    "母女",
    "父子",
    "姐妹",
    "兄弟",
    "师徒",
    "搭档",
    "同桌",
    "室友",
)

EXPLICIT_COUNTERPART_MARKERS = (
    "告白",
    "表白",
    "求婚",
    "重逢",
    "情侣",
    "夫妻",
    "对峙",
    "争吵",
    "谈判",
    "审问",
    "质问",
    "一对",
    "两人",
    "二人",
    "双方",
    "彼此",
    "互相",
    "相互",
    "男女主",
    "男主和女主",
    "女主和男主",
    "他和她",
    "她和他",
    "男生和女生",
    "女生和男生",
    "少年与少女",
    "少女与少年",
)

SAME_GENDER_KEYWORDS = (
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

DIRECTED_INTERACTION_PATTERN = re.compile(
    r"(?:一个|一名|一位|某个|男生|女生|男人|女人|少年|少女|男主|女主|主角|他|她)?"
    r"[^，。；!?！？]{0,18}"
    r"(?:向|对|给|跟|和|与|同)"
    r"[^，。；!?！？]{1,24}"
    r"(?:告白|表白|求婚|道歉|重逢|告别|摊牌|对峙|争吵|谈判|审问|质问|合作|约会|相认|诀别|表露心意|说出真相)"
)

PAIRING_PATTERN = re.compile(
    r"(?:他和她|她和他|男女主|男主和女主|女主和男主|男生和女生|女生和男生|"
    r"少年与少女|少女与少年|一个[^，。；!?！？]{0,12}另一个|一对[^，。；!?！？]{0,10}|"
    r"两位[^，。；!?！？]{0,10}|两人[^，。；!?！？]{0,10}|二人[^，。；!?！？]{0,10})"
)

ORDERED_GENDER_TOKENS = (
    ("女主", "女"),
    ("男主", "男"),
    ("女生", "女"),
    ("男生", "男"),
    ("女孩", "女"),
    ("男孩", "男"),
    ("女人", "女"),
    ("男人", "男"),
    ("少女", "女"),
    ("少年", "男"),
    ("妻子", "女"),
    ("丈夫", "男"),
    ("她", "女"),
    ("他", "男"),
)

ROLE_LABEL_SUFFIXES = (
    "地方势力继承人",
    "掌握档案的退休警察",
    "退休警察",
    "青梅竹马",
    "未婚妻",
    "未婚夫",
    "档案管理员",
    "继承人",
    "经纪人",
    "研究员",
    "程序员",
    "工程师",
    "班主任",
    "青少年",
    "恋人",
    "前任",
    "线人",
    "记者",
    "警察",
    "警探",
    "侦探",
    "老师",
    "同学",
    "室友",
    "朋友",
    "母亲",
    "父亲",
    "哥哥",
    "姐姐",
    "妹妹",
    "弟弟",
    "丈夫",
    "妻子",
    "女儿",
    "儿子",
    "搭档",
    "队友",
    "保镖",
    "嫌疑人",
    "证人",
    "医生",
    "律师",
    "导演",
    "主播",
    "助理",
    "老板",
    "总监",
    "投资人",
    "歌手",
    "演员",
    "画家",
    "作家",
    "教授",
    "学生",
    "女生",
    "男生",
    "女人",
    "男人",
    "少女",
    "少年",
)

ROLE_LABEL_HEAD_PATTERN = re.compile(
    r"^(?:一名|一位|一个|某个|这名|这位|那名|那位)?"
    r"(?P<label>(?:[^，。；：:!?！？、]{0,8}的)?(?:"
    + "|".join(re.escape(item) for item in ROLE_LABEL_SUFFIXES)
    + r"))"
)

ROLE_LABEL_ANY_PATTERN = re.compile(
    r"(?P<label>(?:[^，。；：:!?！？、]{0,8}的)?(?:"
    + "|".join(re.escape(item) for item in ROLE_LABEL_SUFFIXES)
    + r"))"
)

CLAUSE_SPLIT_PATTERN = re.compile(r"[，。；：:!?！？]")
ROLE_LIST_SPLIT_PATTERN = re.compile(r"[、]|以及|(?:和|与|及)")
ROLE_LABEL_PREFIX_PATTERN = re.compile(r"^(?:一名|一位|一个|某个|这名|这位|那名|那位)")
ROLE_LABEL_TRIM_PATTERN = re.compile(r"(?:相继|先后|逐步)?(?:卷入|登场|出现|介入|参与|现身).*$")
COUNTERPART_TAIL_TRIM_PATTERN = re.compile(
    r"(?:告白|表白|求婚|道歉|重逢|告别|摊牌|对峙|争吵|谈判|审问|质问|合作|约会|相认|诀别|表露心意|说出真相).*$"
)


def build_brief_text(brief: StoryBrief) -> str:
    return " ".join(
        [
            brief.title_hint,
            brief.idea,
            brief.genre,
            brief.tone,
            " ".join(brief.must_include),
            " ".join(brief.style_keywords),
        ]
    )


def text_requires_multiple_core_characters(text: str) -> bool:
    compact = _compact_text(text)
    return text_requires_explicit_counterpart(compact) or any(
        keyword in compact for keyword in MULTI_CHARACTER_KEYWORDS
    )


def text_requires_explicit_counterpart(text: str) -> bool:
    compact = _compact_text(text)
    if any(marker in compact for marker in EXPLICIT_COUNTERPART_MARKERS):
        return True
    return bool(
        DIRECTED_INTERACTION_PATTERN.search(compact) or PAIRING_PATTERN.search(compact)
    )


def brief_requires_dual_leads(brief: StoryBrief) -> bool:
    return text_requires_multiple_core_characters(build_brief_text(brief))


def brief_requires_explicit_counterpart(brief: StoryBrief) -> bool:
    return text_requires_explicit_counterpart(build_brief_text(brief))


def brief_prefers_male_female_pair(brief: StoryBrief) -> bool:
    if not brief_requires_dual_leads(brief):
        return False
    lower = build_brief_text(brief).lower()
    return not any(keyword in lower for keyword in SAME_GENDER_KEYWORDS)


def infer_primary_character_genders(brief: StoryBrief) -> tuple[str, str] | None:
    if not brief_prefers_male_female_pair(brief):
        return None

    compact = _compact_text(build_brief_text(brief))
    matches: list[tuple[int, str]] = []
    for token, gender in ORDERED_GENDER_TOKENS:
        for match in re.finditer(re.escape(token), compact):
            matches.append((match.start(), gender))

    ordered_genders: list[str] = []
    for _, gender in sorted(matches, key=lambda item: item[0]):
        if not ordered_genders or ordered_genders[-1] != gender:
            ordered_genders.append(gender)
        if len(ordered_genders) >= 2:
            return ordered_genders[0], ordered_genders[1]
    return None


def extract_role_labels_from_brief(brief: StoryBrief, limit: int = 6) -> list[str]:
    """
    Best-effort role phrase extraction from the brief text.

    This is intentionally heuristic and only serves fallback / repair paths.
    The primary cast structure still comes from the LLM Cast Analyzer prompt.
    """
    text = "，".join(
        part
        for part in (
            brief.idea.strip(),
            "，".join(item.strip() for item in brief.must_include if item.strip()),
        )
        if part
    )
    return extract_role_labels_from_text(text, limit=limit)


def extract_role_labels_from_text(text: str, limit: int = 6) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    for clause in CLAUSE_SPLIT_PATTERN.split(text):
        clause = clause.strip()
        if not clause:
            continue

        head_label = _extract_head_role_label(clause)
        if head_label:
            _append_role_label(labels, seen, head_label, limit)

        fragments = [
            fragment.strip()
            for fragment in ROLE_LIST_SPLIT_PATTERN.split(clause)
            if fragment.strip()
        ]
        if len(fragments) > 1:
            for fragment in fragments:
                label = _extract_fragment_role_label(fragment)
                if label:
                    _append_role_label(labels, seen, label, limit)
                if len(labels) >= limit:
                    return labels
            continue

        if text_requires_explicit_counterpart(clause):
            counterpart_label = _extract_counterpart_role_label(clause)
            if counterpart_label:
                _append_role_label(labels, seen, counterpart_label, limit)
                if len(labels) >= limit:
                    return labels

    return labels


def count_role_labels_in_brief(brief: StoryBrief, limit: int = 6) -> int:
    return len(extract_role_labels_from_brief(brief, limit=limit))


def count_role_labels_in_text(text: str, limit: int = 6) -> int:
    return len(extract_role_labels_from_text(text, limit=limit))


def _extract_head_role_label(clause: str) -> str:
    match = ROLE_LABEL_HEAD_PATTERN.match(clause)
    if not match:
        return ""
    return _normalize_role_label(match.group("label"))


def _extract_fragment_role_label(fragment: str) -> str:
    trimmed = ROLE_LABEL_TRIM_PATTERN.sub("", fragment).strip()
    if not trimmed:
        return ""
    normalized_fragment = _normalize_role_label(trimmed)
    if any(normalized_fragment.endswith(suffix) for suffix in ROLE_LABEL_SUFFIXES):
        return normalized_fragment

    match = None
    for candidate in ROLE_LABEL_ANY_PATTERN.finditer(trimmed):
        match = candidate
    if match is None:
        return ""
    return _normalize_role_label(match.group("label"))


def _extract_counterpart_role_label(clause: str) -> str:
    match = re.search(r"(?:向|对|给|跟|和|与|同)([^，。；：:!?！？]{1,18})", clause)
    if not match:
        return ""
    fragment = COUNTERPART_TAIL_TRIM_PATTERN.sub("", match.group(1)).strip()
    return _extract_fragment_role_label(fragment)


def _normalize_role_label(label: str) -> str:
    token = ROLE_LABEL_PREFIX_PATTERN.sub("", label.strip())
    token = token.strip(" ，。；：:!?！？、")
    if not token:
        return ""
    if len(token) > 18:
        return ""
    return token


def _append_role_label(
    labels: list[str],
    seen: set[str],
    label: str,
    limit: int,
) -> None:
    if not label or label in seen or len(labels) >= limit:
        return
    labels.append(label)
    seen.add(label)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)
