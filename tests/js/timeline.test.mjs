import assert from "node:assert/strict";

import { renderTimelineTab } from "../../src/storyforge/api/static/app/render/timeline.js";

const rootTask = {
  project_id: "project-1",
  task_id: "task-1",
  result: { story_source_revision: "rev-1" },
};

const segment = {
  segmentId: "ch01-sc01-seg01",
  title: "入口等待",
  chapterNumber: 1,
  sceneId: "ch01-sc01",
  durationSeconds: 6,
  summary: "林屿等待苏晚。",
  sceneMasterFrame: { url: "/scene.png", kind: "image" },
  characterReferences: [{ url: "/linyu.png", kind: "image" }],
  clip: null,
  sceneReady: true,
  videoReady: false,
  videoPrompt: "计划视频",
  seedanceMotionPrompt: "林屿从场景母图中的入口位置走入并停下等待。",
  motionPlan: { scene_motion: "从入口站定到望向小径深处。" },
};

const sceneGroup = {
  sceneId: "ch01-sc01",
  sceneTitle: "入口等待",
  sceneSummary: "林屿在入口等待。",
  chapterNumber: 1,
  sceneMasterFrame: { url: "/scene.png", kind: "image" },
  sceneMasterFramePrompt: "场景母图 prompt",
  segments: [segment],
};

const helpers = {
  CONTINUITY_STATUS_LABEL: { high_risk: "高风险" },
  buildArtifactPendingMessage: () => "等待时间线素材",
  buildBatchRepairButtonLabel: () => "批量修复风险合同",
  buildBlockedSceneButtonLabel: () => "场景图被锁定",
  buildMergeButtonLabel: () => "合并总片",
  buildSceneGroups: () => [sceneGroup],
  buildSceneMasterButtonLabel: () => "重生成场景母图",
  buildSceneRepairButtonLabel: () => "修复 scene",
  buildSegmentRepairButtonLabel: () => "修复 segment",
  buildSegmentSceneButtonLabel: () => "生成场景图",
  buildSegmentVideoButtonLabel: () => "生成视频",
  buildTimelineGalleryItems: () => [sceneGroup.sceneMasterFrame, ...segment.characterReferences],
  buildTimelineSegments: () => [segment],
  buildContinuityLookup: (groups, keyField) => new Map((groups || []).map((item) => [item[keyField], item])),
  getLatestBatchRepairTask: () => null,
  getLatestSceneMasterTask: () => null,
  getLatestSceneRepairTask: () => null,
  getLatestSegmentStageTask: () => null,
  getRepairAffectedSegmentIds: () => new Set(),
  hasRecommendedContinuityAction: (group, action) => Boolean(group?.recommended_actions?.includes(action)),
  isBusyTaskStatus: (status) => ["queued", "running"].includes(status),
  renderBatchRepairNotice: () => "",
  renderContinuityIssueList: () => "",
  renderContinuityOverview: () => "",
  renderContinuityRiskChips: () => `<span>风险</span>`,
  renderFullStoryBlock: () => "",
  renderRepairPlanNotice: () => "",
  renderSegmentSceneBlockedNotice: () => "",
  renderSegmentTaskError: () => "",
  renderTimelinePreview: (_item, label) => `<figure>${label}</figure>`,
  resolveRepairRemainingActions: () => [],
  segmentLabel: (segmentId) => segmentId,
};

const run = {
  rootTask,
  latestSegmentContractsTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
  latestCharacterTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
  latestMergeTask: {
    status: "idle",
    result: { story_source_revision: "rev-1" },
  },
  tasks: [],
};

const html = renderTimelineTab({
  task: rootTask,
  artifacts: {
    available: true,
    full_story: null,
    continuity_summary: { status: "high_risk", high_risk_count: 1, medium_risk_count: 0 },
    continuity_scene_groups: [{ scene_id: "ch01-sc01", issue_count: 1, recommended_actions: ["regenerate_scene_master_frame"] }],
    continuity_segment_groups: [{ segment_id: "ch01-sc01-seg01", issue_count: 1, recommended_actions: ["regenerate_video"] }],
  },
  context: "ctx",
  run,
  helpers,
});

assert.match(html, /按视频片段审片/);
assert.match(html, /data-auto-repair-batch="task-1"/);
assert.match(html, /data-merge-videos="task-1"/);
assert.match(html, /data-auto-repair-scene="ch01-sc01"/);
assert.match(html, /data-generate-scene-master="ch01-sc01"/);
assert.match(html, /data-auto-repair-segment="ch01-sc01-seg01"/);
assert.match(html, /data-generate-scene-segment="ch01-sc01-seg01"/);
assert.match(html, /data-generate-video-segment="ch01-sc01-seg01"/);
assert.match(html, /场景母图 prompt/);
assert.match(html, /计划视频/);
assert.match(html, /recommended-action/);

const pendingHtml = renderTimelineTab({
  task: rootTask,
  artifacts: { available: false },
  context: "ctx",
  helpers,
});
assert.match(pendingHtml, /等待时间线素材/);

console.log("timeline render tests passed");
