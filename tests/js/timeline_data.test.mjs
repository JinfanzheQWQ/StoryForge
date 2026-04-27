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
      scene_master_frame: { name: "ch01-sc01_master.png", url: "/scene.png", path: "/scene.png" },
      rendered_clip: { name: "ch01-sc01-seg01.mp4", url: "/clip.mp4", path: "/clip.mp4" },
      scene_master_frame_prompt: "场景母图 prompt",
      video_prompt: "视频 prompt",
      submitted_video_prompt: "提交视频 prompt",
      seedance_motion_prompt: "图片1为空场景母图，角色从入口走入场景并完成等待动作。",
      motion_plan: {
        scene_motion: "林屿从松林入口石柱旁站稳，视线沿小径向深处寻找。",
        camera_path: "固定中景带轻微呼吸感。",
      },
      motion_contract: { continuity_guard: "始终保持同一松林入口空间。" },
      diagnostics: { risk: "low" },
      submitted_prompt_variant: "full_context",
      scene_master_frame_request: { provider: "seedream", payload: { content: [{ type: "text", text: "scene" }] } },
      video_request: { provider: "seedance", payload: { content: [{ type: "text", text: "video" }] } },
      submitted_reference_bindings: [{ label: "图片1", path: "/scene.png" }],
      scene_ready: true,
      video_ready: true,
    },
  ],
};

const plannedSegments = buildTimelineSegments(plannedArtifacts);
assert.equal(plannedSegments.length, 1);
assert.equal(plannedSegments[0].segmentId, "ch01-sc01-seg01");
assert.equal(plannedSegments[0].title, "第 01 章 / 场景 01 / 片段 01");
assert.equal(plannedSegments[0].sceneMasterFrame.kind, "image");
assert.equal(plannedSegments[0].clip.kind, "video");
assert.equal(plannedSegments[0].sceneMasterFrameRequest.payload.content[0].text, "scene");
assert.equal(plannedSegments[0].videoRequest.payload.content[0].text, "video");
assert.deepEqual(plannedSegments[0].submittedReferenceBindings, [{ label: "图片1", path: "/scene.png" }]);

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
  "/clip.mp4",
]);
assert.equal(plannedGalleryItems[0].kind, "video");
assert.equal(plannedGalleryItems[1].kind, "image");

const fallbackArtifacts = {
  scene_frames: [
    { name: "ch01-sc02_master.png", url: "/fallback-scene.png", path: "/fallback-scene.png" },
  ],
  rendered_clips: [
    { name: "ch01-sc02-seg01.mp4", url: "/fallback-clip.mp4", path: "/fallback-clip.mp4" },
  ],
  full_story: null,
};
const fallbackSegments = buildTimelineSegments(fallbackArtifacts);
assert.equal(fallbackSegments.length, 1);
assert.equal(fallbackSegments[0].segmentId, "ch01-sc02-seg01");
assert.equal(fallbackSegments[0].sceneReady, false);
assert.equal(fallbackSegments[0].videoReady, true);
assert.deepEqual(
  buildTimelineGalleryItems(fallbackArtifacts).map((item) => item.kind),
  ["image", "video"],
);

const duplicateGallery = buildTimelineGalleryItems({
  planned_segments: [
    {
      segment_id: "ch01-sc01-seg02",
      scene_master_frame: { name: "scene.png", url: "/same.png", path: "/same.png" },
      rendered_clip: { name: "clip.mp4", url: "/same.png", path: "/same.png" },
    },
  ],
});
assert.equal(duplicateGallery.length, 1);

registerGallery("timeline-data-test", [{ url: "/scene.png", name: "scene.png", kind: "image" }]);
assert.match(renderTimelinePreview({ url: "/scene.png", name: "scene.png", kind: "image" }, "场景母图", "timeline-data-test"), /data-preview-index="0"/);
assert.match(renderTimelinePreview(null, "视频", "timeline-data-test"), /未生成/);
assert.equal(segmentLabel("ch01-sc01-seg02_01", 0), "第 01 章 / 场景 01 / 片段 02-01");
assert.equal(segmentLabel("", 2), "片段 3");

console.log("timeline data tests passed");
