import { elements } from "./dom.js";
import {
  applyBootstrapToForm,
  clearForm,
  clearProjectBinding,
  setSubmitStatus,
} from "./form.js";
import { submitProject, submitStageJob } from "./jobs.js";
import { closeLightbox, openLightbox, stepLightbox } from "./lightbox.js";
import {
  prepareRerunProject,
  selectProject,
  selectProjectRun,
  selectQueueTask,
  setCurrentPage,
} from "./navigation.js";
import { refreshTasks } from "./refresh.js";
import { renderProjectDetail } from "./render/projects.js";
import { renderQueueDetail } from "./render/queue.js";
import { state } from "./state.js";

function handlePageTabClick(event) {
  const button = event.target.closest("[data-page]");
  if (!button) {
    return;
  }
  setCurrentPage(button.dataset.page);
}

function handleWorkspaceNavigation(event) {
  const button = event.target.closest("[data-go-page]");
  if (button) {
    setCurrentPage(button.dataset.goPage);
    return;
  }

  const previewButton = event.target.closest("[data-preview-group]");
  if (previewButton) {
    openLightbox(previewButton.dataset.previewGroup, Number(previewButton.dataset.previewIndex));
  }
}

async function handleProjectListClick(event) {
  const projectButton = event.target.closest("[data-select-project]");
  if (!projectButton) {
    return;
  }
  await selectProject(projectButton.dataset.selectProject);
}

async function handleProjectDetailClick(event) {
  const rerunButton = event.target.closest("[data-rerun-project]");
  if (rerunButton) {
    prepareRerunProject(rerunButton.dataset.rerunProject, (detail) => {
      setSubmitStatus(`已载入故事 ${detail.story_title || detail.title_hint}，接下来会先新生成一版文本。`);
    });
    return;
  }

  const runButton = event.target.closest("[data-select-project-run]");
  if (runButton) {
    selectProjectRun(runButton.dataset.selectProjectRun);
    return;
  }

  const tabButton = event.target.closest("[data-detail-tab]");
  if (tabButton) {
    state.projectDetailTab = tabButton.dataset.detailTab;
    renderProjectDetail();
    return;
  }

  const characterButton = event.target.closest("[data-generate-characters]");
  if (characterButton) {
    try {
      await submitStageJob(
        "/v1/projects/characters",
        {
          project_id: state.selectedProjectId,
          source_task_id: characterButton.dataset.generateCharacters,
        },
        "角色图任务已创建",
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "角色图任务提交失败。";
    }
    return;
  }

  const sceneButton = event.target.closest("[data-generate-scenes]");
  if (sceneButton) {
    try {
      await submitStageJob(
        "/v1/projects/scenes",
        {
          project_id: state.selectedProjectId,
          source_task_id: sceneButton.dataset.generateScenes,
        },
        "场景图任务已创建",
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "场景图任务提交失败。";
    }
    return;
  }

  const videoButton = event.target.closest("[data-generate-videos]");
  if (videoButton) {
    try {
      await submitStageJob(
        "/v1/projects/videos",
        {
          project_id: state.selectedProjectId,
          source_task_id: videoButton.dataset.generateVideos,
        },
        "视频任务已创建",
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "视频任务提交失败。";
    }
    return;
  }

  const previewButton = event.target.closest("[data-preview-group]");
  if (previewButton) {
    openLightbox(previewButton.dataset.previewGroup, Number(previewButton.dataset.previewIndex));
  }
}

function handleQueueListClick(event) {
  const button = event.target.closest("[data-select-queue-task]");
  if (!button) {
    return;
  }
  selectQueueTask(button.dataset.selectQueueTask);
}

function handleQueueDetailClick(event) {
  const tabButton = event.target.closest("[data-detail-tab]");
  if (tabButton) {
    state.queueDetailTab = tabButton.dataset.detailTab;
    renderQueueDetail();
    return;
  }

  const previewButton = event.target.closest("[data-preview-group]");
  if (previewButton) {
    openLightbox(previewButton.dataset.previewGroup, Number(previewButton.dataset.previewIndex));
  }
}

function handleLightboxClick(event) {
  if (event.target.closest("[data-lightbox-close]")) {
    closeLightbox();
  }
}

function handleKeyDown(event) {
  if (elements.lightbox.classList.contains("hidden")) {
    return;
  }
  if (event.key === "Escape") {
    closeLightbox();
    return;
  }
  if (event.key === "ArrowLeft") {
    stepLightbox(-1);
    return;
  }
  if (event.key === "ArrowRight") {
    stepLightbox(1);
  }
}

export function bindEvents() {
  elements.form.addEventListener("submit", submitProject);
  elements.fillDemoButton.addEventListener("click", () => {
    if (!state.bootstrap) {
      return;
    }
    applyBootstrapToForm(state.bootstrap);
    clearProjectBinding();
    setSubmitStatus("已载入示例。");
  });
  elements.clearFormButton.addEventListener("click", clearForm);
  elements.clearProjectBindingButton.addEventListener("click", () => {
    clearProjectBinding();
    setSubmitStatus("已切回新故事模式。");
  });
  elements.pageTabs.addEventListener("click", handlePageTabClick);
  elements.workspaceShell.addEventListener("click", handleWorkspaceNavigation);
  elements.projectList.addEventListener("click", (event) => {
    void handleProjectListClick(event);
  });
  elements.projectDetailView.addEventListener("click", (event) => {
    void handleProjectDetailClick(event);
  });
  elements.queueTaskList.addEventListener("click", handleQueueListClick);
  elements.queueDetailView.addEventListener("click", handleQueueDetailClick);
  elements.refreshButton.addEventListener("click", () => {
    void refreshTasks();
  });
  elements.lightbox.addEventListener("click", handleLightboxClick);
  elements.lightboxCloseButton.addEventListener("click", closeLightbox);
  elements.lightboxPrevButton.addEventListener("click", () => stepLightbox(-1));
  elements.lightboxNextButton.addEventListener("click", () => stepLightbox(1));
  window.addEventListener("keydown", handleKeyDown);
}
