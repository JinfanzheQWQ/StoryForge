import assert from "node:assert/strict";

import {
  renderRequestDebugTab,
  resolveDebugDocuments,
} from "../../src/storyforge/api/static/app/render/request_debug.js";

const documents = [
  { name: "seedance_manifest.json" },
  { name: "continuity_report.json" },
  { name: "novel_package.json" },
];

const debugDocuments = resolveDebugDocuments(documents);
assert.deepEqual(debugDocuments.map((item) => item.name), [
  "seedance_manifest.json",
  "continuity_report.json",
]);

const task = {
  project_id: "project-1",
  task_id: "task-1",
};

const segment = {
  segmentId: "ch01-sc01-seg01",
  title: "入口等待",
  sceneMasterFramePrompt: "计划场景母图",
  videoPrompt: "计划视频",
  sceneMasterFrameRequest: {
    provider: "seedream",
    payload: { prompt: "实际场景母图 payload" },
    referenceBindings: [],
  },
  videoRequest: {
    provider: "seedance",
    payload: { content: [{ type: "text", text: "实际视频 payload" }] },
    referenceBindings: [{ label: "图片1", kind: "scene_master" }],
  },
  submittedVideoPrompt: "实际视频 payload",
  submittedReferenceBindings: [],
  motionPlan: {},
  diagnostics: {},
};

const helpers = {
  buildArtifactPendingMessage: () => "等待调试文件",
  buildTimelineSegments: () => [segment],
  renderAssetSectionIntro: (title, summary, chips) => `<header><h3>${title}</h3><p>${summary}</p>${chips}</header>`,
  renderDocumentBlock: (title, items, summary) => `<section><h4>${title}</h4><p>${summary}</p>${items.map((item) => item.name).join(",")}</section>`,
};

const html = renderRequestDebugTab({
  task,
  artifacts: {
    available: true,
    documents,
  },
  helpers,
});

assert.match(html, /请求与调试/);
assert.match(html, /ch01-sc01-seg01/);
assert.match(html, /入口等待/);
assert.match(html, /视频实际提交参数/);
assert.match(html, /实际视频 payload/);
assert.match(html, /图片1/);
assert.match(html, /seedance_manifest\.json/);
assert.match(html, /continuity_report\.json/);
assert.doesNotMatch(html, /novel_package\.json/);

const pendingHtml = renderRequestDebugTab({
  task,
  artifacts: { available: false },
  helpers,
});
assert.match(pendingHtml, /等待调试文件/);

console.log("request_debug render tests passed");
