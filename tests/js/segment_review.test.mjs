import assert from "node:assert/strict";

import { state } from "../../src/storyforge/api/static/app/state.js";
import { renderSegmentReviewDetail } from "../../src/storyforge/api/static/app/render/segment_review.js";

const helpers = {
  buildBlockedSceneButtonLabel: () => "场景图被锁定",
  buildSegmentRepairButtonLabel: () => "智能修复该段",
  buildSegmentSceneButtonLabel: () => "生成场景图",
  buildSegmentVideoButtonLabel: () => "生成视频",
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
  requiresMidFrame: true,
  sceneReady: true,
  videoReady: true,
  startFrame: {},
  midFrame: {},
  endFrame: {},
  clip: {},
  startFramePrompt: "计划首帧",
  midFramePrompt: "计划中段",
  endFramePrompt: "计划尾帧",
  videoPrompt: "计划视频",
  submittedVideoPrompt: "实际视频",
  startFrameRequest: { payload: { prompt: "实际首帧" }, referenceBindings: [] },
  midFrameRequest: { payload: { prompt: "实际中段" }, referenceBindings: [] },
  endFrameRequest: { payload: { prompt: "实际尾帧" }, referenceBindings: [] },
  videoRequest: { payload: { content: [{ type: "text", text: "实际视频" }] }, referenceBindings: [] },
  motionPlan: {},
  submittedReferenceBindings: [],
  diagnostics: {},
};

state.selectedSegmentAssetKind = "start";
const startHtml = renderSegmentReviewDetail({ segment, index: 0, model, galleryId: "g", characterStatus: "completed", helpers });
assert.match(startHtml, /重做首帧/);
assert.match(startHtml, /data-generate-scene-segment="ch01-sc01-seg01"/);
assert.match(startHtml, /data-frame-kind="start"/);
assert.match(startHtml, /计划首帧/);
assert.doesNotMatch(startHtml, /保存并重做视频/);

state.selectedSegmentAssetKind = "video";
const videoHtml = renderSegmentReviewDetail({ segment, index: 0, model, galleryId: "g", characterStatus: "completed", helpers });
assert.match(videoHtml, /重做当前视频/);
assert.match(videoHtml, /data-generate-video-segment="ch01-sc01-seg01"/);
assert.doesNotMatch(videoHtml, /data-frame-kind="video"/);
assert.match(videoHtml, /保存并重做视频/);
assert.match(videoHtml, /计划视频/);
assert.doesNotMatch(videoHtml, /保存并重做首帧/);

console.log("segment_review render tests passed");
