import assert from "node:assert/strict";

import { registerGallery } from "../../src/storyforge/api/static/app/gallery.js";
import {
  buildSceneGroups,
  buildTimelineGalleryItems,
  buildTimelineSegments,
  renderTimelinePreview,
  segmentLabel,
} from "../../src/storyforge/api/static/app/render/timeline_data.js";

const plannedArtifacts = {
  full_story: { name: "full.mp4", url: "/full.mp4", path: "/full.mp4" },
  planned_segments: [
    {
      segment_id: "ch01-sc01-seg01",
      scene_id: "ch01-sc01",
      scene_title: "松林入口",
      scene_summary: "林屿在入口等待。",
      scene_anchor: "松林入口石柱",
      scene_bible: { location: "松林入口" },
      scene_transition_contract: { next_scene_entry_match: "林屿面向小径。" },
      scene_master_frame_status: "ready",
      covered_event_ids: ["ch01-ev01"],
      covered_event_summaries: ["等待"],
      chapter_number: 1,
      duration_seconds: 8,
      requires_mid_frame: true,
      scene_master_frame: { name: "ch01-sc01_master.png", url: "/scene.png", path: "/scene.png" },
      start_frame: { name: "ch01-sc01-seg01_start.png", url: "/start.png", path: "/start.png" },
      mid_frame: { name: "ch01-sc01-seg01_mid.png", url: "/mid.png", path: "/mid.png" },
      end_frame: { name: "ch01-sc01-seg01_end.png", url: "/end.png", path: "/end.png" },
      rendered_clip: { name: "ch01-sc01-seg01.mp4", url: "/clip.mp4", path: "/clip.mp4" },
      scene_master_frame_prompt: "场景母图 prompt",
      start_frame_prompt: "首帧 prompt",
      mid_frame_prompt: "中段 prompt",
      end_frame_prompt: "尾帧 prompt",
      video_prompt: "视频 prompt",
      submitted_video_prompt: "提交视频 prompt",
      seedance_motion_prompt: "图片1推进到图片2，再推进到图片3。",
      motion_plan: { image_1_to_2: "靠近" },
      diagnostics: { risk: "low" },
      submitted_prompt_variant: "full_context",
      scene_master_frame_request: { provider: "seedream", payload: { content: [{ type: "text", text: "scene" }] } },
      start_frame_request: { provider: "seedream", payload: { content: [{ type: "text", text: "start" }] } },
      mid_frame_request: { provider: "seedream", payload: { content: [{ type: "text", text: "mid" }] } },
      end_frame_request: { provider: "seedream", payload: { content: [{ type: "text", text: "end" }] } },
      video_request: { provider: "seedance", payload: { content: [{ type: "text", text: "video" }] } },
      submitted_reference_bindings: [{ label: "图片1", path: "/start.png" }],
      scene_ready: true,
      video_ready: true,
    },
  ],
};

const plannedSegments = buildTimelineSegments(plannedArtifacts);
assert.equal(plannedSegments.length, 1);
assert.equal(plannedSegments[0].segmentId, "ch01-sc01-seg01");
assert.equal(plannedSegments[0].title, "第 01 章 / 场景 01 / 片段 01");
assert.equal(plannedSegments[0].requiresMidFrame, true);
assert.equal(plannedSegments[0].midFrame.kind, "image");
assert.equal(plannedSegments[0].clip.kind, "video");
assert.equal(plannedSegments[0].sceneMasterFrameRequest.payload.content[0].text, "scene");
assert.equal(plannedSegments[0].videoRequest.payload.content[0].text, "video");
assert.deepEqual(plannedSegments[0].submittedReferenceBindings, [{ label: "图片1", path: "/start.png" }]);

const sceneGroups = buildSceneGroups(plannedSegments);
assert.equal(sceneGroups.length, 1);
assert.equal(sceneGroups[0].sceneId, "ch01-sc01");
assert.equal(sceneGroups[0].sceneMasterFrame.url, "/scene.png");
assert.equal(sceneGroups[0].segments[0].segmentId, "ch01-sc01-seg01");
assert.deepEqual(sceneGroups[0].coveredEventIds, ["ch01-ev01"]);

const plannedGalleryItems = buildTimelineGalleryItems(plannedArtifacts);
assert.deepEqual(plannedGalleryItems.map((item) => item.url), [
  "/full.mp4",
  "/scene.png",
  "/start.png",
  "/mid.png",
  "/end.png",
  "/clip.mp4",
]);
assert.equal(plannedGalleryItems[0].kind, "video");
assert.equal(plannedGalleryItems[1].kind, "image");

const fallbackArtifacts = {
  scene_frames: [
    { name: "ch01-sc02-seg01_start.png", url: "/fallback-start.png", path: "/fallback-start.png" },
    { name: "ch01-sc02-seg01_mid.png", url: "/fallback-mid.png", path: "/fallback-mid.png" },
    { name: "ch01-sc02-seg01_end.png", url: "/fallback-end.png", path: "/fallback-end.png" },
  ],
  rendered_clips: [
    { name: "ch01-sc02-seg01.mp4", url: "/fallback-clip.mp4", path: "/fallback-clip.mp4" },
  ],
  full_story: null,
};
const fallbackSegments = buildTimelineSegments(fallbackArtifacts);
assert.equal(fallbackSegments.length, 1);
assert.equal(fallbackSegments[0].segmentId, "ch01-sc02-seg01");
assert.equal(fallbackSegments[0].sceneReady, true);
assert.equal(fallbackSegments[0].videoReady, true);
assert.equal(fallbackSegments[0].midFrame.url, "/fallback-mid.png");
assert.deepEqual(
  buildTimelineGalleryItems(fallbackArtifacts).map((item) => item.kind),
  ["image", "image", "image", "video"],
);

const duplicateGallery = buildTimelineGalleryItems({
  planned_segments: [
    {
      segment_id: "ch01-sc01-seg02",
      scene_master_frame: { name: "scene.png", url: "/same.png", path: "/same.png" },
      start_frame: { name: "start.png", url: "/same.png", path: "/same.png" },
    },
  ],
});
assert.equal(duplicateGallery.length, 1);

registerGallery("timeline-data-test", [{ url: "/start.png", name: "start.png", kind: "image" }]);
assert.match(renderTimelinePreview({ url: "/start.png", name: "start.png", kind: "image" }, "首帧", "timeline-data-test"), /data-preview-index="0"/);
assert.match(renderTimelinePreview(null, "中段", "timeline-data-test"), /未生成/);
assert.equal(segmentLabel("ch01-sc01-seg02_01", 0), "第 01 章 / 场景 01 / 片段 02-01");
assert.equal(segmentLabel("", 2), "片段 3");

console.log("timeline data tests passed");
