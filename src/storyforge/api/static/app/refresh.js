import {
  fetchBootstrap,
  fetchProjectDetail,
  fetchProjects,
  fetchTaskArtifacts,
  fetchTasks,
} from "./api.js";
import { elements } from "./dom.js";
import { applyBootstrapToForm } from "./form.js";
import { renderApplication, updateStats } from "./render/application.js";
import { state } from "./state.js";
import {
  buildStorySourceKey,
  ensureStorySourceLoaded,
  resolveStorySourceLocator,
} from "./story_source.js";
import { getPipelineRootTaskId, getProjectRuns } from "./utils.js";

export async function loadBootstrap() {
  const payload = await fetchBootstrap();
  state.bootstrap = payload;
  window.storyforgeBootstrap = payload;
  applyBootstrapToForm(payload);

  elements.llmModel.textContent = `${payload.llm_provider} / ${payload.llm_model}`;
  elements.seedreamModel.textContent = payload.seedream_model;
  elements.seedanceModel.textContent = payload.seedance_model;
}

// 任务完成后再拉产物索引，避免轮询期反复请求还不存在的文件清单。
async function loadArtifactsIfNeeded(task) {
  if (!task.result?.output_dir) {
    return;
  }

  const versionKey = task.result?.artifact_revision || task.finished_at || task.status;
  if (task.status !== "running" && state.artifactVersionByTaskId.get(task.task_id) === versionKey) {
    return;
  }

  const payload = await fetchTaskArtifacts(task.task_id);
  if (!payload) {
    return;
  }

  state.artifactsByTaskId.set(task.task_id, payload);
  state.artifactVersionByTaskId.set(task.task_id, versionKey);
}

function isMediaPreviewActive() {
  const lightboxOpen = elements.lightbox && !elements.lightbox.classList.contains("hidden");
  if (lightboxOpen) {
    return true;
  }

  return Array.from(
    document.querySelectorAll("#project-detail-view video, #queue-detail-view video"),
  ).some((media) => !media.paused && !media.ended);
}

function ensureSelections() {
  const taskIds = new Set(state.tasks.map((task) => task.task_id));
  const projectIds = new Set(state.projects.map((project) => project.project_id));

  if (state.lastSubmittedTaskId && taskIds.has(state.lastSubmittedTaskId)) {
    const submittedTask = state.tasks.find((task) => task.task_id === state.lastSubmittedTaskId);
    state.selectedQueueTaskId = state.lastSubmittedTaskId;
    state.selectedProjectId = submittedTask?.project_id || state.selectedProjectId;
    state.selectedProjectTaskId = submittedTask ? getPipelineRootTaskId(submittedTask) : state.lastSubmittedTaskId;
    state.lastSubmittedTaskId = null;
  }

  if (!state.selectedQueueTaskId || !taskIds.has(state.selectedQueueTaskId)) {
    state.selectedQueueTaskId = state.tasks[0]?.task_id || null;
  }

  if (!state.selectedProjectId || !projectIds.has(state.selectedProjectId)) {
    state.selectedProjectId = state.projects[0]?.project_id || null;
  }
}

export async function refreshSelectedProjectDetail() {
  if (!state.selectedProjectId) {
    return;
  }

  try {
    const detail = await fetchProjectDetail(state.selectedProjectId);
    state.projectDetails.set(state.selectedProjectId, detail);
    const runs = getProjectRuns(detail);
    const rootTaskIds = new Set(runs.map((run) => run.rootTask?.task_id).filter(Boolean));
    if (!state.selectedProjectTaskId || !rootTaskIds.has(state.selectedProjectTaskId)) {
      state.selectedProjectTaskId = runs[0]?.rootTask?.task_id || null;
    }
  } catch {
    // 项目可能被删除或列表刚切换，忽略这次详情刷新即可。
  }
}

export async function refreshSelectedStorySources() {
  const targets = new Map();

  const detail = state.projectDetails.get(state.selectedProjectId);
  if (detail) {
    const runs = getProjectRuns(detail);
    const selectedRun =
      runs.find((run) => run.rootTask?.task_id === state.selectedProjectTaskId) || runs[0] || null;
    const locator = selectedRun?.rootTask
      ? resolveStorySourceLocator(selectedRun.rootTask, selectedRun)
      : null;
    if (locator) {
      targets.set(buildStorySourceKey(locator.projectId, locator.sourceTaskId), locator);
    }
  }

  const queueTask = state.tasks.find((task) => task.task_id === state.selectedQueueTaskId) || null;
  const queueLocator = queueTask ? resolveStorySourceLocator(queueTask) : null;
  if (queueLocator) {
    targets.set(buildStorySourceKey(queueLocator.projectId, queueLocator.sourceTaskId), queueLocator);
  }

  await Promise.allSettled(
    Array.from(targets.values()).map((target) =>
      ensureStorySourceLoaded(target.projectId, target.sourceTaskId),
    ),
  );
}

export async function refreshTasks() {
  elements.pollIndicator.textContent = "同步中";

  try {
    const [tasks, projects] = await Promise.all([fetchTasks(), fetchProjects()]);

    state.tasks = tasks;
    state.projects = projects;
    await Promise.allSettled(state.tasks.map(loadArtifactsIfNeeded));
    ensureSelections();
    await refreshSelectedProjectDetail();
    await refreshSelectedStorySources();
    const activeElement = document.activeElement;
    const isEditingStorySource = Boolean(
      activeElement
      && activeElement.matches
      && activeElement.matches("[data-story-title-input], [data-story-chapter-field]"),
    );
    updateStats();
    if (isEditingStorySource && state.storySourceDirtyKeys.size > 0) {
      elements.pollIndicator.textContent = "编辑中，已暂停详情区重绘";
      return;
    }
    if (isMediaPreviewActive()) {
      elements.pollIndicator.textContent = "预览中，已暂停详情区重绘";
      return;
    }
    renderApplication();
    elements.pollIndicator.textContent = `已同步 ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    elements.pollIndicator.textContent = `刷新失败：${error.message || "未知错误"}`;
  }
}
