import { DETAIL_TABS, state } from "./state.js";

const VALID_PAGES = new Set(["home", "create", "projects", "project-detail"]);
const VALID_DETAIL_TABS = new Set(DETAIL_TABS.map((tab) => tab.id));

function readHashParams() {
  const rawHash = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  return new URLSearchParams(rawHash);
}

function setHashFromParams(params) {
  const url = new URL(window.location.href);
  const nextHash = params.toString();
  url.hash = nextHash ? `#${nextHash}` : "";
  window.history.replaceState(null, "", url);
}

export function hydrateStateFromLocation() {
  const params = readHashParams();
  const page = params.get("page");
  const projectId = params.get("project");
  const runId = params.get("run");
  const detailTab = params.get("tab");

  if (VALID_PAGES.has(page)) {
    state.currentPage = page;
  }
  if (projectId) {
    state.selectedProjectId = projectId;
  }
  if (runId) {
    state.selectedProjectTaskId = runId;
  }
  if (VALID_DETAIL_TABS.has(detailTab)) {
    state.projectDetailTab = detailTab;
  }
}

export function syncLocationFromState() {
  const params = new URLSearchParams();

  if (state.currentPage && state.currentPage !== "home") {
    params.set("page", state.currentPage);
  }

  if (state.currentPage === "project-detail" && state.selectedProjectId) {
    params.set("project", state.selectedProjectId);
    if (state.selectedProjectTaskId) {
      params.set("run", state.selectedProjectTaskId);
    }
    if (state.projectDetailTab && state.projectDetailTab !== "overview") {
      params.set("tab", state.projectDetailTab);
    }
  }

  setHashFromParams(params);
}
