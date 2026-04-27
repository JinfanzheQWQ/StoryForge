import assert from "node:assert/strict";

import { state } from "../../src/storyforge/api/static/app/state.js";
import {
  renderDocumentBlock,
  renderDocumentGroups,
  renderFullStoryBlock,
} from "../../src/storyforge/api/static/app/render/document_assets.js";

const emptyHtml = renderDocumentBlock("调试文件", []);
assert.match(emptyHtml, /调试文件/);
assert.match(emptyHtml, /暂无文件/);

const docHtml = renderDocumentBlock("项目文件", [
  { name: "story_source.json", url: "/docs/story_source.json", kind: "document" },
  { name: "custom_debug.json", url: "/docs/custom_debug.json", kind: "document" },
], "当前项目文件");
assert.match(docHtml, /项目文件/);
assert.match(docHtml, /当前项目文件/);
assert.match(docHtml, /故事正文源文件/);
assert.match(docHtml, /核心运行文件/);
assert.match(docHtml, /custom_debug.json/);
assert.match(docHtml, /其他文件/);
assert.match(docHtml, /打开文件/);

const groupsHtml = renderDocumentGroups([
  { name: "seedance_execution.json", url: "/seedance_execution.json", kind: "document" },
  { name: "seedance_manifest.json", url: "/seedance_manifest.json", kind: "document" },
  { name: "continuity_report.json", url: "/continuity_report.json", kind: "document" },
  { name: "continuity_repair_ch01-sc01.json", url: "/continuity_repair_ch01-sc01.json", kind: "document" },
  { name: "story_source.json", url: "/story_source.json", kind: "document" },
  { name: "unknown.log", url: "/unknown.log", kind: "document" },
]);
assert.ok(groupsHtml.indexOf("核心运行文件") < groupsHtml.indexOf("媒体任务清单"));
assert.ok(groupsHtml.indexOf("媒体任务清单") < groupsHtml.indexOf("修复与风险"));
assert.ok(groupsHtml.indexOf("修复与风险") < groupsHtml.indexOf("执行报告"));
assert.ok(groupsHtml.indexOf("执行报告") < groupsHtml.indexOf("其他文件"));
assert.match(groupsHtml, /视频执行报告/);
assert.match(groupsHtml, /视频提交清单/);
assert.match(groupsHtml, /连续性校验报告/);
assert.match(groupsHtml, /连续性修复报告/);
assert.match(groupsHtml, /unknown.log/);

assert.match(renderFullStoryBlock(null, "ctx"), /当前版本还没有生成完整成片/);
const video = { name: "full.mp4", url: "/full.mp4", path: "/runs/full.mp4" };
const fullHtml = renderFullStoryBlock(video, "ctx");
assert.match(fullHtml, /总片预览/);
assert.match(fullHtml, /data-preview-group="ctx:full:\/runs\/full.mp4"/);
assert.match(fullHtml, /data-preview-index="0"/);
assert.match(fullHtml, /src="\/full.mp4"/);
assert.equal(state.galleries.get("ctx:full:/runs/full.mp4")?.[0]?.url, "/full.mp4");

state.galleries.set("existing-gallery", [{ title: "full.mp4", url: "/full.mp4", kind: "video" }]);
const existingGalleryHtml = renderFullStoryBlock(video, "ctx", "existing-gallery");
assert.match(existingGalleryHtml, /data-preview-group="existing-gallery"/);
assert.match(existingGalleryHtml, /data-preview-index="0"/);

console.log("document_assets tests passed");
