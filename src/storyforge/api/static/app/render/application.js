import { elements } from "../dom.js";
import { syncLocationFromState } from "../route_state.js";
import { state } from "../state.js";
import { renderHomeOverview } from "./home.js";
import { renderProjectDetail, renderProjectList } from "./projects.js";

function renderPageTabs() {
  elements.pageTabs.querySelectorAll("[data-page]").forEach((button) => {
    const matches = (
      button.dataset.page === state.currentPage
      || (state.currentPage === "project-detail" && button.dataset.page === "projects")
    );
    button.classList.toggle("active", matches);
  });

  document.querySelectorAll("[data-page-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pagePanel === state.currentPage);
  });
}

export function updateStats() {
  elements.totalStat.textContent = String(state.tasks.length);
  elements.runningStat.textContent = String(state.tasks.filter((task) => task.status === "running").length);
  elements.completedStat.textContent = String(state.tasks.filter((task) => task.status === "completed").length);
  elements.failedStat.textContent = String(state.tasks.filter((task) => task.status === "failed").length);
}

export function renderApplication() {
  state.galleries.clear();
  syncLocationFromState();
  renderPageTabs();
  renderHomeOverview();
  renderProjectList();
  renderProjectDetail();
}
