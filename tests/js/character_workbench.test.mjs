import assert from "node:assert/strict";

import { renderCharacterWorkbenchTab } from "../../src/storyforge/api/static/app/render/character_workbench.js";

const task = {
  project_id: "project-1",
  task_id: "task-1",
};

const html = renderCharacterWorkbenchTab({
  task,
  artifacts: {
    character_images: [
      {
        name: "林屿.png",
        character_name: "林屿",
        url: "/characters/linyu.png",
        prompt: "林屿角色 prompt",
        status: "completed",
        candidate_url: "/characters/_candidates/linyu.png",
        character_request: {
          provider: "seedream-4.5",
          endpoint: "https://example.invalid/images/generations",
          variant: "text_only; refs=0",
          payload: { model: "seedream", prompt: "林屿角色 prompt", watermark: false },
          reference_bindings: [],
        },
      },
    ],
  },
  context: "ctx",
});

assert.match(html, /角色工作台/);
assert.match(html, /角色定妆图/);
assert.match(html, /林屿/);
assert.match(html, /林屿角色 prompt/);
assert.match(html, /data-character-operation-status/);
assert.match(html, /data-edit-character-prompt/);
assert.match(html, /data-save-character-prompt="林屿"/);
assert.match(html, /data-save-and-rerun-character-prompt="林屿"/);
assert.match(html, /data-project-id="project-1"/);
assert.match(html, /data-source-task="task-1"/);
assert.match(html, /角色图实际提交请求/);
assert.match(html, /text_only; refs=0/);
assert.match(html, /&quot;watermark&quot;: false/);
assert.match(html, /src="\/characters\/linyu.png"/);
assert.match(html, /新候选图/);
assert.match(html, /src="\/characters\/_candidates\/linyu.png"/);
assert.match(html, /放弃新图/);
assert.match(html, /使用新图/);
assert.match(html, /data-select-character-version="candidate"/);
assert.match(html, /data-select-character-version="current"/);


const busyHtml = renderCharacterWorkbenchTab({
  task,
  artifacts: {
    character_images: [
      {
        name: "林屿.png",
        character_name: "林屿",
        url: "/characters/linyu.png",
        prompt: "林屿角色 prompt",
        status: "planned",
      },
    ],
  },
  context: "ctx-busy",
  run: {
    tasks: [
      {
        task_type: "project.characters",
        status: "running",
        payload: { character_name: "林屿" },
      },
    ],
  },
});
assert.match(busyHtml, /is-busy/);
assert.match(busyHtml, /该角色图正在重做/);
assert.match(busyHtml, /data-save-and-rerun-character-prompt="林屿"/);
assert.match(busyHtml, /disabled/);

const emptyHtml = renderCharacterWorkbenchTab({
  task,
  artifacts: {},
  context: "ctx",
});
assert.match(emptyHtml, /还没有角色图/);
assert.match(emptyHtml, /单角色重做入口/);

console.log("character_workbench render tests passed");
