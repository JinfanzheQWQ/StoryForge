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
import {
  saveStorySourceDraft,
  updateStoryChapterDraft,
  updateStoryTitleDraft,
} from "./story_source.js";
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
    await selectProjectRun(runButton.dataset.selectProjectRun);
    return;
  }

  const tabButton = event.target.closest("[data-detail-tab]");
  if (tabButton) {
    state.projectDetailTab = tabButton.dataset.detailTab;
    renderProjectDetail();
    return;
  }

  const saveStoryButton = event.target.closest("[data-save-story-source]");
  if (saveStoryButton) {
    try {
      await saveStorySourceDraft(
        saveStoryButton.dataset.storySourceProject,
        saveStoryButton.dataset.saveStorySource,
      );
      await refreshTasks();
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "故事文本保存失败。";
      renderProjectDetail();
    }
    return;
  }

  const analysisButton = event.target.closest("[data-generate-story-analysis]");
  if (analysisButton) {
    try {
      await submitStageJob(
        "/v1/projects/story-analysis",
        {
          project_id: analysisButton.dataset.storySourceProject,
          source_task_id: analysisButton.dataset.generateStoryAnalysis,
        },
        "结构化任务已创建",
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "结构化任务提交失败。";
    }
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
  void selectQueueTask(button.dataset.selectQueueTask);
}

async function handleQueueDetailClick(event) {
  const tabButton = event.target.closest("[data-detail-tab]");
  if (tabButton) {
    state.queueDetailTab = tabButton.dataset.detailTab;
    renderQueueDetail();
    return;
  }

  const saveStoryButton = event.target.closest("[data-save-story-source]");
  if (saveStoryButton) {
    try {
      await saveStorySourceDraft(
        saveStoryButton.dataset.storySourceProject,
        saveStoryButton.dataset.saveStorySource,
      );
      await refreshTasks();
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "故事文本保存失败。";
      renderQueueDetail();
    }
    return;
  }

  const analysisButton = event.target.closest("[data-generate-story-analysis]");
  if (analysisButton) {
    try {
      await submitStageJob(
        "/v1/projects/story-analysis",
        {
          project_id: analysisButton.dataset.storySourceProject,
          source_task_id: analysisButton.dataset.generateStoryAnalysis,
        },
        "结构化任务已创建",
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "结构化任务提交失败。";
    }
    return;
  }

  const previewButton = event.target.closest("[data-preview-group]");
  if (previewButton) {
    openLightbox(previewButton.dataset.previewGroup, Number(previewButton.dataset.previewIndex));
  }
}

function handleStorySourceInput(event, context) {
  const container = context === "project" ? elements.projectDetailView : elements.queueDetailView;

  const titleInput = event.target.closest("[data-story-title-input]");
  if (titleInput) {
    updateStoryTitleDraft(
      titleInput.dataset.storySourceProject,
      titleInput.dataset.storySourceTask,
      titleInput.value,
    );
    titleInput.setAttribute("value", titleInput.value);
    syncStorySourceEditorChrome(container, titleInput.dataset.storySourceTask);
    return;
  }

  const chapterField = event.target.closest("[data-story-chapter-field]");
  if (!chapterField) {
    return;
  }

  updateStoryChapterDraft(
    chapterField.dataset.storySourceProject,
    chapterField.dataset.storySourceTask,
    Number(chapterField.dataset.storyChapterIndex),
    chapterField.dataset.storyChapterField,
    chapterField.value,
  );
  if (chapterField.tagName === "TEXTAREA") {
    chapterField.textContent = chapterField.value;
  } else {
    chapterField.setAttribute("value", chapterField.value);
  }
  syncStorySourceEditorChrome(container, chapterField.dataset.storySourceTask);
}

function syncStorySourceEditorChrome(container, sourceTaskId) {
  container
    .querySelectorAll(`[data-save-story-source="${CSS.escape(sourceTaskId)}"]`)
    .forEach((button) => {
      button.disabled = false;
      button.textContent = "保存正文";
    });
  container
    .querySelectorAll(`[data-generate-story-analysis="${CSS.escape(sourceTaskId)}"]`)
    .forEach((button) => {
      button.disabled = true;
    });
  container
    .querySelectorAll(`[data-story-status-note="${CSS.escape(sourceTaskId)}"]`)
    .forEach((node) => {
      node.textContent = "文本已修改，尚未保存。保存后再重新生成结构化信息。";
    });
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
  elements.projectDetailView.addEventListener("input", (event) => {
    handleStorySourceInput(event, "project");
  });
  elements.queueTaskList.addEventListener("click", handleQueueListClick);
  elements.queueDetailView.addEventListener("click", (event) => {
    void handleQueueDetailClick(event);
  });
  elements.queueDetailView.addEventListener("input", (event) => {
    handleStorySourceInput(event, "queue");
  });
  elements.refreshButton.addEventListener("click", () => {
    void refreshTasks();
  });
  elements.lightbox.addEventListener("click", handleLightboxClick);
  elements.lightboxCloseButton.addEventListener("click", closeLightbox);
  elements.lightboxPrevButton.addEventListener("click", () => stepLightbox(-1));
  elements.lightboxNextButton.addEventListener("click", () => stepLightbox(1));
  window.addEventListener("keydown", handleKeyDown);
}
