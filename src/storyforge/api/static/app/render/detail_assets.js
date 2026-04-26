import { state } from "../state.js";
import {
  renderScenePromptPanel,
  renderSegmentPromptPanel,
} from "./prompt_tools.js";
import {
  CONTINUITY_STATUS_LABEL,
  buildContinuityLookup,
  hasRecommendedContinuityAction,
  renderBatchRepairNotice,
  renderContinuityIssueList,
  renderContinuityOverview,
  renderContinuityRiskChips,
  renderRepairPlanNotice,
} from "./continuity_ui.js";
import {
  renderDocumentBlock,
  renderDocumentGroups,
  renderFullStoryBlock,
} from "./document_assets.js";
import { renderWorkbenchOverviewTab as renderWorkbenchOverview } from "./overview.js";
import { renderRequestDebugTab as renderRequestDebugWorkbench } from "./request_debug.js";
import { renderRunStageActions as renderRunStageActionPanel } from "./run_stage_actions.js";
import { renderSceneWorkbenchTab as renderSceneWorkbench } from "./scene_workbench.js";
import { renderSegmentReviewTab as renderSegmentReviewWorkbench } from "./segment_review.js";
import { renderStoryTab as renderStoryStructure } from "./story_structure.js";
import {
  buildBatchRepairButtonLabel,
  buildBlockedSceneButtonLabel,
  buildMergeButtonLabel,
  buildSceneMasterButtonLabel,
  buildSceneRepairButtonLabel,
  buildSegmentRepairButtonLabel,
  buildSegmentSceneButtonLabel,
  buildSegmentVideoButtonLabel,
  getLatestBatchRepairTask,
  getLatestSceneMasterTask,
  getLatestSceneRepairTask,
  getLatestSegmentStageTask,
  getRepairAffectedSegmentIds,
  isBusyTaskStatus,
  resolveRepairRemainingActions,
} from "./task_state.js";
import {
  buildSceneGroups,
  buildTimelineGalleryItems,
  buildTimelineSegments,
  renderTimelinePreview,
  segmentLabel,
} from "./timeline_data.js";
import { renderTimelineTab as renderTimelineWorkbench } from "./timeline.js";
import {
  getStorySourceDraft,
  getStorySourceMeta,
  resolveStorySourceLocator,
} from "../story_source.js";
import {
  buildArtifactPendingMessage,
  buildTaskErrorMessage,
  buildSegmentContractFailureLabel,
  buildSegmentContractProgressLabel,
  buildOverviewNote,
  escapeHtml,
  formatShortTime,
  getSegmentContractProgress,
  metricCard,
  singleAssetMessage,
} from "../utils.js";

function resolveSegmentContractsUiState(segmentContractsTask, segmentContractsStatus) {
  const progress = getSegmentContractProgress(segmentContractsTask);
  const progressLabel = buildSegmentContractProgressLabel(progress);
  const failureLabel = buildSegmentContractFailureLabel(progress);
  const resumeFromProgress = (
    segmentContractsStatus === "failed"
    && Boolean(progress?.resume_ready)
  );
  const buttonLabel =
    segmentContractsStatus === "completed"
      ? "分段合同已完成"
      : resumeFromProgress
        ? "从失败位置继续"
        : segmentContractsStatus === "failed" || segmentContractsStatus === "stale"
          ? "重新生成分段合同"
          : segmentContractsStatus === "running"
            ? progressLabel ? `分段合同生成中 · ${progressLabel}` : "分段合同生成中"
            : "生成分段合同";
  return {
    progress,
    progressLabel,
    failureLabel,
    resumeFromProgress,
    buttonLabel,
  };
}

function renderAssetSectionIntro(title, summary, chipsMarkup = "") {
  return `
    <article class="asset-block story-editor-hero">
      <div class="story-editor-head">
        <div>
          <h4>${title}</h4>
          <p class="asset-note">${escapeHtml(summary)}</p>
        </div>
        ${chipsMarkup ? `<div class="detail-chip-row">${chipsMarkup}</div>` : ""}
      </div>
    </article>
  `;
}

function renderSegmentTaskError(task, label) {
  const error = buildTaskErrorMessage(task);
  if (!error) {
    return "";
  }
  return `<p class="timeline-task-error">${escapeHtml(`${label}：${error}`)}</p>`;
}

function renderSegmentSceneBlockedNotice({
  segment,
  characterStatus,
  sceneScopeLocked,
  segmentRepairLocked,
  sceneTaskStatus,
  videoTaskStatus,
}) {
  if (characterStatus !== "completed") {
    if (characterStatus === "failed") {
      return '<p class="asset-note">角色图生成失败。请先重试角色图，再生成场景图。</p>';
    }
    if (characterStatus === "stale") {
      return '<p class="asset-note">角色图仍然对应旧文本版本。请先重新生成角色图，再生成场景图。</p>';
    }
    if (characterStatus === "queued" || characterStatus === "running") {
      return '<p class="asset-note">角色图正在生成。角色参考图完成后，这一段才能生成场景图。</p>';
    }
    if (!segment.sceneReady) {
      return '<p class="asset-note">请先生成角色图。场景图阶段依赖角色参考图，所以当前按钮会先锁定。</p>';
    }
  }
  if (sceneScopeLocked) {
    return '<p class="asset-note">当前 scene 正在修复或生成场景母图，暂时不能并发生成片段场景图。</p>';
  }
  if (segmentRepairLocked) {
    return '<p class="asset-note">当前片段正在智能修复。请等待修复完成后再生成场景图。</p>';
  }
  if (isBusyTaskStatus(sceneTaskStatus)) {
    return '<p class="asset-note">当前片段场景图正在生成，页面会自动刷新状态。</p>';
  }
  if (isBusyTaskStatus(videoTaskStatus)) {
    return '<p class="asset-note">当前片段视频正在生成，暂时不允许并发重跑场景图。</p>';
  }
  return "";
}

const SEGMENT_REVIEW_HELPERS = {
  buildArtifactPendingMessage,
  buildBlockedSceneButtonLabel,
  buildSegmentRepairButtonLabel,
  buildSegmentSceneButtonLabel,
  buildSegmentVideoButtonLabel,
  buildTimelineGalleryItems,
  buildTimelineSegments,
  buildContinuityLookup,
  getLatestBatchRepairTask,
  getLatestSegmentStageTask,
  hasRecommendedContinuityAction,
  isBusyTaskStatus,
  renderContinuityIssueList,
  renderContinuityRiskChips,
  renderRepairPlanNotice,
  renderSegmentSceneBlockedNotice,
  renderSegmentTaskError,
  renderTimelinePreview,
  resolveRepairRemainingActions,
  segmentLabel,
};

const SCENE_WORKBENCH_HELPERS = {
  buildArtifactPendingMessage,
  buildSceneGroups,
  buildSceneMasterButtonLabel,
  buildSceneRepairButtonLabel,
  buildTimelineGalleryItems,
  buildTimelineSegments,
  buildContinuityLookup,
  getLatestBatchRepairTask,
  getLatestSceneMasterTask,
  getLatestSceneRepairTask,
  hasRecommendedContinuityAction,
  isBusyTaskStatus,
  renderAssetSectionIntro,
  renderContinuityIssueList,
  renderContinuityRiskChips,
  renderRepairPlanNotice,
  renderSegmentTaskError,
  renderTimelinePreview,
  resolveRepairRemainingActions,
};

const REQUEST_DEBUG_HELPERS = {
  buildArtifactPendingMessage,
  buildTimelineSegments,
  renderAssetSectionIntro,
  renderDocumentBlock,
};

const TIMELINE_HELPERS = {
  CONTINUITY_STATUS_LABEL,
  buildArtifactPendingMessage,
  buildBatchRepairButtonLabel,
  buildBlockedSceneButtonLabel,
  buildMergeButtonLabel,
  buildSceneGroups,
  buildSceneMasterButtonLabel,
  buildSceneRepairButtonLabel,
  buildSegmentRepairButtonLabel,
  buildSegmentSceneButtonLabel,
  buildSegmentVideoButtonLabel,
  buildTimelineGalleryItems,
  buildTimelineSegments,
  buildContinuityLookup,
  getLatestBatchRepairTask,
  getLatestSceneMasterTask,
  getLatestSceneRepairTask,
  getLatestSegmentStageTask,
  getRepairAffectedSegmentIds,
  hasRecommendedContinuityAction,
  isBusyTaskStatus,
  renderBatchRepairNotice,
  renderContinuityIssueList,
  renderContinuityOverview,
  renderContinuityRiskChips,
  renderFullStoryBlock,
  renderRepairPlanNotice,
  renderSegmentSceneBlockedNotice,
  renderSegmentTaskError,
  renderTimelinePreview,
  resolveRepairRemainingActions,
  segmentLabel,
};

const OVERVIEW_HELPERS = {
  buildOverviewNote,
  buildSceneGroups,
  buildTimelineSegments,
  renderContinuityOverview,
  renderFullStoryBlock,
  renderRunStageActions,
};

const STORY_STRUCTURE_HELPERS = {
  getStorySourceDraft,
  getStorySourceMeta,
  resolveSegmentContractsUiState,
  resolveStorySourceLocator,
};

const RUN_STAGE_ACTION_HELPERS = {
  buildMergeButtonLabel,
  getStorySourceMeta,
  resolveSegmentContractsUiState,
  resolveStorySourceLocator,
};

function renderTimelineTab(task, artifacts, context, run = null) {
  return renderTimelineWorkbench({
    task,
    artifacts,
    context,
    run,
    helpers: TIMELINE_HELPERS,
  });
}


function renderWorkbenchOverviewTab(task, artifacts, context, run = null) {
  return renderWorkbenchOverview({
    task,
    artifacts,
    context,
    run,
    helpers: OVERVIEW_HELPERS,
  });
}


function renderSceneWorkbenchTab(task, artifacts, context, run = null) {
  return renderSceneWorkbench({
    task,
    artifacts,
    context,
    run,
    helpers: SCENE_WORKBENCH_HELPERS,
  });
}

function renderSegmentReviewTab(task, artifacts, context, run = null) {
  return renderSegmentReviewWorkbench({
    task,
    artifacts,
    context,
    run,
    helpers: SEGMENT_REVIEW_HELPERS,
  });
}

function renderRequestDebugTab(task, artifacts, context, run = null) {
  return renderRequestDebugWorkbench({
    task,
    artifacts,
    context,
    run,
    helpers: REQUEST_DEBUG_HELPERS,
  });
}

function renderOverviewTab(task, artifacts, context, run = null) {
  if (context === "project") {
    return renderTimelineTab(task, artifacts, context, run);
  }
  return `
    <section class="asset-grid">
      <article class="asset-block">
        <h4>制作概览</h4>
        <div class="detail-metrics">
          ${metricCard("创建时间", formatShortTime(task.created_at))}
          ${metricCard("角色图", String(artifacts?.character_images?.length || 0))}
          ${metricCard("场景帧", String(artifacts?.scene_frames?.length || 0))}
          ${metricCard("片段视频", String(artifacts?.rendered_clips?.length || 0))}
        </div>
        <p class="asset-note">${escapeHtml(buildOverviewNote(task, artifacts, run))}</p>
      </article>
      ${renderFullStoryBlock(artifacts?.full_story, context)}
    </section>
  `;
}

function renderStoryTab(task, context, run = null) {
  return renderStoryStructure({
    task,
    context,
    run,
    helpers: STORY_STRUCTURE_HELPERS,
  });
}

export function renderRunStageActions(run) {
  return renderRunStageActionPanel({
    run,
    helpers: RUN_STAGE_ACTION_HELPERS,
  });
}

export function renderRunTabContent(task, artifacts, context, activeTab, run = null) {
  if (activeTab === "story") {
    return renderStoryTab(task, context, run);
  }
  if (activeTab === "scenes") {
    return renderSceneWorkbenchTab(task, artifacts, context, run);
  }
  if (activeTab === "segments") {
    return renderSegmentReviewTab(task, artifacts, context, run);
  }
  if (activeTab === "debug") {
    return renderRequestDebugTab(task, artifacts, context, run);
  }
  return renderWorkbenchOverviewTab(task, artifacts, context, run);
}
