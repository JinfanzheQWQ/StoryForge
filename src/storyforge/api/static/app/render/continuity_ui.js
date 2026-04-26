import {
  chip,
  continuityReviewModeLabel,
  escapeAttr,
  escapeHtml,
  formatShortTime,
} from "../utils.js";

const CONTINUITY_SEVERITY_LABEL = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

export const CONTINUITY_STATUS_LABEL = {
  healthy: "稳定",
  warning: "需留意",
  critical: "高风险",
  unknown: "未校验",
};

const CONTINUITY_V2_STATUS_LABEL = {
  disabled: "已关闭",
  skipped: "自动跳过",
  completed: "已完成",
  failed: "失败",
};

const REPAIR_PENDING_ACTION_LABELS = {
  regenerate_scene_master_frame: "手动重生成场景母图",
  regenerate_scene_images: "手动重生成场景图",
  regenerate_video: "手动重生成视频",
};

export function renderRepairPlanNotice(task, remainingActions = null) {
  if (!task || task.status !== "completed" || !task.result?.media_regeneration_required) {
    return "";
  }
  const pendingActions = Array.isArray(remainingActions)
    ? remainingActions
    : (
      Array.isArray(task.result?.pending_media_actions)
        ? task.result.pending_media_actions
        : []
    );
  const actionLabels = pendingActions
      .map((action) => REPAIR_PENDING_ACTION_LABELS[action] || action)
      .filter(Boolean);
  const repairSummary = String(task.result?.repair_summary || "").trim();
  const message = actionLabels.length
    ? [
      repairSummary || "智能修复已完成，只更新了当前修复合同。",
      `媒体不会自动重跑，请按需要继续：${actionLabels.join("、")}。`,
    ].join(" ")
    : [
      repairSummary || "智能修复已完成，只更新了当前修复合同。",
      "后续媒体任务已手动提交或完成，可以继续审阅最新结果。",
    ].join(" ");
  return `<p class="asset-note">${escapeHtml(message)}</p>`;
}

export function renderBatchRepairNotice(task) {
  if (!task || task.status !== "completed") {
    return "";
  }
  const summary = String(task.result?.repair_summary || "").trim();
  if (!summary) {
    return "";
  }
  return `<p class="asset-note">${escapeHtml(summary)}</p>`;
}

export function buildContinuityLookup(groups, keyField) {
  return new Map(
    (groups || [])
      .filter((group) => group && group[keyField])
      .map((group) => [String(group[keyField]), group]),
  );
}

export function hasRecommendedContinuityAction(group, action) {
  return Boolean(group?.recommended_actions?.includes(action));
}

export function renderContinuityRiskChips(group) {
  if (!group || !group.issue_count) {
    return chip("连续性稳定");
  }
  const parts = [chip(`风险 ${group.issue_count}`)];
  if (group.high_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-high">高 ${group.high_risk_count}</span>`);
  }
  if (group.medium_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-medium">中 ${group.medium_risk_count}</span>`);
  }
  if (group.low_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-low">低 ${group.low_risk_count}</span>`);
  }
  return parts.join("");
}

export function renderContinuityIssueList(group, emptyMessage = "") {
  if (!group?.issues?.length) {
    return emptyMessage ? `<p class="continuity-empty">${escapeHtml(emptyMessage)}</p>` : "";
  }
  return `
    <div class="continuity-issue-list">
      ${group.issues.map((issue) => `
        <article class="continuity-issue continuity-issue-${escapeAttr(issue.severity || "low")}">
          <div class="continuity-issue-head">
            <span class="continuity-pill continuity-pill-${escapeAttr(issue.severity || "low")}">
              ${escapeHtml(CONTINUITY_SEVERITY_LABEL[issue.severity] || "风险")}
            </span>
            ${issue.recommended_action_label ? `<span class="continuity-action-label">${escapeHtml(issue.recommended_action_label)}</span>` : ""}
          </div>
          <p>${escapeHtml(issue.message || "")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

export function renderContinuityOverview(summary) {
  if (!summary) {
    return `<p class="timeline-continuity-note">当前还没有连续性校验结果。</p>`;
  }
  const generatedAt = summary.generated_at ? formatShortTime(summary.generated_at) : "未记录";
  const modeLabel = continuityReviewModeLabel(summary.review_mode_requested);
  const v2StatusLabel = CONTINUITY_V2_STATUS_LABEL[summary.v2_review_status] || summary.v2_review_status || "未执行";
  const topIssues = summary.top_issues?.length
    ? `
      <div class="continuity-hero-list">
        ${summary.top_issues.map((issue) => `
          <article class="continuity-inline-item">
            <span class="continuity-pill continuity-pill-${escapeAttr(issue.severity || "low")}">
              ${escapeHtml(CONTINUITY_SEVERITY_LABEL[issue.severity] || "风险")}
            </span>
            <p>${escapeHtml(issue.message || "")}</p>
          </article>
        `).join("")}
      </div>
    `
    : `<p class="timeline-continuity-note">当前没有检测到需要人工处理的连续性问题。</p>`;
  return `
    <div class="timeline-continuity-summary">
      <p class="timeline-continuity-note">
        ${escapeHtml(`最近校验：${generatedAt} · 状态：${CONTINUITY_STATUS_LABEL[summary.status] || summary.status || "未校验"}`)}
      </p>
      <div class="detail-chip-row">
        ${chip(`V2 模式 ${modeLabel}`)}
        ${chip(`V2 状态 ${v2StatusLabel}`)}
        ${summary.v2_issue_count ? `<span class="continuity-chip continuity-chip-medium">V2 问题 ${summary.v2_issue_count}</span>` : ""}
      </div>
      ${summary.v2_note ? `<p class="timeline-continuity-note">${escapeHtml(summary.v2_note)}</p>` : ""}
      ${topIssues}
    </div>
  `;
}
