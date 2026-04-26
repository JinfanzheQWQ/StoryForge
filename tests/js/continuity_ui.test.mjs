import assert from "node:assert/strict";

import {
  CONTINUITY_STATUS_LABEL,
  buildContinuityLookup,
  hasRecommendedContinuityAction,
  renderBatchRepairNotice,
  renderContinuityIssueList,
  renderContinuityOverview,
  renderContinuityRiskChips,
  renderRepairPlanNotice,
} from "../../src/storyforge/api/static/app/render/continuity_ui.js";

assert.equal(CONTINUITY_STATUS_LABEL.critical, "高风险");

const lookup = buildContinuityLookup([
  { segment_id: "ch01-sc01-seg01", issue_count: 1 },
  { segment_id: "", issue_count: 2 },
  null,
], "segment_id");
assert.equal(lookup.size, 1);
assert.equal(lookup.get("ch01-sc01-seg01").issue_count, 1);

assert.equal(
  hasRecommendedContinuityAction({ recommended_actions: ["regenerate_video"] }, "regenerate_video"),
  true,
);
assert.equal(hasRecommendedContinuityAction(null, "regenerate_video"), false);

assert.match(renderContinuityRiskChips(null), /连续性稳定/);
assert.match(
  renderContinuityRiskChips({ issue_count: 3, high_risk_count: 1, medium_risk_count: 1, low_risk_count: 1 }),
  /风险 3.*高 1.*中 1.*低 1/s,
);

assert.match(renderContinuityIssueList(null, "暂无风险"), /暂无风险/);
const issueHtml = renderContinuityIssueList({
  issues: [
    {
      severity: "high",
      message: "首帧跳变 <danger>",
      recommended_action_label: "重生成视频",
    },
  ],
});
assert.match(issueHtml, /高风险/);
assert.match(issueHtml, /重生成视频/);
assert.match(issueHtml, /首帧跳变 &lt;danger&gt;/);

const repairTask = {
  status: "completed",
  result: {
    media_regeneration_required: true,
    repair_summary: "合同已更新",
    pending_media_actions: ["regenerate_scene_images", "regenerate_video"],
  },
};
assert.match(renderRepairPlanNotice(repairTask), /合同已更新/);
assert.match(renderRepairPlanNotice(repairTask), /手动重生成场景图、手动重生成视频/);
assert.match(renderRepairPlanNotice(repairTask, []), /后续媒体任务已手动提交或完成/);
assert.equal(renderRepairPlanNotice({ status: "running", result: {} }), "");

assert.match(
  renderBatchRepairNotice({ status: "completed", result: { repair_summary: "批量完成 <ok>" } }),
  /批量完成 &lt;ok&gt;/,
);
assert.equal(renderBatchRepairNotice({ status: "completed", result: {} }), "");

assert.match(renderContinuityOverview(null), /当前还没有连续性校验结果/);
const overviewHtml = renderContinuityOverview({
  generated_at: "2026-04-26T10:00:00Z",
  status: "critical",
  review_mode_requested: "auto",
  v2_review_status: "completed",
  v2_issue_count: 2,
  v2_note: "软审校发现问题",
  top_issues: [{ severity: "medium", message: "中段丢人" }],
});
assert.match(overviewHtml, /状态：高风险/);
assert.match(overviewHtml, /V2 状态 已完成/);
assert.match(overviewHtml, /V2 问题 2/);
assert.match(overviewHtml, /中风险/);
assert.match(overviewHtml, /中段丢人/);

console.log("continuity_ui tests passed");
