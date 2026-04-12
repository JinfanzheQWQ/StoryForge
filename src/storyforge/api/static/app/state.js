export const state = {
  bootstrap: null,
  tasks: [],
  projects: [],
  projectDetails: new Map(),
  currentPage: "home",
  lastSubmittedTaskId: null,
  selectedQueueTaskId: null,
  selectedProjectId: null,
  selectedProjectTaskId: null,
  queueDetailTab: "overview",
  projectDetailTab: "overview",
  artifactsByTaskId: new Map(),
  artifactVersionByTaskId: new Map(),
  galleries: new Map(),
  lightboxGroupId: null,
  lightboxIndex: 0,
};

export const DETAIL_TABS = [
  { id: "overview", label: "概览" },
  { id: "docs", label: "文档" },
  { id: "images", label: "图片" },
  { id: "videos", label: "视频" },
];
