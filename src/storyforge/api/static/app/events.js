import { elements } from "./dom.js";
import { deleteProject } from "./api.js";
import { askProjectDeleteConfirmation } from "./confirm_modal.js";
import {
  applyBootstrapToForm,
  clearForm,
  clearProjectBinding,
  setSubmitStatus,
  syncLlmModelPreset,
} from "./form.js";
import { submitProject, submitStageJob } from "./jobs.js";
import { closeLightbox, openLightbox, stepLightbox } from "./lightbox.js";
import {
  prepareRerunProject,
  selectProject,
  selectProjectRun,
  setCurrentPage,
} from "./navigation.js";
import { refreshTasks } from "./refresh.js";
import { renderProjectDetail, renderProjectList } from "./render/projects.js";
import { syncLocationFromState } from "./route_state.js";
import {
  saveStorySourceDraft,
  updateStoryChapterDraft,
  updateStoryTitleDraft,
} from "./story_source.js";
import { state } from "./state.js";
import {
  getTaskRun,
  normalizeContinuityReviewMode,
  resolveRunContinuityReviewMode,
} from "./utils.js";

function handlePageTabClick(event) {
  const button = event.target.closest("[data-page]");
  if (!button) {
    return;
  }
  setCurrentPage(button.dataset.page);
}

function handleLibraryFilterClick(event) {
  const button = event.target.closest("[data-filter-scope][data-filter-status]");
  if (!button) {
    return;
  }

  const scope = button.dataset.filterScope;
  const status = button.dataset.filterStatus || "all";
  if (scope === "project") {
    state.projectListStatus = status;
    syncFilterChipGroup(elements.projectStatusFilters, state.projectListStatus);
    renderProjectList();
  }
}

function syncFilterChipGroup(container, activeStatus) {
  if (!container) {
    return;
  }
  container.querySelectorAll("[data-filter-status]").forEach((button) => {
    button.classList.toggle("active", button.dataset.filterStatus === activeStatus);
  });
}

function handleLibrarySearchInput(event) {
  if (event.target === elements.projectSearchInput) {
    state.projectListQuery = elements.projectSearchInput.value;
    renderProjectList();
  }
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

async function handleProjectListKeyDown(event) {
  const projectCard = event.target.closest("[data-select-project]");
  if (!projectCard) {
    return;
  }
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  await selectProject(projectCard.dataset.selectProject);
}

async function submitStageFromButton(
  button,
  endpoint,
  payload,
  successMessage,
  fallbackErrorMessage,
) {
  if (button.disabled) {
    return;
  }
  button.disabled = true;
  try {
    await submitStageJob(endpoint, payload, successMessage);
  } catch (error) {
    elements.pollIndicator.textContent = error.message || fallbackErrorMessage;
    button.disabled = false;
  }
}

function resolveContinuityReviewModeForSourceTask(sourceTaskId) {
  const run = getTaskRun(sourceTaskId);
  return resolveRunContinuityReviewMode(run);
}

function withContinuityReviewMode(sourceTaskId, payload) {
  return {
    ...payload,
    continuity_review_mode: resolveContinuityReviewModeForSourceTask(sourceTaskId),
  };
}

async function submitSceneStructureFromButton(button) {
  await submitStageFromButton(
    button,
    "/v1/projects/scene-structure",
    withContinuityReviewMode(button.dataset.generateSceneStructure, {
      project_id: button.dataset.storySourceProject,
      source_task_id: button.dataset.generateSceneStructure,
    }),
    "场景结构任务已创建",
    "场景结构任务提交失败。",
  );
}

async function submitSegmentContractsFromButton(button) {
  await submitStageFromButton(
    button,
    "/v1/projects/segment-contracts",
    withContinuityReviewMode(button.dataset.generateSegmentContracts, {
      project_id: button.dataset.storySourceProject,
      source_task_id: button.dataset.generateSegmentContracts,
    }),
    "分段合同任务已创建",
    "分段合同任务提交失败。",
  );
}

function clearDeletedProjectState(projectId) {
  const deletedTaskIds = new Set(
    state.tasks
      .filter((task) => task.project_id === projectId)
      .map((task) => task.task_id),
  );
  state.projectDetails.delete(projectId);
  state.storySources.forEach((_, key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySources.delete(key);
    }
  });
  state.storySourceDrafts.forEach((_, key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySourceDrafts.delete(key);
    }
  });
  state.storySourceMessages.forEach((_, key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySourceMessages.delete(key);
    }
  });
  state.storySourceDirtyKeys.forEach((key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySourceDirtyKeys.delete(key);
    }
  });
  state.storySourceLoadingKeys.forEach((key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySourceLoadingKeys.delete(key);
    }
  });
  state.storySourceSavingKeys.forEach((key) => {
    if (key.startsWith(`${projectId}:`)) {
      state.storySourceSavingKeys.delete(key);
    }
  });
  deletedTaskIds.forEach((taskId) => {
    state.artifactsByTaskId.delete(taskId);
    state.artifactVersionByTaskId.delete(taskId);
    state.runContinuityReviewModes.delete(taskId);
  });
  state.projects = state.projects.filter((project) => project.project_id !== projectId);
  state.tasks = state.tasks.filter((task) => task.project_id !== projectId);
  if (state.selectedProjectId === projectId) {
    state.selectedProjectId = null;
    state.selectedProjectTaskId = null;
    state.currentPage = "projects";
  }
}

async function handleProjectDetailClick(event) {
  const rerunButton = event.target.closest("[data-rerun-project]");
  if (rerunButton) {
    prepareRerunProject(rerunButton.dataset.rerunProject, (detail) => {
      setSubmitStatus(`已载入故事 ${detail.story_title || detail.title_hint}，接下来会先新生成一版文本。`);
    });
    return;
  }

  const deleteButton = event.target.closest("[data-delete-project]");
  if (deleteButton) {
    if (deleteButton.disabled) {
      return;
    }
    const projectId = deleteButton.dataset.deleteProject;
    const detail = state.projectDetails.get(projectId);
    const confirmed = await askProjectDeleteConfirmation({
      title: detail?.story_title || detail?.title_hint,
      taskCount: state.tasks.filter((task) => task.project_id === projectId).length,
    });
    if (!confirmed) {
      return;
    }
    deleteButton.disabled = true;
    try {
      const result = await deleteProject(projectId);
      clearDeletedProjectState(projectId);
      await refreshTasks();
      elements.pollIndicator.textContent = (
        `项目已删除，移除 ${result.deleted_task_count} 条任务记录，`
        + `清理 ${result.deleted_output_count} 个输出目录。`
      );
    } catch (error) {
      elements.pollIndicator.textContent = error.message || "项目删除失败。";
      deleteButton.disabled = false;
    }
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
    syncLocationFromState();
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

  const sceneStructureButton = event.target.closest("[data-generate-scene-structure]");
  if (sceneStructureButton) {
    await submitSceneStructureFromButton(sceneStructureButton);
    return;
  }

  const segmentContractsButton = event.target.closest("[data-generate-segment-contracts]");
  if (segmentContractsButton) {
    await submitSegmentContractsFromButton(segmentContractsButton);
    return;
  }

  const characterButton = event.target.closest("[data-generate-characters]");
  if (characterButton) {
    await submitStageFromButton(
      characterButton,
      "/v1/projects/characters",
      withContinuityReviewMode(characterButton.dataset.generateCharacters, {
        project_id: state.selectedProjectId,
        source_task_id: characterButton.dataset.generateCharacters,
      }),
      "角色图任务已创建",
      "角色图任务提交失败。",
    );
    return;
  }

  const sceneButton = event.target.closest("[data-generate-scenes]");
  if (sceneButton) {
    await submitStageFromButton(
      sceneButton,
      "/v1/projects/scenes",
      withContinuityReviewMode(sceneButton.dataset.generateScenes, {
        project_id: state.selectedProjectId,
        source_task_id: sceneButton.dataset.generateScenes,
      }),
      "场景图任务已创建",
      "场景图任务提交失败。",
    );
    return;
  }

  const sceneSegmentButton = event.target.closest("[data-generate-scene-segment]");
  if (sceneSegmentButton) {
    await submitStageFromButton(
      sceneSegmentButton,
      "/v1/projects/scenes",
      withContinuityReviewMode(sceneSegmentButton.dataset.sourceTask, {
        project_id: sceneSegmentButton.dataset.projectId || state.selectedProjectId,
        source_task_id: sceneSegmentButton.dataset.sourceTask,
        segment_id: sceneSegmentButton.dataset.generateSceneSegment,
      }),
      "片段场景图任务已创建",
      "片段场景图任务提交失败。",
    );
    return;
  }

  const sceneMasterButton = event.target.closest("[data-generate-scene-master]");
  if (sceneMasterButton) {
    await submitStageFromButton(
      sceneMasterButton,
      "/v1/projects/scenes",
      withContinuityReviewMode(sceneMasterButton.dataset.sourceTask, {
        project_id: sceneMasterButton.dataset.projectId || state.selectedProjectId,
        source_task_id: sceneMasterButton.dataset.sourceTask,
        scene_id: sceneMasterButton.dataset.generateSceneMaster,
        master_only: true,
      }),
      "场景母图任务已创建",
      "场景母图任务提交失败。",
    );
    return;
  }

  const repairSceneButton = event.target.closest("[data-auto-repair-scene]");
  if (repairSceneButton) {
    await submitStageFromButton(
      repairSceneButton,
      "/v1/projects/continuity-repair",
      withContinuityReviewMode(repairSceneButton.dataset.sourceTask, {
        project_id: repairSceneButton.dataset.projectId || state.selectedProjectId,
        source_task_id: repairSceneButton.dataset.sourceTask,
        scene_id: repairSceneButton.dataset.autoRepairScene,
      }),
      "场景修复规划任务已创建",
      "场景修复规划任务提交失败。",
    );
    return;
  }

  const repairBatchButton = event.target.closest("[data-auto-repair-batch]");
  if (repairBatchButton) {
    await submitStageFromButton(
      repairBatchButton,
      "/v1/projects/continuity-repair-batch",
      withContinuityReviewMode(repairBatchButton.dataset.sourceTask, {
        project_id: repairBatchButton.dataset.projectId || state.selectedProjectId,
        source_task_id: repairBatchButton.dataset.sourceTask,
      }),
      "批量合同修复任务已创建",
      "批量合同修复任务提交失败。",
    );
    return;
  }

  const videoButton = event.target.closest("[data-generate-videos]");
  if (videoButton) {
    await submitStageFromButton(
      videoButton,
      "/v1/projects/videos",
      withContinuityReviewMode(videoButton.dataset.generateVideos, {
        project_id: state.selectedProjectId,
        source_task_id: videoButton.dataset.generateVideos,
      }),
      "视频任务已创建",
      "视频任务提交失败。",
    );
    return;
  }

  const videoSegmentButton = event.target.closest("[data-generate-video-segment]");
  if (videoSegmentButton) {
    await submitStageFromButton(
      videoSegmentButton,
      "/v1/projects/videos",
      withContinuityReviewMode(videoSegmentButton.dataset.sourceTask, {
        project_id: videoSegmentButton.dataset.projectId || state.selectedProjectId,
        source_task_id: videoSegmentButton.dataset.sourceTask,
        segment_id: videoSegmentButton.dataset.generateVideoSegment,
      }),
      "片段视频任务已创建",
      "片段视频任务提交失败。",
    );
    return;
  }

  const repairSegmentButton = event.target.closest("[data-auto-repair-segment]");
  if (repairSegmentButton) {
    await submitStageFromButton(
      repairSegmentButton,
      "/v1/projects/continuity-repair",
      withContinuityReviewMode(repairSegmentButton.dataset.sourceTask, {
        project_id: repairSegmentButton.dataset.projectId || state.selectedProjectId,
        source_task_id: repairSegmentButton.dataset.sourceTask,
        segment_id: repairSegmentButton.dataset.autoRepairSegment,
      }),
      "片段修复规划任务已创建",
      "片段修复规划任务提交失败。",
    );
    return;
  }

  const mergeVideosButton = event.target.closest("[data-merge-videos]");
  if (mergeVideosButton) {
    await submitStageFromButton(
      mergeVideosButton,
      "/v1/projects/videos",
      withContinuityReviewMode(mergeVideosButton.dataset.mergeVideos, {
        project_id: mergeVideosButton.dataset.projectId || state.selectedProjectId,
        source_task_id: mergeVideosButton.dataset.mergeVideos,
        merge_only: true,
      }),
      "视频合并任务已创建",
      "视频合并任务提交失败。",
    );
    return;
  }

  const previewButton = event.target.closest("[data-preview-group]");
  if (previewButton) {
    openLightbox(previewButton.dataset.previewGroup, Number(previewButton.dataset.previewIndex));
  }
}

function handleStorySourceInput(event) {
  const container = elements.projectDetailView;

  const continuityModeSelect = event.target.closest("[data-run-continuity-review-mode]");
  if (continuityModeSelect) {
    const runRootTaskId = continuityModeSelect.dataset.runContinuityReviewMode;
    if (runRootTaskId) {
      state.runContinuityReviewModes.set(
        runRootTaskId,
        normalizeContinuityReviewMode(continuityModeSelect.value),
      );
      elements.pollIndicator.textContent = "已更新当前版本的 V2 连续性软审校模式。";
    }
    return;
  }

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
    .querySelectorAll(`[data-generate-scene-structure="${CSS.escape(sourceTaskId)}"]`)
    .forEach((button) => {
      button.disabled = true;
    });
  container
    .querySelectorAll(`[data-generate-segment-contracts="${CSS.escape(sourceTaskId)}"]`)
    .forEach((button) => {
      button.disabled = true;
    });
  container
    .querySelectorAll(`[data-story-status-note="${CSS.escape(sourceTaskId)}"]`)
    .forEach((node) => {
      node.textContent = "文本已修改，尚未保存。保存后再重新生成场景结构和分段合同。";
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
  elements.projectList.addEventListener("keydown", (event) => {
    void handleProjectListKeyDown(event);
  });
  elements.projectStatusFilters.addEventListener("click", handleLibraryFilterClick);
  elements.projectSearchInput.addEventListener("input", handleLibrarySearchInput);
  if (elements.llmProviderSelect) {
    elements.llmProviderSelect.addEventListener("change", syncLlmModelPreset);
  }
  elements.projectDetailView.addEventListener("click", (event) => {
    void handleProjectDetailClick(event);
  });
  elements.projectDetailView.addEventListener("input", (event) => {
    handleStorySourceInput(event);
  });
  elements.projectDetailView.addEventListener("change", (event) => {
    handleStorySourceInput(event);
  });
  if (elements.refreshButton) {
    elements.refreshButton.addEventListener("click", () => {
      void refreshTasks();
    });
  }
  elements.lightbox.addEventListener("click", handleLightboxClick);
  elements.lightboxCloseButton.addEventListener("click", closeLightbox);
  elements.lightboxPrevButton.addEventListener("click", () => stepLightbox(-1));
  elements.lightboxNextButton.addEventListener("click", () => stepLightbox(1));
  window.addEventListener("keydown", handleKeyDown);

  syncFilterChipGroup(elements.projectStatusFilters, state.projectListStatus);
}
