import { state } from "../state.js";
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
import {
  renderAssetSectionIntro,
  renderSegmentSceneBlockedNotice,
  renderSegmentTaskError,
} from "./detail_common.js";
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
  buildSegmentContractFailureLabel,
  buildSegmentContractProgressLabel,
  buildOverviewNote,
  getSegmentContractProgress,
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

export function renderRunStageActions(run) {
  return renderRunStageActionPanel({
    run,
    helpers: RUN_STAGE_ACTION_HELPERS,
  });
}

export function renderRunTabContent(task, artifacts, context, activeTab, run = null) {
  if (activeTab === "story") {
    return renderStoryStructure({ task, context, run, helpers: STORY_STRUCTURE_HELPERS });
  }
  if (activeTab === "scenes") {
    return renderSceneWorkbench({ task, artifacts, context, run, helpers: SCENE_WORKBENCH_HELPERS });
  }
  if (activeTab === "segments") {
    return renderSegmentReviewWorkbench({ task, artifacts, context, run, helpers: SEGMENT_REVIEW_HELPERS });
  }
  if (activeTab === "debug") {
    return renderRequestDebugWorkbench({ task, artifacts, context, run, helpers: REQUEST_DEBUG_HELPERS });
  }
  return renderWorkbenchOverview({ task, artifacts, context, run, helpers: OVERVIEW_HELPERS });
}
