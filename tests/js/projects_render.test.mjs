import assert from "node:assert/strict";

globalThis.document = {
  querySelector: () => ({ innerHTML: "", addEventListener: () => {}, classList: { add: () => {}, remove: () => {} } }),
  querySelectorAll: () => [],
};

const { state } = await import("../../src/storyforge/api/static/app/state.js");
const { renderProjectDetail, renderProjectList } = await import("../../src/storyforge/api/static/app/render/projects.js");
const { elements } = await import("../../src/storyforge/api/static/app/dom.js");

const projectList = { innerHTML: "" };
const projectDetailView = { innerHTML: "" };
elements.projectList = projectList;
elements.projectDetailView = projectDetailView;

const rootTask = {
  task_id: "task-root",
  project_id: "project-1",
  task_type: "project.story",
  status: "completed",
  created_at: "2026-04-27T00:00:00Z",
  payload: { brief: { genre: "青春" } },
  result: { pipeline_root_task_id: "task-root", story_source_revision: "rev-1" },
  artifacts: {
    available: true,
    character_images: [{ name: "hero.png", url: "/hero.png", kind: "image" }],
    scene_frames: [{ name: "scene.png", url: "/scene.png", kind: "image" }],
    rendered_clips: [],
    full_story: null,
  },
};

state.projects = [
  {
    project_id: "project-1",
    title_hint: "首页作品测试",
    story_title: "首页作品测试",
    brief: { idea: "两名学生在校园里告白。" },
    run_count: 1,
    full_story_count: 0,
    completed_run_count: 0,
    latest_status: "completed",
    updated_at: "2026-04-27T00:00:00Z",
  },
];
state.tasks = [rootTask];
state.projectDetails = new Map([
  [
    "project-1",
    {
      ...state.projects[0],
      tasks: [rootTask],
    },
  ],
]);
state.selectedProjectId = "project-1";
state.selectedProjectTaskId = "task-root";
state.projectListQuery = "";
state.projectListStatus = "all";
state.artifactsByTaskId = new Map();

renderProjectList();
assert.match(projectList.innerHTML, /首页作品测试/);
assert.match(projectList.innerHTML, /src="\/scene.png"/);
assert.doesNotMatch(projectList.innerHTML, /场景帧/);

renderProjectDetail();
assert.match(projectDetailView.innerHTML, /场景母图/);
assert.doesNotMatch(projectDetailView.innerHTML, /场景帧/);

console.log("projects render tests passed");
