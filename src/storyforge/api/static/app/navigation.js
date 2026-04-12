import { applyProjectToForm } from "./form.js";
import { renderApplication } from "./render/application.js";
import { renderProjectDetail, renderProjectList } from "./render/projects.js";
import { renderQueueDetail, renderQueueList } from "./render/queue.js";
import { state } from "./state.js";
import { refreshSelectedProjectDetail } from "./refresh.js";

export async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  state.projectDetailTab = "overview";
  await refreshSelectedProjectDetail();
  renderProjectList();
  renderProjectDetail();
}

export function selectProjectRun(taskId) {
  state.selectedProjectTaskId = taskId;
  state.projectDetailTab = "overview";
  renderProjectDetail();
}

export function selectQueueTask(taskId) {
  state.selectedQueueTaskId = taskId;
  state.queueDetailTab = "overview";
  renderQueueList();
  renderQueueDetail();
}

export function setCurrentPage(page) {
  state.currentPage = page;
  renderApplication();
}

export function prepareRerunProject(projectId, onPrepared) {
  const detail = state.projectDetails.get(projectId);
  if (!detail) {
    return;
  }
  applyProjectToForm(detail);
  setCurrentPage("create");
  onPrepared(detail);
}
