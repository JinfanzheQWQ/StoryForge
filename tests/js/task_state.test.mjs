import assert from "node:assert/strict";

import {
  buildBatchRepairButtonLabel,
  buildBlockedSceneButtonLabel,
  buildMergeButtonLabel,
  buildSceneMasterButtonLabel,
  buildSceneRepairButtonLabel,
  buildSegmentRepairButtonLabel,
  buildSegmentSceneButtonLabel,
  buildSegmentVideoButtonLabel,
  getLatestBatchRepairTask,
  getLatestSceneMasterTask,
  getLatestSceneRepairTask,
  getLatestSegmentStageTask,
  getRepairAffectedSegmentIds,
  isBusyTaskStatus,
  resolveRepairRemainingActions,
} from "../../src/storyforge/api/static/app/render/task_state.js";

assert.equal(isBusyTaskStatus("queued"), true);
assert.equal(isBusyTaskStatus("running"), true);
assert.equal(isBusyTaskStatus("completed"), false);

const tasks = [
  {
    task_type: "project.scenes",
    status: "completed",
    created_at: "2026-04-26T10:00:00Z",
    payload: { segment_id: "ch01-sc01-seg01" },
    result: { story_source_revision: "rev-1" },
  },
  {
    task_type: "project.scenes",
    status: "completed",
    created_at: "2026-04-26T10:01:00Z",
    payload: { scene_id: "ch01-sc01", master_only: true },
    result: { story_source_revision: "rev-1" },
  },
  {
    task_type: "project.continuity_repair",
    status: "failed",
    created_at: "2026-04-26T10:02:00Z",
    payload: { scene_id: "ch01-sc01" },
    result: { story_source_revision: "rev-1" },
  },
  {
    task_type: "project.continuity_repair_batch",
    status: "completed",
    created_at: "2026-04-26T10:03:00Z",
    result: { story_source_revision: "rev-1", has_more_batches: true },
  },
];
const run = { tasks };

assert.equal(getLatestSegmentStageTask(run, "project.scenes", "ch01-sc01-seg01"), tasks[0]);
assert.equal(getLatestSceneMasterTask(run, "ch01-sc01"), tasks[1]);
assert.equal(getLatestSceneRepairTask(run, "ch01-sc01"), tasks[2]);
assert.equal(getLatestBatchRepairTask(run), tasks[3]);

assert.deepEqual(
  Array.from(getRepairAffectedSegmentIds({ result: { affected_segment_ids: [" ch01-sc01-seg01 ", "", null] } })),
  ["ch01-sc01-seg01"],
);

assert.equal(buildSceneMasterButtonLabel({ sceneMasterFrame: null }, "queued"), "场景母图生成中");
assert.equal(buildSceneMasterButtonLabel({ sceneMasterFrame: { url: "/scene.png" } }, "completed"), "重生成场景母图");
assert.equal(buildSceneMasterButtonLabel({ sceneMasterFrame: null }, "failed"), "重试场景母图");
assert.equal(buildSceneRepairButtonLabel("completed", true), "修复方案已更新");
assert.equal(buildSceneRepairButtonLabel("failed", false), "重试智能修复");
assert.equal(buildBatchRepairButtonLabel("completed", { result: { has_more_batches: true } }), "继续修下一批");
assert.equal(buildBatchRepairButtonLabel("completed", { result: {} }), "重新批量修复");

assert.equal(buildSegmentSceneButtonLabel({ sceneReady: false }, "failed"), "重试场景图");
assert.equal(buildSegmentSceneButtonLabel({ sceneReady: true }, "completed"), "重生成场景图");
assert.equal(buildBlockedSceneButtonLabel({ sceneReady: false }, "idle", "stale"), "先重生成角色图");
assert.equal(buildBlockedSceneButtonLabel({ sceneReady: false }, "idle", "idle"), "先生成角色图");
assert.equal(buildSegmentVideoButtonLabel({ videoReady: true }, "completed"), "重生成视频");
assert.equal(buildSegmentRepairButtonLabel({ videoReady: false, sceneReady: true }, "completed", false), "重新智能修复");
assert.equal(buildSegmentRepairButtonLabel({ videoReady: false, sceneReady: false }, "completed", true), "修复合同已更新");
assert.equal(buildMergeButtonLabel({ full_story: { url: "/full.mp4" } }, "completed"), "重新合并总片");

const repairTask = {
  task_type: "project.continuity_repair",
  status: "completed",
  created_at: "2026-04-26T10:00:00Z",
  payload: { scene_id: "ch01-sc01", segment_id: "ch01-sc01-seg01" },
  result: {
    story_source_revision: "rev-1",
    media_regeneration_required: true,
    pending_media_actions: ["regenerate_scene_master_frame", "regenerate_scene_images", "regenerate_video"],
    affected_segment_ids: ["ch01-sc01-seg01"],
  },
};
const remainingBefore = resolveRepairRemainingActions({ tasks: [repairTask] }, repairTask, "rev-1");
assert.deepEqual(remainingBefore, ["regenerate_scene_master_frame", "regenerate_scene_images", "regenerate_video"]);

const completedRun = {
  tasks: [
    repairTask,
    {
      task_type: "project.scenes",
      status: "completed",
      created_at: "2026-04-26T10:01:00Z",
      payload: { scene_id: "ch01-sc01", master_only: true },
      result: { story_source_revision: "rev-1" },
    },
    {
      task_type: "project.scenes",
      status: "completed",
      created_at: "2026-04-26T10:02:00Z",
      payload: { segment_id: "ch01-sc01-seg01" },
      result: { story_source_revision: "rev-1" },
    },
    {
      task_type: "project.videos",
      status: "completed",
      created_at: "2026-04-26T10:03:00Z",
      payload: { segment_id: "ch01-sc01-seg01" },
      result: { story_source_revision: "rev-1" },
    },
  ],
};
assert.deepEqual(resolveRepairRemainingActions(completedRun, repairTask, "rev-1"), []);

const staleRun = {
  tasks: [
    repairTask,
    {
      task_type: "project.videos",
      status: "completed",
      created_at: "2026-04-26T10:03:00Z",
      payload: { segment_id: "ch01-sc01-seg01" },
      result: { story_source_revision: "older-rev" },
    },
  ],
};
assert.deepEqual(resolveRepairRemainingActions(staleRun, repairTask, "rev-1"), [
  "regenerate_scene_master_frame",
  "regenerate_scene_images",
  "regenerate_video",
]);

console.log("task_state tests passed");
