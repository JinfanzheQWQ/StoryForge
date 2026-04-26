import assert from "node:assert/strict";

import { state } from "../../src/storyforge/api/static/app/state.js";
import {
  renderRunStageActions,
  renderRunTabContent,
} from "../../src/storyforge/api/static/app/render/detail_assets.js";
import { buildStorySourceKey } from "../../src/storyforge/api/static/app/story_source.js";

const rootTask = {
  project_id: "project-1",
  task_id: "task-1",
  task_type: "project.story",
  status: "completed",
  created_at: "2026-04-26T10:00:00Z",
  result: {
    story_source_path: "/story_source.json",
    story_source_revision: "rev-1",
  },
};

const run = {
  rootTask,
  tasks: [],
  latestSceneStructureTask: {
    task_type: "project.scene_structure",
    status: "completed",
    created_at: "2026-04-26T10:01:00Z",
    result: { story_source_revision: "rev-1" },
  },
  latestSegmentContractsTask: {
    task_type: "project.segment_contracts",
    status: "completed",
    created_at: "2026-04-26T10:02:00Z",
    result: { story_source_revision: "rev-1" },
  },
  latestCharacterTask: {
    task_type: "project.characters",
    status: "completed",
    created_at: "2026-04-26T10:03:00Z",
    result: { story_source_revision: "rev-1" },
  },
  latestSceneTask: {
    task_type: "project.scenes",
    status: "idle",
    result: { story_source_revision: "rev-1" },
  },
  latestVideoTask: {
    task_type: "project.videos",
    status: "idle",
    result: { story_source_revision: "rev-1" },
  },
  latestMergeTask: {
    task_type: "project.videos",
    status: "idle",
    result: { story_source_revision: "rev-1" },
  },
};

const segment = {
  segment_id: "ch01-sc01-seg01",
  scene_id: "ch01-sc01",
  scene_title: "松林入口",
  scene_summary: "林屿在松林入口等待苏晚。",
  scene_anchor: "松林入口石柱",
  scene_bible: {
    location: "松林入口",
    time_window: "傍晚",
    lighting: "夕阳斜射",
    background_anchors: ["松树", "小径"],
  },
  scene_transition_contract: {
    next_scene_entry_match: "林屿站在入口，面向小径。",
  },
  scene_master_frame_status: "ready",
  covered_event_ids: ["ch01-ev01"],
  covered_event_summaries: ["等待"],
  title: "入口等待",
  summary: "林屿等待苏晚。",
  chapter_number: 1,
  duration_seconds: 6,
  requires_mid_frame: false,
  scene_master_frame: { name: "ch01-sc01_master.png", url: "/scene.png", path: "/scene.png" },
  start_frame: { name: "ch01-sc01-seg01_start.png", url: "/start.png", path: "/start.png" },
  end_frame: { name: "ch01-sc01-seg01_end.png", url: "/end.png", path: "/end.png" },
  rendered_clip: { name: "ch01-sc01-seg01.mp4", url: "/clip.mp4", path: "/clip.mp4" },
  scene_master_frame_prompt: "场景母图 prompt",
  start_frame_prompt: "首帧 prompt",
  end_frame_prompt: "尾帧 prompt",
  video_prompt: "视频 prompt",
  seedance_motion_prompt: "图片1到图片2自然推进。",
  motion_plan: { start_to_end: "从等待到抬头" },
  diagnostics: {
    status: "warning",
    risk_types: ["尾部留空"],
    action_node_count: 2,
    action_node_budget: 2,
    duration_seconds: 6,
    timed_beat_count: 2,
    timed_beat_end_seconds: 4,
    missing_tail_seconds: 2,
    requires_mid_frame: false,
    planner_warning_source: "timed_beats",
  },
  scene_ready: true,
  video_ready: true,
};

const artifacts = {
  available: true,
  character_images: [{ name: "林屿.png", url: "/linyu.png", path: "/linyu.png" }],
  scene_frames: [segment.start_frame, segment.end_frame],
  rendered_clips: [segment.rendered_clip],
  full_story: { name: "full.mp4", url: "/full.mp4", path: "/full.mp4" },
  documents: [
    { name: "story_source.json", url: "/story_source.json", kind: "document" },
    { name: "seedance_execution.json", url: "/seedance_execution.json", kind: "document" },
  ],
  planned_segments: [segment],
  continuity_summary: {
    status: "healthy",
    generated_at: "2026-04-26T10:04:00Z",
    review_mode_requested: "auto",
    v2_review_status: "completed",
    high_risk_count: 0,
    medium_risk_count: 0,
    top_issues: [],
  },
  continuity_scene_groups: [],
  continuity_segment_groups: [],
};
run.latestArtifacts = artifacts;

state.storySourceDrafts.set(buildStorySourceKey("project-1", "task-1"), {
  project_id: "project-1",
  source_task_id: "task-1",
  story_title: "松针上的光",
  story_source_revision: "rev-1",
  chapters: [
    {
      number: 1,
      title: "入口等待",
      summary: "林屿等待苏晚。",
      markdown: "林屿站在松林入口，等苏晚沿小径走来。",
    },
  ],
});

const overviewHtml = renderRunTabContent(rootTask, artifacts, "project", "overview", run);
assert.match(overviewHtml, /生产总览/);
assert.match(overviewHtml, /当前版本制作入口/);
assert.match(overviewHtml, /总片预览/);
assert.match(overviewHtml, /Scene/);
assert.match(overviewHtml, /Segment/);

const storyHtml = renderRunTabContent(rootTask, artifacts, "project", "story", run);
assert.match(storyHtml, /可编辑小说正文/);
assert.match(storyHtml, /松针上的光/);
assert.match(storyHtml, /data-generate-segment-contracts="task-1"/);

const scenesHtml = renderRunTabContent(rootTask, artifacts, "project", "scenes", run);
assert.match(scenesHtml, /场景工作台/);
assert.match(scenesHtml, /松林入口/);
assert.match(scenesHtml, /data-generate-scene-master="ch01-sc01"/);

const segmentsHtml = renderRunTabContent(rootTask, artifacts, "project", "segments", run);
assert.match(segmentsHtml, /分段审片台/);
assert.match(segmentsHtml, /入口等待/);
assert.match(segmentsHtml, /规划诊断摘要/);
assert.match(segmentsHtml, /尾部留空/);
assert.match(segmentsHtml, /data-select-review-segment="ch01-sc01-seg01"/);

const debugHtml = renderRunTabContent(rootTask, artifacts, "project", "debug", run);
assert.match(debugHtml, /请求与调试/);
assert.match(debugHtml, /seedance_execution.json/);
assert.match(debugHtml, /ch01-sc01-seg01/);
assert.match(debugHtml, /完整诊断 JSON/);

const fallbackHtml = renderRunTabContent(rootTask, artifacts, "task", "unknown", run);
assert.match(fallbackHtml, /生产总览/);
assert.match(fallbackHtml, /角色图/);
assert.match(fallbackHtml, /总片预览/);

const actionsHtml = renderRunStageActions(run);
assert.match(actionsHtml, /pipeline-rail/);
assert.match(actionsHtml, /生成角色定妆/);
assert.match(actionsHtml, /合并总片/);

console.log("detail_assets integration tests passed");
