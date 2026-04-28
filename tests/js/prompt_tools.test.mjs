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
  sceneMasterFramePrompt: "计划场景母图",
  videoPrompt: "计划视频",
  submittedVideoPrompt: "实际视频",
  submittedPromptVariant: "full_context",
  sceneMasterFrame: { name: "scene-master" },
  characterReferences: [{ name: "role-a" }],
  videoReady: true,
  sceneMasterFrameRequest: {
    provider: "seedream",
    payload: { prompt: "实际场景母图" },
    referenceBindings: [],
  },
  videoRequest: {
    provider: "seedance",
    payload: { content: [{ type: "text", text: "实际视频" }], first_frame: "/seg00-last.png", return_last_frame: true },
    referenceBindings: [{ label: "图片1", kind: "scene_master" }],
  },
  firstFrameUrl: "/seg00-last.png",
  lastFrameUrl: "/seg01-last.png",
  previousClipSegmentId: "ch01-sc01-seg00",
  previousClipVideoUrl: "/seg00.mp4",
  motionPlan: { scene_motion: "角色在场景母图中移动" },
  motionContract: { scene_master_url: "/scene.png" },
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
    subsegment_index: 1,
    subsegment_count: 2,
    repair_source: "timeline_repair",
  },
};

state.selectedSegmentAssetKind = "video";
const videoOption = resolveSelectedSegmentAssetOption(segment);
assert.equal(videoOption.kind, "video");

const videoEditorHtml = renderPromptEditorPanel(segment, rootTask, videoOption);
assert.match(videoEditorHtml, /保存并重做视频/);
assert.doesNotMatch(videoEditorHtml, /data-frame-kind=/);
assert.doesNotMatch(videoEditorHtml, /data-generate-video-segment=/);
assert.match(videoEditorHtml, /计划视频/);
assert.doesNotMatch(videoEditorHtml, /计划场景母图/);

const missingVideoEditorHtml = renderPromptEditorPanel({ ...segment, videoReady: false }, rootTask, videoOption);
assert.match(missingVideoEditorHtml, /保存并生成视频/);
assert.doesNotMatch(missingVideoEditorHtml, /保存并重做视频/);

const videoInspectorHtml = renderRequestInspectorPanel(segment, videoOption);
assert.match(videoInspectorHtml, /视频实际提交 Prompt/);
assert.match(videoInspectorHtml, /实际视频/);
assert.match(videoInspectorHtml, /视频帧连续性/);
assert.match(videoInspectorHtml, /尾帧承接/);
assert.match(videoInspectorHtml, /ch01-sc01-seg00/);
assert.match(videoInspectorHtml, /\/seg01-last.png/);
assert.match(videoInspectorHtml, /已开启/);
assert.match(videoInspectorHtml, /规划诊断/);
assert.match(videoInspectorHtml, /动作点/);
assert.match(videoInspectorHtml, /4 \/ 3/);
assert.match(videoInspectorHtml, /8s -&gt; 10s/);
assert.match(videoInspectorHtml, /完整诊断 JSON/);
assert.match(videoInspectorHtml, /timeline_repair/);

console.log("prompt_tools render tests passed");
