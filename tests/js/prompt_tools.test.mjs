import assert from "node:assert/strict";

import { state } from "../../src/storyforge/api/static/app/state.js";
import {
  renderPromptEditorPanel,
  renderRequestInspectorPanel,
  resolveSelectedSegmentAssetOption,
} from "../../src/storyforge/api/static/app/render/prompt_tools.js";

const rootTask = {
  project_id: "project-1",
  task_id: "task-1",
};

const segment = {
  segmentId: "ch01-sc01-seg01",
  startFramePrompt: "计划首帧",
  midFramePrompt: "计划中段",
  endFramePrompt: "计划尾帧",
  videoPrompt: "计划视频",
  submittedVideoPrompt: "实际视频",
  submittedPromptVariant: "full_context",
  requiresMidFrame: true,
  startFrame: { name: "start" },
  midFrame: { name: "mid" },
  endFrame: { name: "end" },
  videoReady: true,
  startFrameRequest: {
    provider: "seedream",
    payload: { prompt: "实际首帧" },
    referenceBindings: [{ label: "图片1", kind: "scene" }],
  },
  midFrameRequest: null,
  endFrameRequest: null,
  videoRequest: {
    provider: "seedance",
    payload: { content: [{ type: "text", text: "实际视频" }] },
    referenceBindings: [{ label: "图片1", kind: "start" }],
  },
  motionPlan: {},
  submittedReferenceBindings: [],
  diagnostics: {
    status: "warning",
    risk_types: ["容量过载"],
    action_node_count: 4,
    action_node_budget: 3,
    duration_auto_expanded_from: 8,
    duration_seconds: 10,
    timed_beat_count: 3,
    timed_beat_end_seconds: 10,
    missing_tail_seconds: 0,
    requires_mid_frame: true,
    mid_frame_mode: "continuous",
    subsegment_index: 1,
    subsegment_count: 2,
    repair_source: "timeline_repair",
  },
};

state.selectedSegmentAssetKind = "start";
const startOption = resolveSelectedSegmentAssetOption(segment);
assert.equal(startOption.kind, "start");

const startEditorHtml = renderPromptEditorPanel(segment, rootTask, startOption);
assert.match(startEditorHtml, /data-save-and-rerun-segment-prompt="ch01-sc01-seg01"/);
assert.match(startEditorHtml, /data-frame-kind="start"/);
assert.doesNotMatch(startEditorHtml, /data-generate-scene-segment=/);
assert.doesNotMatch(startEditorHtml, /data-generate-video-segment=/);
assert.match(startEditorHtml, /计划首帧/);
assert.doesNotMatch(startEditorHtml, /计划尾帧/);
assert.doesNotMatch(startEditorHtml, /计划视频/);

const startInspectorHtml = renderRequestInspectorPanel(segment, startOption);
assert.match(startInspectorHtml, /Prompt Diff/);
assert.match(startInspectorHtml, /规划诊断/);
assert.match(startInspectorHtml, /动作点/);
assert.match(startInspectorHtml, /4 \/ 3/);
assert.match(startInspectorHtml, /8s -&gt; 10s/);
assert.match(startInspectorHtml, /完整诊断 JSON/);
assert.match(startInspectorHtml, /timeline_repair/);
assert.match(startInspectorHtml, /实际首帧/);
assert.doesNotMatch(startInspectorHtml, /视频实际提交 Prompt/);

state.selectedSegmentAssetKind = "video";
const videoOption = resolveSelectedSegmentAssetOption(segment);
assert.equal(videoOption.kind, "video");

const videoEditorHtml = renderPromptEditorPanel(segment, rootTask, videoOption);
assert.match(videoEditorHtml, /保存并重做视频/);
assert.doesNotMatch(videoEditorHtml, /data-frame-kind=/);
assert.doesNotMatch(videoEditorHtml, /data-generate-video-segment=/);
assert.match(videoEditorHtml, /计划视频/);
assert.doesNotMatch(videoEditorHtml, /计划首帧/);

const videoInspectorHtml = renderRequestInspectorPanel(segment, videoOption);
assert.match(videoInspectorHtml, /视频实际提交 Prompt/);
assert.match(videoInspectorHtml, /实际视频/);
assert.doesNotMatch(videoInspectorHtml, /首帧实际提交参数/);

console.log("prompt_tools render tests passed");
