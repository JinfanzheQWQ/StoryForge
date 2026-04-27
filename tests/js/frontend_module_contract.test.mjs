import assert from "node:assert/strict";

const modules = {
  detailAssets: await import("../../src/storyforge/api/static/app/render/detail_assets.js"),
  detailCommon: await import("../../src/storyforge/api/static/app/render/detail_common.js"),
  documentAssets: await import("../../src/storyforge/api/static/app/render/document_assets.js"),
  continuityUi: await import("../../src/storyforge/api/static/app/render/continuity_ui.js"),
  taskState: await import("../../src/storyforge/api/static/app/render/task_state.js"),
  timelineData: await import("../../src/storyforge/api/static/app/render/timeline_data.js"),
  promptTools: await import("../../src/storyforge/api/static/app/render/prompt_tools.js"),
  characterWorkbench: await import("../../src/storyforge/api/static/app/render/character_workbench.js"),
  overview: await import("../../src/storyforge/api/static/app/render/overview.js"),
  requestDebug: await import("../../src/storyforge/api/static/app/render/request_debug.js"),
  runStageActions: await import("../../src/storyforge/api/static/app/render/run_stage_actions.js"),
  sceneWorkbench: await import("../../src/storyforge/api/static/app/render/scene_workbench.js"),
  segmentReview: await import("../../src/storyforge/api/static/app/render/segment_review.js"),
  storyStructure: await import("../../src/storyforge/api/static/app/render/story_structure.js"),
  timeline: await import("../../src/storyforge/api/static/app/render/timeline.js"),
};

const expectedFunctionExports = {
  detailAssets: ["renderRunStageActions", "renderRunTabContent"],
  detailCommon: ["renderAssetSectionIntro", "renderSegmentSceneBlockedNotice", "renderSegmentTaskError"],
  documentAssets: ["renderDocumentBlock", "renderDocumentGroups", "renderFullStoryBlock"],
  continuityUi: [
    "buildContinuityLookup",
    "hasRecommendedContinuityAction",
    "renderBatchRepairNotice",
    "renderContinuityIssueList",
    "renderContinuityOverview",
    "renderContinuityRiskChips",
    "renderRepairPlanNotice",
  ],
  taskState: [
    "buildBatchRepairButtonLabel",
    "buildBlockedSceneButtonLabel",
    "buildMergeButtonLabel",
    "buildSceneMasterButtonLabel",
    "buildSceneRepairButtonLabel",
    "buildSegmentRepairButtonLabel",
    "buildSegmentSceneButtonLabel",
    "buildSegmentVideoButtonLabel",
    "getLatestBatchRepairTask",
    "getLatestSceneMasterTask",
    "getLatestSceneRepairTask",
    "getLatestSegmentStageTask",
    "getRepairAffectedSegmentIds",
    "isBusyTaskStatus",
    "resolveRepairRemainingActions",
  ],
  timelineData: [
    "buildSceneGroups",
    "buildTimelineGalleryItems",
    "buildTimelineSegments",
    "renderTimelinePreview",
    "segmentLabel",
  ],
  promptTools: [
    "getSegmentAssetOptions",
    "normalizeSubmittedRequest",
    "renderPromptEditorPanel",
    "renderPromptSection",
    "renderRequestInspectorPanel",
    "renderSubmittedRequest",
    "renderScenePromptPanel",
    "renderSegmentAssetSelector",
    "renderSegmentPromptPanel",
    "resolveSelectedSegmentAssetOption",
  ],
  characterWorkbench: ["renderCharacterWorkbenchTab"],
  overview: ["renderWorkbenchOverviewTab"],
  requestDebug: ["renderRequestDebugTab", "resolveDebugDocuments"],
  runStageActions: ["renderRunStageActions"],
  sceneWorkbench: ["renderSceneSegmentMatrix", "renderSceneWorkbenchTab"],
  segmentReview: ["renderSegmentReviewDetail", "renderSegmentReviewTab"],
  storyStructure: ["renderStoryTab"],
  timeline: ["renderTimelineTab"],
};

for (const [moduleName, exportNames] of Object.entries(expectedFunctionExports)) {
  for (const exportName of exportNames) {
    assert.equal(
      typeof modules[moduleName][exportName],
      "function",
      `${moduleName}.${exportName} should be a function`,
    );
  }
}

assert.equal(typeof modules.continuityUi.CONTINUITY_STATUS_LABEL, "object");
assert.equal(modules.continuityUi.CONTINUITY_STATUS_LABEL.healthy, "稳定");

assert.equal(modules.detailAssets.renderRunStageActions({}), "");
assert.match(
  modules.detailAssets.renderRunTabContent(
    { project_id: "project-1", task_id: "task-1" },
    { available: false },
    "project",
    "debug",
    null,
  ),
  /请求与调试/,
);

console.log("frontend module contract tests passed");
