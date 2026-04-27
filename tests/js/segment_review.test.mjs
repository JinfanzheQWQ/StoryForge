import assert from "node:assert/strict";

import { state } from "../../src/storyforge/api/static/app/state.js";
import { renderSegmentReviewDetail } from "../../src/storyforge/api/static/app/render/segment_review.js";

const helpers = {
  buildBlockedSceneButtonLabel: () => "场景图被锁定",
  buildSegmentRepairButtonLabel: () => "智能修复该段",
  buildSegmentSceneButtonLabel: () => "生成场景图",
  buildSegmentVideoButtonLabel: (_segment, status) => status === "running" ? "视频生成中" : "生成视频",
  renderContinuityIssueList: () => "",
  renderContinuityRiskChips: () => "",
  renderRepairPlanNotice: () => "",
  renderSegmentSceneBlockedNotice: () => "",
  renderSegmentTaskError: () => "",
  renderTimelinePreview: (_item, label) => `<figure>${label}</figure>`,
  segmentLabel: (segmentId) => segmentId,
};

const rootTask = {
  project_id: "project-1",
  task_id: "task-1",
};

const model = {
  rootTask,
  segmentContinuity: null,
  sceneTask: null,
  videoTask: null,
  repairTask: null,
  sceneTaskStatus: "idle",
  videoTaskStatus: "idle",
  repairTaskStatus: "idle",
  segmentRepairRemainingActions: [],
  sceneScopeLocked: false,
  segmentRepairLocked: false,
  canGenerateScene: true,
  canGenerateVideo: true,
  canRunRepair: false,
  sceneRecommended: false,
  videoRecommended: false,
};

const segment = {
  segmentId: "ch01-sc01-seg01",
  title: "入口等待",
  summary: "林屿等待苏晚。",
  chapterNumber: 1,
  sceneId: "ch01-sc01",
  durationSeconds: 6,
  sceneReady: true,
  videoReady: true,
  sceneMasterFrame: {},
  characterReferences: [{}],
  clip: {},
  sceneMasterFramePrompt: "计划场景母图",
  videoPrompt: "计划视频",
  submittedVideoPrompt: "实际视频",
  videoRequest: { payload: { content: [{ type: "text", text: "实际视频" }] }, referenceBindings: [] },
  motionPlan: { scene_motion: "从等待到抬头" },
  motionContract: { scene_master_url: "/scene.png" },
  submittedReferenceBindings: [],
  diagnostics: {
    status: "warning",
    risk_type: "动作容量过载",
    action_node_count: 3,
    action_node_budget: 2,
    duration_auto_expanded_from: 5,
    duration_seconds: 8,
    timed_beat_count: 2,
    timed_beat_end_seconds: 8,
    repair_source: "planner",
  },
};

state.selectedSegmentAssetKind = "video";
const videoHtml = renderSegmentReviewDetail({ segment, index: 0, model, galleryId: "g", characterStatus: "completed", helpers });
assert.match(videoHtml, /规划诊断摘要/);
assert.match(videoHtml, /动作容量过载/);
assert.match(videoHtml, /3 \/ 2/);
assert.match(videoHtml, /5s -&gt; 8s/);
assert.match(videoHtml, /重做当前视频/);
assert.match(videoHtml, /data-generate-video-segment="ch01-sc01-seg01"/);
assert.doesNotMatch(videoHtml, /data-frame-kind="video"/);
assert.match(videoHtml, /保存并重做视频/);
assert.match(videoHtml, /计划视频/);

const missingVideoHtml = renderSegmentReviewDetail({
  segment: { ...segment, videoReady: false, clip: null },
  index: 0,
  model,
  galleryId: "g",
  characterStatus: "completed",
  helpers,
});
assert.match(missingVideoHtml, /生成当前视频/);
assert.match(missingVideoHtml, /保存并生成视频/);
assert.doesNotMatch(missingVideoHtml, /重做当前视频/);

const runningVideoHtml = renderSegmentReviewDetail({
  segment,
  index: 0,
  model: { ...model, videoTaskStatus: "running", canGenerateVideo: false },
  galleryId: "g",
  characterStatus: "completed",
  helpers,
});
assert.match(runningVideoHtml, /视频生成中/);
assert.match(
  runningVideoHtml,
  /data-reset-segment-prompt="ch01-sc01-seg01"[\s\S]*?disabled[\s\S]*?>重置当前点 Prompt/,
);
assert.match(
  runningVideoHtml,
  /data-save-segment-prompts="ch01-sc01-seg01"[\s\S]*?disabled[\s\S]*?>保存视频 Prompt/,
);
assert.match(
  runningVideoHtml,
  /data-save-and-rerun-segment-prompt="ch01-sc01-seg01"[\s\S]*?disabled[\s\S]*?>保存并重做视频/,
);

console.log("segment_review render tests passed");
