from __future__ import annotations

import re


TIMED_BEAT_PREFIX_PATTERN = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*[-~到]\s*\d+(?:\.\d+)?\s*秒\s*[：:，,]?\s*"
)
ACTION_STEP_SPLIT_PATTERN = re.compile(r"[；;。]|然后|随后|接着|之后|最后|最终|再(?:次)?")
EVENT_PROGRESS_SPLIT_PATTERN = re.compile(r"[，,；;。]|然后|随后|接着|之后|最后|最终")

GENERIC_PROGRESS_FILLER_TERMS = (
    "继续",
    "承接",
    "保持",
    "延续",
    "推进",
    "过渡",
    "状态",
    "情绪",
    "动作",
    "关系",
    "当前",
    "片段",
    "场景",
)

PROGRESSION_SIGNAL_TERMS = (
    "等待",
    "会面",
    "相遇",
    "走",
    "跑",
    "停",
    "停下",
    "停步",
    "驻足",
    "回头",
    "转身",
    "抬头",
    "低头",
    "看",
    "望",
    "靠近",
    "走近",
    "迈步",
    "前进",
    "后退",
    "进入",
    "到达",
    "出现",
    "离开",
    "伸手",
    "递",
    "递出",
    "接",
    "接过",
    "开口",
    "说",
    "回应",
    "回答",
    "告白",
    "表白",
    "确认",
    "决定",
    "答应",
    "拒绝",
    "牵手",
    "拥抱",
    "亲吻",
    "坐下",
    "起身",
)

BOUNDARY_RESPONSE_CONTEXT_TOKENS = (
    "告白",
    "表白",
    "心意",
    "那句话",
    "等这句话",
    "关系",
    "在一起",
    "交往",
    "喜欢你",
    "喜欢他",
    "喜欢她",
    "也喜欢",
    "说喜欢",
    "可不可以亲",
    "亲吻",
    "牵手",
    "拥抱",
)

BOUNDARY_CONFIRMATION_CONTEXT_TOKENS = (
    "关系",
    "心意",
    "告白",
    "表白",
    "在一起",
    "交往",
    "喜欢你",
    "喜欢他",
    "喜欢她",
    "也喜欢",
    "亲吻",
    "牵手",
    "拥抱",
)

BOUNDARY_DECISION_CONTEXT_TOKENS = (
    "关系",
    "在一起",
    "交往",
    "离开",
    "分开",
    "告白",
    "表白",
    "亲吻",
    "牵手",
    "拥抱",
)

NO_PROGRESS_PHRASES = (
    "没有新的动作推进",
    "没有继续前进",
    "继续保持",
    "保持当前",
    "保持等待姿态",
    "停在原地",
    "仍停在原地",
    "仍停在",
    "继续停在",
    "姿态几乎不变",
    "没有明显变化",
    "没有推进",
)

EVENT_PROGRESS_CHAIN_MARKERS = (
    "先",
    "再",
    "然后",
    "随后",
    "接着",
    "之后",
    "最后",
    "最终",
    "终于",
    "后",
)

GENERIC_OPENING_MATCH_PHRASES = (
    "承接上一段继续",
    "场景开始",
    "开场进入",
    "继续推进",
    "继续当前状态",
    "新场景开始",
)

DIRECTION_APPROACH_PATTERNS = (
    re.compile(r"从(?:画面)?深处向(?:画面)?浅处"),
    re.compile(r"(?:走近|靠近|接近|逼近|冲向)(?:镜头|画面前方|前景)?"),
    re.compile(r"向(?:镜头|画面前方|画面浅处|前景|近处)"),
    re.compile(r"由远及近"),
    re.compile(r"朝(?:镜头|前方)走来"),
)

DIRECTION_RETREAT_PATTERNS = (
    re.compile(r"从(?:画面)?浅处向(?:画面)?深处"),
    re.compile(r"(?:走向|走进|迈向|退向)(?:远处|深处|后方)"),
    re.compile(r"向(?:画面深处|远处|远方|深处|后方)"),
    re.compile(r"(?:背影|身影).{0,6}(?:远去|渐远|离开)"),
    re.compile(r"渐行渐远"),
    re.compile(r"离镜头越来越远"),
    re.compile(r"由近及远"),
)


def normalize_similarity_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def text_ngrams(value: str) -> set[str]:
    normalized = normalize_similarity_text(value)
    if not normalized:
        return set()
    if len(normalized) <= 3:
        return {normalized}
    grams: set[str] = set()
    for size in (2, 3):
        if len(normalized) < size:
            continue
        grams.update(
            normalized[index : index + size]
            for index in range(len(normalized) - size + 1)
        )
    return grams


def text_overlap_ratio(left: str, right: str) -> float:
    left_grams = text_ngrams(left)
    right_grams = text_ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))


def text_new_signal_count(previous: str, current: str) -> int:
    return len(text_ngrams(current) - text_ngrams(previous))


def progress_text_too_generic(text: str) -> bool:
    normalized = normalize_similarity_text(text)
    if not normalized:
        return True
    reduced = normalized
    for token in GENERIC_PROGRESS_FILLER_TERMS:
        reduced = reduced.replace(token, "")
    return len(reduced) < 6


def extract_progression_signal_terms(text: str) -> set[str]:
    normalized = normalize_similarity_text(text)
    return {
        term
        for term in PROGRESSION_SIGNAL_TERMS
        if term and term in normalized
    }


def contains_normalized_token(normalized_text: str, tokens: tuple[str, ...]) -> bool:
    return any(
        normalize_similarity_text(token) in normalized_text
        for token in tokens
        if normalize_similarity_text(token)
    )


def extract_boundary_critical_terms(text: str) -> set[str]:
    normalized = normalize_similarity_text(text)
    if not normalized:
        return set()

    terms: set[str] = set()
    if contains_normalized_token(
        normalized,
        (
            "告白",
            "表白",
            "喜欢你",
            "说出喜欢",
            "说出心意",
            "表达心意",
            "心意说出口",
        ),
    ):
        terms.add("告白")
    if contains_normalized_token(
        normalized,
        (
            "亲吻",
            "接吻",
            "拥吻",
            "吻上",
            "吻住",
            "轻吻",
            "踮脚吻",
            "可不可以亲",
            "亲她",
            "亲他",
            "亲你",
        ),
    ):
        terms.add("亲吻")
    if contains_normalized_token(
        normalized,
        ("牵手", "牵起", "牵住手", "十指相扣", "握住手"),
    ):
        terms.add("牵手")
    if contains_normalized_token(
        normalized,
        ("拥抱", "抱住", "抱紧", "环住", "搂住"),
    ):
        terms.add("拥抱")
    if contains_normalized_token(
        normalized,
        ("回应", "回答", "答应", "拒绝", "接受", "同意"),
    ) and contains_normalized_token(
        normalized,
        BOUNDARY_RESPONSE_CONTEXT_TOKENS,
    ):
        terms.add("回应")
    if contains_normalized_token(
        normalized,
        ("确认", "确定"),
    ) and contains_normalized_token(
        normalized,
        BOUNDARY_CONFIRMATION_CONTEXT_TOKENS,
    ):
        terms.add("确认")
    if "决定" in normalized and contains_normalized_token(
        normalized,
        BOUNDARY_DECISION_CONTEXT_TOKENS,
    ):
        terms.add("决定")
    return terms


def estimate_progression_node_count_from_texts(texts: list[str]) -> int:
    clauses: list[str] = []
    non_empty_texts = [str(item or "").strip() for item in texts if str(item or "").strip()]
    for text in non_empty_texts:
        for raw_clause in EVENT_PROGRESS_SPLIT_PATTERN.split(text):
            clause = str(raw_clause or "").strip(" ，。；;")
            if not clause:
                continue
            if progress_text_too_generic(clause) and not extract_progression_signal_terms(clause):
                continue
            if max([text_overlap_ratio(clause, existing) for existing in clauses] or [0.0]) >= 0.72:
                continue
            clauses.append(clause)
    combined_text = " ".join(non_empty_texts)
    signal_count = len(extract_progression_signal_terms(combined_text))
    if len(clauses) >= 2:
        return max(len(clauses), signal_count if signal_count >= 3 else len(clauses))
    if signal_count >= 3:
        return signal_count
    if signal_count >= 2 and any(marker in combined_text for marker in EVENT_PROGRESS_CHAIN_MARKERS):
        return signal_count
    if clauses:
        return len(clauses)
    if signal_count:
        return 1
    return 1


def text_explicitly_stalled(text: str) -> bool:
    normalized = normalize_similarity_text(text)
    return any(
        normalize_similarity_text(phrase) in normalized
        for phrase in NO_PROGRESS_PHRASES
    )
