import assert from "node:assert/strict";

import {
  renderSceneSegmentMatrix,
  renderSceneWorkbenchTab,
} from "../../src/storyforge/api/static/app/render/scene_workbench.js";

const rootTask = {
  project_id: "project-1",
  task_id: "task-1",
  result: { story_source_revision: "rev-1" },
};

const sceneGroup = {
  sceneId: "ch01-sc01",
  sceneTitle: "入口等待",
  sceneSummary: "林屿在入口等待。",
  sceneAnchor: "松树公园入口",
  sceneBible: {
    location: "松树公园入口",
    time_window: "傍晚",
    lighting: "夕阳斜射",
    background_anchors: ["松树", "小径"],
  },
  sceneSpatialContinuityMode: "same_space_progression",
  sceneMasterReferenceImages: ["/prev-scene.png"],
  sceneTransitionContract: {
    scene_spatial_continuity_mode: "same_space_progression",
    shared_environment_anchors: ["小径", "松树"],
    spatial_relation_to_previous: "沿小径向松林深处推进。",
    forbidden_drift: "不要改变小径方向。",
    next_scene_entry_match: "林屿站在入口，面向小径。",
  },
  sceneMasterFrame: { url: "/scene.png" },
  sceneMasterFrameStatus: "ready",
  sceneMasterFramePrompt: "场景母图 prompt",
  segments: [
    {
      segmentId: "ch01-sc01-seg01",
      sceneMasterFrame: { url: "/scene.png" },
      characterReferences: [{ url: "/linyu.png" }],
      videoReady: false,
    },
  ],
};

const segmentContinuityLookup = new Map([
  ["ch01-sc01-seg01", { segment_id: "ch01-sc01-seg01", issue_count: 2, high_risk_count: 1 }],
]);

const matrixHtml = renderSceneSegmentMatrix({ sceneGroup, segmentContinuityLookup });
assert.match(matrixHtml, /ch01-sc01-seg01/);
assert.match(matrixHtml, /高 1/);
assert.match(matrixHtml, /<span class="matrix-state missing">缺<\/span>/);

const helpers = {
  buildArtifactPendingMessage: () => "等待素材",
  buildSceneGroups: () => [sceneGroup],
  buildSceneMasterButtonLabel: () => "重生成场景母图",
  buildSceneRepairButtonLabel: () => "修复 scene",
  buildTimelineGalleryItems: () => [sceneGroup.sceneMasterFrame],
  buildTimelineSegments: () => sceneGroup.segments,
  buildContinuityLookup: (groups, keyField) => new Map((groups || []).map((item) => [item[keyField], item])),
  getLatestBatchRepairTask: () => null,
  getLatestSceneMasterTask: () => null,
  getLatestSceneRepairTask: () => null,
  hasRecommendedContinuityAction: (group, action) => Boolean(group?.recommended_actions?.includes(action)),
  isBusyTaskStatus: (status) => ["queued", "running"].includes(status),
  renderAssetSectionIntro: (title, summary, chips) => `<header><h3>${title}</h3><p>${summary}</p>${chips}</header>`,
  renderContinuityIssueList: () => "",
  renderContinuityRiskChips: () => `<span>风险 1</span>`,
  renderRepairPlanNotice: () => "",
  renderSegmentTaskError: () => "",
  renderTimelinePreview: (_item, label) => `<figure>${label}</figure>`,
  resolveRepairRemainingActions: () => [],
};

const run = {
  rootTask,
  latestSegmentContractsTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
};

const html = renderSceneWorkbenchTab({
  task: rootTask,
  artifacts: {
    available: true,
    continuity_scene_groups: [{ scene_id: "ch01-sc01", issue_count: 1, recommended_actions: ["regenerate_scene_master_frame"] }],
    continuity_segment_groups: [{ segment_id: "ch01-sc01-seg01", issue_count: 2, high_risk_count: 1 }],
  },
  context: "ctx",
  run,
  helpers,
});

assert.match(html, /场景工作台/);
assert.match(html, /data-auto-repair-scene="ch01-sc01"/);
assert.match(html, /data-generate-scene-master="ch01-sc01"/);
assert.match(html, /recommended-action/);
assert.match(html, /场景母图 prompt/);
assert.match(html, /同一空间推进|same_space_progression/);
assert.match(html, /沿小径向松林深处推进/);
assert.match(html, /\/prev-scene\.png/);
assert.match(html, /ch01-sc01-seg01/);

console.log("scene_workbench render tests passed");
