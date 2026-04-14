import { applyProjectToForm } from "./form.js";
import { renderApplication } from "./render/application.js";
import { state } from "./state.js";
import { refreshSelectedProjectDetail, refreshSelectedStorySources } from "./refresh.js";

export async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  state.projectDetailTab = "overview";
  state.currentPage = "project-detail";
  await refreshSelectedProjectDetail();
  await refreshSelectedStorySources();
  renderApplication();
  elementsSafeScrollToTop("#project-detail-view");
}

export async function selectProjectRun(taskId) {
  state.selectedProjectTaskId = taskId;
  state.projectDetailTab = "overview";
  state.currentPage = "project-detail";
  await refreshSelectedStorySources();
  renderApplication();
  elementsSafeScrollToTop("#project-detail-view");
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

function elementsSafeScrollToTop(selector) {
  const element = document.querySelector(selector);
  if (element) {
    element.scrollTo({ top: 0, behavior: "smooth" });
  }
}
