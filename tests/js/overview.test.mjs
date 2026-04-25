import assert from "node:assert/strict";

import { renderWorkbenchOverviewTab } from "../../src/storyforge/api/static/app/render/overview.js";

const task = {
  project_id: "project-1",
  task_id: "task-1",
  result: { story_source_revision: "rev-1" },
};

const segments = [
  { segmentId: "ch01-sc01-seg01", sceneReady: true, videoReady: true, sceneId: "ch01-sc01" },
  { segmentId: "ch01-sc01-seg02", sceneReady: true, videoReady: false, sceneId: "ch01-sc01" },
];

const helpers = {
  buildOverviewNote: () => "默认下一步",
  buildSceneGroups: () => [{ sceneId: "ch01-sc01", segments }],
  buildTimelineSegments: () => segments,
  renderContinuityOverview: () => `<section>连续性概览</section>`,
  renderFullStoryBlock: () => `<section>总片预览</section>`,
  renderRunStageActions: () => `<section>阶段入口</section>`,
};

const run = {
  rootTask: task,
  latestSceneStructureTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
  latestSegmentContractsTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
  latestCharacterTask: {
    status: "completed",
    result: { story_source_revision: "rev-1" },
  },
};

const html = renderWorkbenchOverviewTab({
  task,
  artifacts: {
    continuity_summary: { high_risk_count: 2, medium_risk_count: 1 },
    full_story: null,
  },
  context: "ctx",
  run,
  helpers,
});

assert.match(html, /生产总览/);
assert.match(html, /下一步：进入分段审片台，逐段生成或重生成视频。/);
assert.match(html, /Scene/);
assert.match(html, /Segment/);
assert.match(html, /场景图/);
assert.match(html, /2\/2/);
assert.match(html, /视频/);
assert.match(html, /1\/2/);
assert.match(html, /高风险/);
assert.match(html, /中风险/);
assert.match(html, /阶段入口/);
assert.match(html, /连续性概览/);
assert.match(html, /总片预览/);

const noRunHtml = renderWorkbenchOverviewTab({
  task,
  artifacts: {},
  context: "ctx",
  helpers,
});
assert.match(noRunHtml, /默认下一步/);
assert.doesNotMatch(noRunHtml, /阶段入口/);

console.log("overview render tests passed");
