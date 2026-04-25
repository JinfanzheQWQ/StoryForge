import assert from "node:assert/strict";

import { renderStoryTab } from "../../src/storyforge/api/static/app/render/story_structure.js";

const task = {
  project_id: "project-1",
  task_id: "task-1",
};

const locator = {
  projectId: "project-1",
  sourceTaskId: "task-1",
};

const storySource = {
  story_title: "松针上的光",
  story_source_revision: "2026-04-25T00:00:00Z",
  chapters: [
    {
      number: 1,
      title: "入口等待",
      summary: "林屿在入口等待苏晚。",
      markdown: "林屿站在公园入口。",
    },
  ],
};

const meta = {
  loading: false,
  saving: false,
  dirty: true,
  message: "",
};

const helpers = {
  getStorySourceDraft: () => storySource,
  getStorySourceMeta: () => meta,
  resolveSegmentContractsUiState: () => ({
    progress: { resume_ready: true },
    progressLabel: "1/2 场景",
    failureLabel: "失败于 ch01-sc02",
    resumeFromProgress: true,
    buttonLabel: "继续生成分段合同",
  }),
  resolveStorySourceLocator: () => locator,
};

const run = {
  rootTask: {
    result: { story_source_revision: "2026-04-25T00:00:00Z" },
  },
  latestSceneStructureTask: {
    status: "completed",
    result: { story_source_revision: "2026-04-25T00:00:00Z" },
  },
  latestSegmentContractsTask: {
    status: "failed",
    error: "LLM 输出过粗",
    result: { story_source_revision: "2026-04-25T00:00:00Z" },
  },
};

const html = renderStoryTab({ task, run, helpers });

assert.match(html, /可编辑小说正文/);
assert.match(html, /data-save-story-source="task-1"/);
assert.match(html, /保存正文/);
assert.match(html, /data-generate-scene-structure="task-1"/);
assert.match(html, /场景结构已完成/);
assert.match(html, /data-generate-segment-contracts="task-1"/);
assert.match(html, /data-resume-from-progress="true"/);
assert.match(html, /继续生成分段合同/);
assert.match(html, /支持失败后继续/);
assert.match(html, /失败原因：LLM 输出过粗/);
assert.match(html, /松针上的光/);
assert.match(html, /data-story-chapter-field="markdown"/);
assert.match(html, /林屿站在公园入口。/);

const missingHtml = renderStoryTab({
  task,
  helpers: {
    ...helpers,
    resolveStorySourceLocator: () => null,
  },
});
assert.match(missingHtml, /当前版本还没有可展示或编辑的故事正文。/);

const loadingHtml = renderStoryTab({
  task,
  helpers: {
    ...helpers,
    getStorySourceDraft: () => null,
    getStorySourceMeta: () => ({ loading: true, saving: false, dirty: false, message: "" }),
  },
});
assert.match(loadingHtml, /故事正文加载中。/);

console.log("story_structure render tests passed");
