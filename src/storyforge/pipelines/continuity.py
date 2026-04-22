from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from storyforge.agents.base import PromptRequest
from storyforge.core.io import write_json
from storyforge.domains.video.contracts import SceneImageTask, SeedanceClipTask
from storyforge.integrations.llm import build_agent_backend


SPOKEN_TEXT_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
TIMED_BEAT_PATTERN = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒"
)
SCENE_BIBLE_REQUIRED_KEYS = (
    "location",
    "time_window",
    "lighting",
    "background_anchors",
    "spatial_layout",
)
SHOT_STATE_REQUIRED_KEYS = (
    "framing",
    "camera_motion",
    "blocking",
    "action_progression",
    "prop_continuity",
    "end_state_lock",
)
CONTINUITY_LINK_REQUIRED_KEYS = (
    "transition_mode",
    "opening_match",
    "allowed_changes",
    "transition_reason",
)
CONTINUITY_REPORT_FILENAME = "continuity_report.json"
ACTION_REGENERATE_SCENE_MASTER = "regenerate_scene_master_frame"
ACTION_REGENERATE_SCENE_IMAGES = "regenerate_scene_images"
ACTION_REGENERATE_VIDEO = "regenerate_video"
SCENE_BASELINE_MIN_BACKGROUND_ANCHORS = 2
SCENE_BASELINE_MIN_FIXED_PROPS = 1
SCENE_BASELINE_MIN_DOMINANT_PALETTE = 1
ACTION_LABELS = {
    ACTION_REGENERATE_SCENE_MASTER: "重生成场景母图",
    ACTION_REGENERATE_SCENE_IMAGES: "重生成片段场景图",
    ACTION_REGENERATE_VIDEO: "重生成片段视频",
}
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
FAILED_VIDEO_STATUSES = {"failed", "cancelled", "canceled", "rejected"}
PENDING_VIDEO_STATUSES = {"submitted", "queued", "running", "processing", "pending", "timeout"}
GENERIC_CONTINUITY_FILLER_TERMS = (
    "开场",
    "开头",
    "继续",
    "承接",
    "延续",
    "上一段",
    "上一镜头",
    "上一片段",
    "尾部",
    "尾帧",
    "状态",
    "镜头",
    "画面",
    "保持",
    "一致",
    "跟上",
)


@dataclass(slots=True)
class ContinuityIssue:
    scope: str
    severity: str
    code: str
    message: str
    scene_id: str = ""
    segment_id: str = ""
    recommended_action: str = ""
    recommended_action_label: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContinuityActionSummary:
    action: str
    label: str
    count: int


@dataclass(slots=True)
class ContinuitySummary:
    issue_count: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    scene_issue_count: int
    segment_issue_count: int


@dataclass(slots=True)
class ContinuityRuleReview:
    status: str
    summary: ContinuitySummary
    recommended_actions: list[ContinuityActionSummary]
    scene_issues: list[ContinuityIssue]
    segment_issues: list[ContinuityIssue]


@dataclass(slots=True)
class ContinuityLLMReview:
    status: str
    triggered: bool
    mode_requested: str
    mode_effective: str
    reviewer_provider: str = ""
    reviewer_model: str = ""
    note: str = ""
    summary: ContinuitySummary | None = None
    recommended_actions: list[ContinuityActionSummary] = field(default_factory=list)
    scene_issues: list[ContinuityIssue] = field(default_factory=list)
    segment_issues: list[ContinuityIssue] = field(default_factory=list)


@dataclass(slots=True)
class ContinuityReport:
    report_version: str
    generated_at: str
    status: str
    review_mode_requested: str
    review_mode_effective: str
    summary: ContinuitySummary
    recommended_actions: list[ContinuityActionSummary]
    scene_issues: list[ContinuityIssue]
    segment_issues: list[ContinuityIssue]
    v1_rules: ContinuityRuleReview
    v2_llm_review: ContinuityLLMReview


class ContinuitySoftIssueSchema(BaseModel):
    scope: Literal["scene", "segment"]
    severity: Literal["high", "medium", "low"]
    issue_type: str = Field(default="soft_continuity_risk")
    scene_id: str = ""
    segment_id: str = ""
    message: str
    recommended_action: Literal[
        "",
        ACTION_REGENERATE_SCENE_MASTER,
        ACTION_REGENERATE_SCENE_IMAGES,
        ACTION_REGENERATE_VIDEO,
    ] = ""
    evidence: str = ""


class ContinuitySoftReviewSchema(BaseModel):
    summary: str = ""
    scene_issues: list[ContinuitySoftIssueSchema] = Field(default_factory=list)
    segment_issues: list[ContinuitySoftIssueSchema] = Field(default_factory=list)


def write_continuity_report(
    output_dir: Path,
    *,
    config=None,
    review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> tuple[Path, ContinuityReport]:
    report = build_continuity_report(
        output_dir,
        config=config,
        review_mode=review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    report_path = output_dir / CONTINUITY_REPORT_FILENAME
    write_json(report_path, report)
    return report_path, report


def build_continuity_report(
    output_dir: Path,
    *,
    config=None,
    review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> ContinuityReport:
    from storyforge.pipelines.video_planning import load_video_planning_artifacts

    planning = load_video_planning_artifacts(output_dir)
    project_package = planning.project_package
    normalized_review_mode = _normalize_review_mode(review_mode)

    v1_rules = _build_v1_rule_review(output_dir, project_package)
    v2_llm_review = _build_v2_llm_review(
        output_dir=output_dir,
        project_package=project_package,
        v1_rules=v1_rules,
        config=config,
        review_mode=normalized_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    scene_issues = _dedupe_issues(v1_rules.scene_issues + v2_llm_review.scene_issues)
    segment_issues = _dedupe_issues(v1_rules.segment_issues + v2_llm_review.segment_issues)
    summary = _build_summary(scene_issues, segment_issues)
    return ContinuityReport(
        report_version="v2",
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=_build_report_status(summary),
        review_mode_requested=normalized_review_mode,
        review_mode_effective=v2_llm_review.mode_effective,
        summary=summary,
        recommended_actions=_build_action_summaries(scene_issues + segment_issues),
        scene_issues=_sort_issues(scene_issues),
        segment_issues=_sort_issues(segment_issues),
        v1_rules=v1_rules,
        v2_llm_review=v2_llm_review,
    )


def _build_v1_rule_review(output_dir: Path, project_package) -> ContinuityRuleReview:
    segments_by_id = {
        segment.segment_id: segment
        for segment in project_package.segments
    }
    scenes_by_id = {
        scene.scene_id: scene
        for scene in project_package.scenes
    }
    scene_tasks_by_segment_id = {
        task.segment_id: task
        for task in project_package.scene_images
    }
    clip_tasks_by_segment_id = {
        clip.segment_id: clip
        for clip in project_package.seedance_manifest.clips
    }

    scene_issues: list[ContinuityIssue] = []
    segment_issues: list[ContinuityIssue] = []

    for scene in project_package.scenes:
        related_tasks = [
            task for task in project_package.scene_images if task.scene_id == scene.scene_id
        ]
        scene_issues.extend(_build_scene_issues(output_dir, scene, related_tasks))

    adjacent_previous_segment = None
    for segment in project_package.segments:
        scene = scenes_by_id.get(segment.scene_id)
        scene_task = scene_tasks_by_segment_id.get(segment.segment_id)
        clip_task = clip_tasks_by_segment_id.get(segment.segment_id)
        previous_segment = segments_by_id.get(segment.continuity_link.previous_segment_id.strip())
        previous_scene_task = (
            scene_tasks_by_segment_id.get(previous_segment.segment_id)
            if previous_segment is not None
            else None
        )
        segment_issues.extend(
            _build_segment_issues(
                output_dir=output_dir,
                segment=segment,
                scene=scene,
                scene_task=scene_task,
                clip_task=clip_task,
                previous_segment=previous_segment,
                previous_scene_task=previous_scene_task,
                adjacent_previous_segment=adjacent_previous_segment,
            )
        )
        adjacent_previous_segment = segment

    summary = _build_summary(scene_issues, segment_issues)
    return ContinuityRuleReview(
        status=_build_report_status(summary),
        summary=summary,
        recommended_actions=_build_action_summaries(scene_issues + segment_issues),
        scene_issues=_sort_issues(scene_issues),
        segment_issues=_sort_issues(segment_issues),
    )


def _build_v2_llm_review(
    *,
    output_dir: Path,
    project_package,
    v1_rules: ContinuityRuleReview,
    config,
    review_mode: str,
    llm_provider: str | None,
    llm_model: str | None,
) -> ContinuityLLMReview:
    effective_mode, trigger_note = _resolve_v2_effective_mode(
        project_package,
        v1_rules.summary,
        review_mode,
    )
    if review_mode == "off":
        return ContinuityLLMReview(
            status="disabled",
            triggered=False,
            mode_requested=review_mode,
            mode_effective="off",
            note="用户已关闭 LLM 软审校。",
        )
    if effective_mode == "off":
        return ContinuityLLMReview(
            status="skipped",
            triggered=False,
            mode_requested=review_mode,
            mode_effective="off",
            note=trigger_note,
        )
    if config is None:
        return ContinuityLLMReview(
            status="failed",
            triggered=True,
            mode_requested=review_mode,
            mode_effective="on",
            note="未提供配置，无法执行 LLM 软审校。",
        )

    resolved_provider = str(llm_provider or config.llm.provider or "").strip().lower()
    resolved_model = str(llm_model or config.llm.model or "").strip()

    try:
        backend = build_agent_backend(
            config,
            use_llm=True,
            provider=llm_provider,
            model=llm_model,
        )
    except Exception as exc:
        return ContinuityLLMReview(
            status="failed",
            triggered=True,
            mode_requested=review_mode,
            mode_effective="on",
            reviewer_provider=resolved_provider,
            reviewer_model=resolved_model,
            note=f"LLM 软审校初始化失败：{exc}",
        )

    request = _build_v2_review_request(project_package, v1_rules, trigger_note)
    try:
        structured = backend.generate_structured(request, ContinuitySoftReviewSchema)
    except Exception as exc:
        return ContinuityLLMReview(
            status="failed",
            triggered=True,
            mode_requested=review_mode,
            mode_effective="on",
            reviewer_provider=resolved_provider,
            reviewer_model=resolved_model,
            note=f"LLM 软审校执行失败：{exc}",
        )

    scene_issues, segment_issues = _normalize_v2_issues(project_package, structured)
    summary = _build_summary(scene_issues, segment_issues)
    summary_note = str(structured.summary or "").strip()
    return ContinuityLLMReview(
        status="completed",
        triggered=True,
        mode_requested=review_mode,
        mode_effective="on",
        reviewer_provider=resolved_provider,
        reviewer_model=resolved_model,
        note=" ".join(part for part in [trigger_note, summary_note] if part).strip(),
        summary=summary,
        recommended_actions=_build_action_summaries(scene_issues + segment_issues),
        scene_issues=_sort_issues(scene_issues),
        segment_issues=_sort_issues(segment_issues),
    )


def _resolve_v2_effective_mode(project_package, v1_summary: ContinuitySummary, review_mode: str) -> tuple[str, str]:
    if review_mode == "on":
        return "on", "用户强制开启 LLM 软审校。"

    reasons: list[str] = []
    if any(len(scene.segments) > 1 for scene in project_package.scenes):
        reasons.append("存在同场景多片段")
    if any(
        len({*segment.involved_characters, *segment.start_frame_characters, *segment.mid_frame_characters, *segment.end_frame_characters}) >= 2
        for segment in project_package.segments
    ):
        reasons.append("存在双人或多人同框")
    if any(
        segment.continuity_link.transition_mode.strip().lower() == "continue"
        for segment in project_package.segments
    ):
        reasons.append("存在跨段连续承接")
    if any(_segment_has_spoken_content(segment) for segment in project_package.segments):
        reasons.append("存在对白或字幕表演")
    if v1_summary.high_risk_count or v1_summary.medium_risk_count:
        reasons.append("V1 已发现中高风险")

    if reasons:
        return "on", "自动触发 LLM 软审校：" + "、".join(reasons) + "。"
    return "off", "自动模式未触发：当前 run 较简单，仅保留 V1 规则审校。"


def _build_v2_review_request(project_package, v1_rules: ContinuityRuleReview, trigger_note: str) -> PromptRequest:
    context = {
        "project_title": project_package.title,
        "trigger_note": trigger_note,
        "v1_summary": {
            "status": v1_rules.status,
            "issue_count": v1_rules.summary.issue_count,
            "high_risk_count": v1_rules.summary.high_risk_count,
            "medium_risk_count": v1_rules.summary.medium_risk_count,
            "low_risk_count": v1_rules.summary.low_risk_count,
        },
        "v1_scene_issues": [
            _issue_context(issue)
            for issue in v1_rules.scene_issues[:8]
        ],
        "v1_segment_issues": [
            _issue_context(issue)
            for issue in v1_rules.segment_issues[:12]
        ],
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "title": scene.title,
                "summary": _truncate(scene.summary, 220),
                "involved_characters": list(scene.involved_characters),
                "scene_master_frame_status": scene.scene_master_frame_status,
                "scene_master_frame_error": _truncate(scene.scene_master_frame_error, 120),
                "scene_bible": {
                    "location": scene.scene_bible.location,
                    "time_window": scene.scene_bible.time_window,
                    "weather": scene.scene_bible.weather,
                    "lighting": scene.scene_bible.lighting,
                    "background_anchors": list(scene.scene_bible.background_anchors[:6]),
                    "fixed_props": list(scene.scene_bible.fixed_props[:6]),
                    "spatial_layout": scene.scene_bible.spatial_layout,
                    "character_blocking": scene.scene_bible.character_blocking,
                    "continuity_notes": scene.scene_bible.continuity_notes,
                },
                "segment_ids": [segment.segment_id for segment in scene.segments],
            }
            for scene in project_package.scenes
        ],
        "segments": [
            {
                "segment_id": segment.segment_id,
                "scene_id": segment.scene_id,
                "chapter_number": segment.chapter_number,
                "title": segment.title,
                "summary": _truncate(segment.summary, 220),
                "duration_seconds": segment.duration_seconds,
                "requires_mid_frame": segment.requires_mid_frame,
                "involved_characters": list(segment.involved_characters),
                "start_frame_characters": list(segment.start_frame_characters),
                "mid_frame_characters": list(segment.mid_frame_characters),
                "end_frame_characters": list(segment.end_frame_characters),
                "timed_beats": list(segment.timed_beats[:6]),
                "narration_preview": _truncate(segment.narration, 120),
                "dialogue_preview": [_truncate(item, 80) for item in segment.dialogue_lines[:3]],
                "subtitle_preview": [_truncate(item, 80) for item in segment.subtitle_lines[:3]],
                "start_frame_prompt": _truncate(segment.start_frame_prompt, 220),
                "mid_frame_prompt": _truncate(segment.mid_frame_prompt, 220),
                "end_frame_prompt": _truncate(segment.end_frame_prompt, 220),
                "shot_state": {
                    "framing": segment.shot_state.framing,
                    "camera_motion": segment.shot_state.camera_motion,
                    "blocking": segment.shot_state.blocking,
                    "action_progression": segment.shot_state.action_progression,
                    "emotion_progression": segment.shot_state.emotion_progression,
                    "prop_continuity": segment.shot_state.prop_continuity,
                    "screen_direction": segment.shot_state.screen_direction,
                    "end_state_lock": segment.shot_state.end_state_lock,
                },
                "continuity_link": {
                    "previous_segment_id": segment.continuity_link.previous_segment_id,
                    "transition_mode": segment.continuity_link.transition_mode,
                    "opening_match": segment.continuity_link.opening_match,
                    "carry_over_elements": list(segment.continuity_link.carry_over_elements),
                    "allowed_changes": segment.continuity_link.allowed_changes,
                    "transition_reason": segment.continuity_link.transition_reason,
                },
            }
            for segment in project_package.segments
        ],
    }
    return PromptRequest(
        system_prompt=(
            "你是 StoryForge 的 Continuity Director。"
            "你只根据提供的结构化 story/video planning 与执行状态，找出规则审校之外仍值得人工留意的连续性软风险。"
            "重点关注：场景漂移、站位或朝向反转、动作链断裂、情绪推进跳变、多角色出入场不顺、"
            "镜头节奏和表演难以成立、字幕或对白虽然未超硬预算但观感仍可能说不完。"
            "不要重复已经明显属于文件缺失、任务失败、URL 缺失这类硬错误。"
            "没有足够证据时不要瞎猜。最多输出 3 个 scene 问题和 6 个 segment 问题。"
            "recommended_action 只能从 regenerate_scene_master_frame、regenerate_scene_images、regenerate_video、空字符串 中选。"
        ),
        user_prompt=(
            "请基于下面的 JSON 上下文，返回结构化连续性软审校结果。\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        ),
        metadata={"task": "continuity-director"},
    )


def _normalize_v2_issues(project_package, structured: ContinuitySoftReviewSchema) -> tuple[list[ContinuityIssue], list[ContinuityIssue]]:
    valid_scene_ids = {scene.scene_id for scene in project_package.scenes}
    segment_scene_map = {
        segment.segment_id: segment.scene_id
        for segment in project_package.segments
    }
    scene_issues: list[ContinuityIssue] = []
    segment_issues: list[ContinuityIssue] = []

    for item in structured.scene_issues:
        scene_id = item.scene_id.strip()
        if scene_id not in valid_scene_ids:
            continue
        scene_issues.append(
            _issue(
                scope="scene",
                severity=item.severity,
                code="llm_" + _normalize_issue_type(item.issue_type),
                message=item.message.strip(),
                scene_id=scene_id,
                recommended_action=item.recommended_action,
                details={"evidence": item.evidence.strip(), "source": "v2_llm_review"},
            )
        )

    for item in structured.segment_issues:
        segment_id = item.segment_id.strip()
        if segment_id not in segment_scene_map:
            continue
        segment_issues.append(
            _issue(
                scope="segment",
                severity=item.severity,
                code="llm_" + _normalize_issue_type(item.issue_type),
                message=item.message.strip(),
                scene_id=segment_scene_map.get(segment_id, item.scene_id.strip()),
                segment_id=segment_id,
                recommended_action=item.recommended_action,
                details={"evidence": item.evidence.strip(), "source": "v2_llm_review"},
            )
        )

    return _sort_issues(_dedupe_issues(scene_issues)), _sort_issues(_dedupe_issues(segment_issues))


def _issue_context(issue: ContinuityIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "scope": issue.scope,
        "code": issue.code,
        "message": issue.message,
        "scene_id": issue.scene_id,
        "segment_id": issue.segment_id,
        "recommended_action": issue.recommended_action,
    }


def _normalize_review_mode(review_mode: str) -> str:
    normalized = str(review_mode or "").strip().lower()
    if normalized in {"off", "on"}:
        return normalized
    return "auto"


def _normalize_issue_type(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or "soft_continuity_risk"


def _segment_has_spoken_content(segment) -> bool:
    if str(segment.narration or "").strip():
        return True
    return any(str(item or "").strip() for item in [*segment.dialogue_lines, *segment.subtitle_lines])


def _truncate(value: str, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _dedupe_issues(issues: list[ContinuityIssue]) -> list[ContinuityIssue]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[ContinuityIssue] = []
    for issue in issues:
        key = (
            issue.scope,
            issue.scene_id,
            issue.segment_id,
            issue.code,
            issue.message,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _build_scene_issues(
    output_dir: Path,
    scene,
    related_tasks: list[SceneImageTask],
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    missing_scene_bible_keys = _missing_required_fields(scene.scene_bible, SCENE_BIBLE_REQUIRED_KEYS)
    if missing_scene_bible_keys:
        issues.append(
            _issue(
                scope="scene",
                severity="medium",
                code="scene_bible_incomplete",
                message=(
                    "场景连续性基线不完整，缺少："
                    + "、".join(missing_scene_bible_keys)
                ),
                scene_id=scene.scene_id,
                details={"missing_keys": missing_scene_bible_keys},
            )
        )
    baseline_gaps = _collect_scene_baseline_gaps(scene)
    if baseline_gaps:
        issues.append(
            _issue(
                scope="scene",
                severity="medium",
                code="scene_baseline_weak",
                message=(
                    "场景基线过弱，后续关键帧容易出现背景或空间漂移："
                    + "、".join(baseline_gaps)
                ),
                scene_id=scene.scene_id,
                recommended_action=ACTION_REGENERATE_SCENE_MASTER,
                details={
                    "baseline_gaps": baseline_gaps,
                    "background_anchor_count": len(_normalized_string_list(scene.scene_bible.background_anchors)),
                    "fixed_prop_count": len(_normalized_string_list(scene.scene_bible.fixed_props)),
                    "dominant_palette_count": len(_normalized_string_list(scene.scene_bible.dominant_palette)),
                },
            )
        )

    master_frame_exists = _path_exists(output_dir, scene.scene_master_frame_path)
    if scene.scene_master_frame_status == "failed":
        issues.append(
            _issue(
                scope="scene",
                severity="high",
                code="scene_master_frame_failed",
                message="场景母图生成失败，需要重新生成场景母图。",
                scene_id=scene.scene_id,
                recommended_action=ACTION_REGENERATE_SCENE_MASTER,
                details={"error": scene.scene_master_frame_error},
            )
        )
    elif (
        scene.scene_master_frame_status == "completed"
        and not scene.scene_master_frame_url
        and not master_frame_exists
    ):
        issues.append(
            _issue(
                scope="scene",
                severity="high",
                code="scene_master_frame_missing_output",
                message="场景母图标记为已完成，但没有可用的母图文件或 URL。",
                scene_id=scene.scene_id,
                recommended_action=ACTION_REGENERATE_SCENE_MASTER,
                details={"scene_master_frame_path": scene.scene_master_frame_path},
            )
        )

    task_master_statuses = {
        (task.scene_master_frame_status, task.scene_master_frame_url)
        for task in related_tasks
        if task.scene_master_frame_status or task.scene_master_frame_url
    }
    if len(task_master_statuses) > 1:
        issues.append(
            _issue(
                scope="scene",
                severity="medium",
                code="scene_master_frame_task_mismatch",
                message="同一场景下各片段记录的场景母图状态不一致。",
                scene_id=scene.scene_id,
                recommended_action=ACTION_REGENERATE_SCENE_MASTER,
            )
        )

    for task in related_tasks:
        if (
            task.scene_master_frame_status
            and task.scene_master_frame_status != scene.scene_master_frame_status
        ):
            issues.append(
                _issue(
                    scope="scene",
                    severity="medium",
                    code="scene_master_frame_status_mismatch",
                    message=(
                        f"片段 {task.segment_id} 的场景母图状态和 scene 主记录不一致。"
                    ),
                    scene_id=scene.scene_id,
                    segment_id=task.segment_id,
                    recommended_action=ACTION_REGENERATE_SCENE_MASTER,
                )
            )
            break
    return issues


def _collect_scene_baseline_gaps(scene) -> list[str]:
    gaps: list[str] = []
    background_anchors = _normalized_string_list(scene.scene_bible.background_anchors)
    fixed_props = _normalized_string_list(scene.scene_bible.fixed_props)
    dominant_palette = _normalized_string_list(scene.scene_bible.dominant_palette)
    spatial_layout = str(scene.scene_bible.spatial_layout or "").strip()
    lighting = str(scene.scene_bible.lighting or "").strip()
    scene_master_prompt = str(scene.scene_master_frame_prompt or "").strip()

    if len(background_anchors) < SCENE_BASELINE_MIN_BACKGROUND_ANCHORS:
        gaps.append("背景锚点不足")
    if len(fixed_props) < SCENE_BASELINE_MIN_FIXED_PROPS:
        gaps.append("固定道具不足")
    if len(dominant_palette) < SCENE_BASELINE_MIN_DOMINANT_PALETTE:
        gaps.append("主色调不足")
    if not spatial_layout:
        gaps.append("空间布局不足")
    if not lighting:
        gaps.append("光线信息不足")
    if len(scene_master_prompt) < 80:
        gaps.append("场景母图 prompt 过短")

    return gaps


def _normalized_string_list(values: list[str]) -> list[str]:
    return [str(item or "").strip() for item in values if str(item or "").strip()]


def _build_segment_issues(
    *,
    output_dir: Path,
    segment,
    scene,
    scene_task: SceneImageTask | None,
    clip_task: SeedanceClipTask | None,
    previous_segment,
    previous_scene_task: SceneImageTask | None,
    adjacent_previous_segment,
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []

    missing_shot_state_keys = _missing_required_fields(segment.shot_state, SHOT_STATE_REQUIRED_KEYS)
    if missing_shot_state_keys:
        issues.append(
            _issue(
                scope="segment",
                severity="medium",
                code="shot_state_incomplete",
                message="镜头状态描述不完整，缺少：" + "、".join(missing_shot_state_keys),
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                details={"missing_keys": missing_shot_state_keys},
            )
        )

    missing_continuity_link_keys = _missing_required_fields(
        segment.continuity_link,
        CONTINUITY_LINK_REQUIRED_KEYS,
    )
    if missing_continuity_link_keys:
        issues.append(
            _issue(
                scope="segment",
                severity="medium",
                code="continuity_link_incomplete",
                message="跨段承接描述不完整，缺少：" + "、".join(missing_continuity_link_keys),
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                details={"missing_keys": missing_continuity_link_keys},
            )
        )

    issues.extend(_build_frame_character_issues(segment))
    issues.extend(_build_timing_issues(segment))
    issues.extend(
        _build_continuity_transition_issues(
            segment=segment,
            previous_segment=previous_segment,
            adjacent_previous_segment=adjacent_previous_segment,
        )
    )

    if scene_task is not None:
        issues.extend(_build_scene_task_issues(output_dir, segment, scene_task))

    if (
        segment.continuity_link.transition_mode.strip().lower() == "continue"
        and previous_segment is not None
        and _scene_generation_started(scene_task, previous_scene_task)
    ):
        if previous_scene_task is None or not _frame_output_ready(
            output_dir, previous_scene_task.end_frame_path, previous_scene_task.end_frame_url
        ):
            issues.append(
                _issue(
                    scope="segment",
                    severity="high",
                    code="continuity_source_missing",
                    message="该片段要求承接上一段，但上一段尾帧还不可用。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
                    details={"previous_segment_id": previous_segment.segment_id},
                )
            )

    if clip_task is not None:
        issues.extend(_build_video_clip_issues(output_dir, segment, scene_task, clip_task))

    if scene is None:
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="segment_scene_missing",
                message="该片段找不到所属 scene 记录。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
            )
        )

    return issues


def _build_continuity_transition_issues(
    *,
    segment,
    previous_segment,
    adjacent_previous_segment,
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    transition_mode = segment.continuity_link.transition_mode.strip().lower()

    if transition_mode == "continue" and previous_segment is not None:
        opening_match = str(segment.continuity_link.opening_match or "").strip()
        previous_end_state = str(
            previous_segment.shot_state.end_state_lock
            or previous_segment.shot_state.action_progression
            or previous_segment.summary
            or ""
        ).strip()
        opening_overlap = _text_overlap_ratio(opening_match, previous_end_state)
        if (
            not opening_match
            or _continuity_text_too_generic(opening_match)
            or opening_overlap < 0.22
        ):
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="opening_match_weak",
                    message="当前片段声明承接上一段，但 opening_match 没有明确复述上一段尾部的动作或站位状态。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
                    details={
                        "previous_segment_id": previous_segment.segment_id,
                        "previous_end_state_lock": previous_end_state,
                        "opening_match": opening_match,
                        "overlap_ratio": round(opening_overlap, 3),
                    },
                )
            )

        current_action = str(
            segment.shot_state.action_progression
            or segment.summary
            or ""
        ).strip()
        allowed_changes = str(segment.continuity_link.allowed_changes or "").strip()
        if _action_progression_stalled(previous_end_state, current_action, allowed_changes):
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="action_progression_stalled",
                    message="当前片段虽然承接上一段，但动作推进几乎没有前进，容易看起来像重新演了一遍。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
                    details={
                        "previous_segment_id": previous_segment.segment_id,
                        "previous_end_state_lock": previous_end_state,
                        "current_action_progression": current_action,
                        "allowed_changes": allowed_changes,
                    },
                )
            )

    if (
        adjacent_previous_segment is not None
        and adjacent_previous_segment.scene_id == segment.scene_id
        and _adjacent_segments_look_duplicate(adjacent_previous_segment, segment)
    ):
        issues.append(
            _issue(
                scope="segment",
                severity="medium",
                code="adjacent_segment_duplicate",
                message="该片段与前一个相邻片段表达的事件过于重复，容易造成镜头顺序混乱或重复表演。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
                details={
                    "previous_segment_id": adjacent_previous_segment.segment_id,
                    "previous_summary": adjacent_previous_segment.summary,
                    "current_summary": segment.summary,
                },
            )
        )

    return issues


def _build_scene_task_issues(
    output_dir: Path,
    segment,
    scene_task: SceneImageTask,
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    if scene_task.status == "failed":
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="scene_generation_failed",
                message="片段场景图生成失败，需要重新生成场景图。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
                details={"error": scene_task.error},
            )
        )
        return issues

    if scene_task.status != "completed":
        return issues

    if not _frame_output_ready(output_dir, scene_task.start_frame_path, scene_task.start_frame_url):
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="start_frame_missing",
                message="片段场景图已完成，但首帧缺失。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
            )
        )
    if scene_task.requires_mid_frame and not _frame_output_ready(
        output_dir, scene_task.mid_frame_path, scene_task.mid_frame_url
    ):
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="mid_frame_missing",
                message="片段要求中段锚点帧，但当前中段帧缺失。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
            )
        )
    if not _frame_output_ready(output_dir, scene_task.end_frame_path, scene_task.end_frame_url):
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="end_frame_missing",
                message="片段场景图已完成，但尾帧缺失。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_SCENE_IMAGES,
            )
        )
    return issues


def _build_video_clip_issues(
    output_dir: Path,
    segment,
    scene_task: SceneImageTask | None,
    clip_task: SeedanceClipTask,
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []

    if scene_task is not None and scene_task.status == "completed":
        if not clip_task.start_frame_url and scene_task.start_frame_url:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="seedance_start_frame_missing",
                    message="视频提交清单缺少首帧 URL，无法稳定复用当前片段关键帧。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_VIDEO,
                )
            )
        if not clip_task.end_frame_url and scene_task.end_frame_url:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="seedance_end_frame_missing",
                    message="视频提交清单缺少尾帧 URL，无法稳定复用当前片段关键帧。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_VIDEO,
                )
            )

    if clip_task.submit_status == "failed" or clip_task.remote_status in FAILED_VIDEO_STATUSES:
        issues.append(
            _issue(
                scope="segment",
                severity="high",
                code="video_generation_failed",
                message="片段视频生成失败，需要重新生成视频。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                recommended_action=ACTION_REGENERATE_VIDEO,
                details={"error": clip_task.error, "remote_status": clip_task.remote_status},
            )
        )
        return issues

    if clip_task.remote_status in PENDING_VIDEO_STATUSES:
        issues.append(
            _issue(
                scope="segment",
                severity="low",
                code="video_generation_pending",
                message="片段视频仍在等待远程完成或下载完成。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                details={"remote_status": clip_task.remote_status, "submit_status": clip_task.submit_status},
            )
        )
        return issues

    if clip_task.remote_status == "succeeded" or clip_task.submit_status == "completed":
        if not _path_exists(output_dir, clip_task.downloaded_path or clip_task.output_path):
            issues.append(
                _issue(
                    scope="segment",
                    severity="high",
                    code="video_file_missing",
                    message="视频任务显示成功，但本地片段文件缺失。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    recommended_action=ACTION_REGENERATE_VIDEO,
                )
            )
    return issues


def _build_frame_character_issues(segment) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    involved_characters = set(segment.involved_characters)
    frame_specs = [
        ("start", segment.start_frame_characters),
        ("mid", segment.mid_frame_characters if segment.requires_mid_frame else []),
        ("end", segment.end_frame_characters),
    ]
    for frame_kind, characters in frame_specs:
        if frame_kind == "mid" and not segment.requires_mid_frame:
            continue
        if not characters:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code=f"{frame_kind}_frame_characters_missing",
                    message=f"{frame_kind} 帧没有标注出镜角色，后续生图和视频承接会变弱。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                )
            )
            continue
        invalid_names = [name for name in characters if name not in involved_characters]
        if invalid_names:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code=f"{frame_kind}_frame_characters_invalid",
                    message=f"{frame_kind} 帧包含未出现在片段角色列表里的角色：{'、'.join(invalid_names)}。",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    details={"invalid_names": invalid_names},
                )
            )
    return issues


def _build_timing_issues(segment) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    duration_seconds = max(int(segment.duration_seconds or 0), 0)
    spoken_unit_count = _spoken_unit_count(segment.subtitle_lines or _spoken_lines(segment))
    if duration_seconds > 0:
        budget = max(duration_seconds * 8, 24)
        if spoken_unit_count > budget:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="spoken_text_over_budget",
                    message=(
                        f"当前片段口播文本明显超预算，约 {spoken_unit_count} 个口播字符，"
                        f"当前时长 {duration_seconds}s。"
                    ),
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                    details={
                        "spoken_unit_count": spoken_unit_count,
                        "duration_seconds": duration_seconds,
                        "budget": budget,
                    },
                )
            )

    if not segment.timed_beats:
        issues.append(
            _issue(
                scope="segment",
                severity="medium",
                code="timed_beats_missing",
                message="片段缺少 timed_beats，镜头节奏与字幕时长难以校验。",
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
            )
        )
        return issues

    max_end_seconds = 0.0
    parsed_any = False
    for beat in segment.timed_beats:
        match = TIMED_BEAT_PATTERN.search(str(beat))
        if match is None:
            continue
        parsed_any = True
        start_seconds = float(match.group("start"))
        end_seconds = float(match.group("end"))
        max_end_seconds = max(max_end_seconds, end_seconds)
        if start_seconds >= end_seconds:
            issues.append(
                _issue(
                    scope="segment",
                    severity="medium",
                    code="timed_beats_invalid_range",
                    message=f"timed_beats 存在无效时间范围：{beat}",
                    scene_id=segment.scene_id,
                    segment_id=segment.segment_id,
                )
            )
    if parsed_any and duration_seconds > 0 and max_end_seconds > duration_seconds + 0.2:
        issues.append(
            _issue(
                scope="segment",
                severity="medium",
                code="timed_beats_exceed_duration",
                message=(
                    f"timed_beats 最后结束时间 {max_end_seconds:g}s 超过当前片段时长 {duration_seconds}s。"
                ),
                scene_id=segment.scene_id,
                segment_id=segment.segment_id,
                details={
                    "max_end_seconds": max_end_seconds,
                    "duration_seconds": duration_seconds,
                },
            )
        )
    return issues


def _adjacent_segments_look_duplicate(previous_segment, segment) -> bool:
    if set(previous_segment.involved_characters) != set(segment.involved_characters):
        return False
    summary_score = _text_overlap_ratio(previous_segment.summary, segment.summary)
    action_score = _text_overlap_ratio(
        previous_segment.shot_state.action_progression or previous_segment.summary,
        segment.shot_state.action_progression or segment.summary,
    )
    signature_score = _text_overlap_ratio(
        " ".join(
            [
                previous_segment.summary,
                previous_segment.shot_state.action_progression,
                " ".join(previous_segment.timed_beats),
            ]
        ),
        " ".join(
            [
                segment.summary,
                segment.shot_state.action_progression,
                " ".join(segment.timed_beats),
            ]
        ),
    )
    return signature_score >= 0.8 or (summary_score >= 0.74 and action_score >= 0.74)


def _action_progression_stalled(
    previous_end_state: str,
    current_action: str,
    allowed_changes: str,
) -> bool:
    if not previous_end_state or not current_action:
        return False
    overlap_ratio = _text_overlap_ratio(previous_end_state, current_action)
    new_signal_count = len(_text_ngrams(current_action) - _text_ngrams(previous_end_state))
    if overlap_ratio < 0.7 or new_signal_count > 2:
        return False
    if not allowed_changes:
        return True
    if _continuity_text_too_generic(allowed_changes):
        return True
    return _text_overlap_ratio(previous_end_state, allowed_changes) >= 0.78


def _continuity_text_too_generic(text: str) -> bool:
    normalized = _normalize_similarity_text(text)
    if not normalized:
        return True
    reduced = normalized
    for token in GENERIC_CONTINUITY_FILLER_TERMS:
        reduced = reduced.replace(token, "")
    return len(reduced) < 6


def _normalize_similarity_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def _text_ngrams(value: str) -> set[str]:
    normalized = _normalize_similarity_text(value)
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


def _text_overlap_ratio(left: str, right: str) -> float:
    left_grams = _text_ngrams(left)
    right_grams = _text_ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))


def _scene_generation_started(
    scene_task: SceneImageTask | None,
    previous_scene_task: SceneImageTask | None,
) -> bool:
    for task in (scene_task, previous_scene_task):
        if task is None:
            continue
        if task.status in {"running", "completed", "failed"}:
            return True
    return False


def _spoken_lines(segment) -> list[str]:
    lines: list[str] = []
    narration = str(segment.narration or "").strip()
    if narration:
        lines.append(narration)
    lines.extend(str(item or "").strip() for item in segment.dialogue_lines if str(item or "").strip())
    return lines


def _spoken_unit_count(lines: list[str]) -> int:
    return sum(len(SPOKEN_TEXT_PATTERN.findall(str(line))) for line in lines)


def _frame_output_ready(output_dir: Path, path_str: str, url: str) -> bool:
    return bool(url) or _path_exists(output_dir, path_str)


def _path_exists(output_dir: Path, raw_path: str) -> bool:
    if not raw_path:
        return False
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = output_dir / candidate
    return candidate.exists()


def _missing_required_fields(source: object, keys: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for key in keys:
        value = getattr(source, key, "")
        if isinstance(value, list):
            if not value:
                missing.append(key)
            continue
        if not str(value or "").strip():
            missing.append(key)
    return missing


def _issue(
    *,
    scope: str,
    severity: str,
    code: str,
    message: str,
    scene_id: str = "",
    segment_id: str = "",
    recommended_action: str = "",
    details: dict[str, Any] | None = None,
) -> ContinuityIssue:
    return ContinuityIssue(
        scope=scope,
        severity=severity,
        code=code,
        message=message,
        scene_id=scene_id,
        segment_id=segment_id,
        recommended_action=recommended_action,
        recommended_action_label=ACTION_LABELS.get(recommended_action, ""),
        details=details or {},
    )


def _build_summary(
    scene_issues: list[ContinuityIssue],
    segment_issues: list[ContinuityIssue],
) -> ContinuitySummary:
    issues = scene_issues + segment_issues
    return ContinuitySummary(
        issue_count=len(issues),
        high_risk_count=sum(1 for item in issues if item.severity == "high"),
        medium_risk_count=sum(1 for item in issues if item.severity == "medium"),
        low_risk_count=sum(1 for item in issues if item.severity == "low"),
        scene_issue_count=len(scene_issues),
        segment_issue_count=len(segment_issues),
    )


def _build_report_status(summary: ContinuitySummary) -> str:
    if summary.high_risk_count:
        return "critical"
    if summary.medium_risk_count or summary.low_risk_count:
        return "warning"
    return "healthy"


def _build_action_summaries(issues: list[ContinuityIssue]) -> list[ContinuityActionSummary]:
    action_counts: dict[str, int] = {}
    for issue in issues:
        action = issue.recommended_action.strip()
        if not action:
            continue
        action_counts[action] = action_counts.get(action, 0) + 1
    return [
        ContinuityActionSummary(
            action=action,
            label=ACTION_LABELS.get(action, action),
            count=count,
        )
        for action, count in sorted(action_counts.items(), key=lambda item: item[0])
    ]


def _sort_issues(issues: list[ContinuityIssue]) -> list[ContinuityIssue]:
    return sorted(
        issues,
        key=lambda item: (
            RISK_ORDER.get(item.severity, 99),
            item.scene_id,
            item.segment_id,
            item.code,
        ),
    )
