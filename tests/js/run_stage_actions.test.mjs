import assert from "node:assert/strict";

import { renderRunStageActions } from "../../src/storyforge/api/static/app/render/run_stage_actions.js";

const rootTask = {
  status: "completed",
  project_id: "project-1",
  task_id: "task-1",
  result: { story_source_revision: "rev-1" },
};

const helpers = {
  buildMergeButtonLabel: () => "合并总片",
  getStorySourceMeta: () => ({ dirty: false, loading: false, saving: false }),
  resolveSegmentContractsUiState: () => ({
    progressLabel: "1/2 场景",
    failureLabel: "",
    resumeFromProgress: false,
    buttonLabel: "生成分段合同",
  }),
  resolveStorySourceLocator: () => ({ projectId: "project-1", sourceTaskId: "task-1" }),
};

const run = {
  rootTask,
  latestSceneStructureTask: { status: "completed", result: { story_source_revision: "rev-1" } },
  latestSegmentContractsTask: { status: "idle", result: { story_source_revision: "rev-1" } },
  latestCharacterTask: { status: "idle", result: { story_source_revision: "rev-1" } },
  latestSceneTask: { status: "idle", result: { story_source_revision: "rev-1" } },
  latestVideoTask: { status: "failed", error: "视频提交失败", result: { story_source_revision: "rev-1" } },
  latestMergeTask: { status: "idle", result: { story_source_revision: "rev-1" } },
  latestArtifacts: {
    planned_segments: [
      { scene_ready: true, video_ready: true },
      { scene_ready: true, video_ready: false },
    ],
  },
};

const html = renderRunStageActions({ run, helpers });

assert.match(html, /pipeline-rail/);
assert.match(html, /小说正文/);
assert.match(html, /场景结构/);
assert.match(html, /分段合同/);
assert.match(html, /V2 连续性软审校/);
assert.match(html, /<option value="auto" selected>自动<\/option>/);
assert.match(html, /data-generate-scene-structure="task-1"/);
assert.match(html, /data-generate-segment-contracts="task-1"/);
assert.match(html, /data-resume-from-progress="false"/);
assert.match(html, /data-generate-characters="task-1"/);
assert.match(html, /data-merge-videos="task-1"/);
assert.match(html, /合并总片/);
assert.match(html, /视频提交失败/);

const noRootHtml = renderRunStageActions({ run: {}, helpers });
assert.equal(noRootHtml, "");


const completedRun = {
  ...run,
  latestSegmentContractsTask: { status: "completed", result: { story_source_revision: "rev-1" } },
};
const completedHelpers = {
  ...helpers,
  resolveSegmentContractsUiState: () => ({
    progressLabel: "2/2 场景",
    failureLabel: "",
    resumeFromProgress: false,
    buttonLabel: "分段合同已完成",
  }),
};
const completedHtml = renderRunStageActions({ run: completedRun, helpers: completedHelpers });
assert.match(completedHtml, /stage-complete/);
assert.match(completedHtml, /分段合同已完成/);

console.log("run_stage_actions render tests passed");
