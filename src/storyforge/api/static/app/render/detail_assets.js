import { state } from "../state.js";
import { findGalleryIndex, registerGallery } from "../gallery.js";
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
  escapeAttr,
  escapeHtml,
  formatShortTime,
  getSegmentContractProgress,
  kindLabel,
  metricCard,
  singleAssetMessage,
} from "../utils.js";

const DOCUMENT_META = {
  "story_source.json": {
    title: "故事正文源文件",
    category: "小说源",
    summary: "当前版本的事实文本源。保存正文后，场景结构、分段合同和媒体阶段都从这里继续。",
  },
  "novel_package.json": {
    title: "结构规划总包",
    category: "结构规划",
    summary: "运行态最小小说包，包含角色卡、章节规划和正文摘录，是分段合同、图片与视频阶段的正式输入。",
  },
  "novel_audit.json": {
    title: "结构规划审计包",
    category: "结构规划",
    summary: "保存 review、workflow_trace，以及从运行包中剥离的分析上下文，主要用于排错和人工审阅。",
  },
  "character_visual_bible.json": {
    title: "角色视觉设定",
    category: "视频规划",
    summary: "定义角色外观、服装、配色和定妆提示词，用来锁定视觉一致性。",
  },
  "character_image_manifest.json": {
    title: "角色图任务清单",
    category: "视频规划",
    summary: "记录每个角色图要怎么生成、输出到哪里，以及当前状态。",
  },
  "scene_plan.json": {
    title: "场景规划主文件",
    category: "视频规划",
    summary: "定义章节下的 scene 层，以及每个 scene 内部的多个视频片段，并记录 scene_master_frame 的 prompt、路径和状态。",
  },
  "scene_structure_source.json": {
    title: "场景结构恢复快照",
    category: "视频规划",
    summary: "保存分段合同开始前的原始 scene skeleton，仅供失败恢复时从当前位置继续，不参与图片和视频执行。",
  },
  "segment_plan.json": {
    title: "片段执行索引",
    category: "视频规划",
    summary: "保留给图片与视频执行阶段使用的 flat segment 索引，便于逐段生成和重试。",
  },
  "segment_contract_progress.json": {
    title: "分段合同进度",
    category: "视频规划",
    summary: "按 scene 记录分段合同执行进度、失败位置和断点恢复状态，用于失败后继续生成。",
  },
  "scene_image_manifest.json": {
    title: "场景帧任务清单",
    category: "视频规划",
    summary: "记录每个场景母图，以及每个片段的首帧、中段锚点帧、尾帧、角色参考图和输出位置。",
  },
  "seedream_character_execution.json": {
    title: "角色图执行报告",
    category: "执行报告",
    summary: "用来确认角色图阶段是否真正跑通，以及失败原因。",
  },
  "seedream_scene_execution.json": {
    title: "场景图执行报告",
    category: "执行报告",
    summary: "用来确认场景关键帧阶段是否真正跑通，以及失败原因。",
  },
  "seedance_manifest.json": {
    title: "视频提交清单",
    category: "视频提交",
    summary: "最终送给 Seedance 的 clip 列表，决定视频片段会如何被生成。",
  },
  "seedance_execution.json": {
    title: "视频执行报告",
    category: "执行报告",
    summary: "记录视频提交状态、完成数量、失败数量和下载结果。",
  },
  "continuity_report.json": {
    title: "连续性校验报告",
    category: "执行报告",
    summary: "连续性审校结果，包含 V1 规则校验与可选的 V2 LLM 软审校，汇总场景母图、关键帧承接、对白预算和视频执行风险。",
  },
};

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

const DOCUMENT_GROUP_ORDER = ["小说源", "结构规划", "视频规划", "视频提交", "执行报告", "其他文件"];

function groupDocuments(items) {
  const groups = new Map();
  items.forEach((item) => {
    const group = DOCUMENT_META[item.name]?.category || "其他文件";
    if (!groups.has(group)) {
      groups.set(group, []);
    }
    groups.get(group).push(item);
  });
  return DOCUMENT_GROUP_ORDER
    .filter((group) => groups.has(group))
    .map((group) => ({ title: group, items: groups.get(group) }));
}

function renderDocumentCard(item) {
  const meta = DOCUMENT_META[item.name] || {
    title: item.name,
    category: "其他文件",
    summary: "当前运行留下的附加文件，可按需打开查看原始内容。",
  };
  return `
    <article class="doc-card">
      <div class="doc-card-head">
        <span class="kind-tag">${escapeHtml(meta.category)}</span>
        <span class="doc-card-file">${escapeHtml(item.name)}</span>
      </div>
      <h5>${escapeHtml(meta.title)}</h5>
      <p>${escapeHtml(meta.summary)}</p>
      <div class="doc-card-actions">
        <a class="doc-link" href="${item.url}" target="_blank" rel="noreferrer">
          <span class="kind-tag">${kindLabel(item.kind)}</span>
          <strong>打开文件</strong>
        </a>
      </div>
    </article>
  `;
}

function renderDocumentBlock(title, items, summary = "") {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无文件。");
  }

  return `
    <article class="asset-block">
      <div class="doc-section-head">
        <div>
          <h4>${title}</h4>
          ${summary ? `<p class="asset-note">${escapeHtml(summary)}</p>` : ""}
        </div>
        <span class="doc-section-count">${items.length} 份</span>
      </div>
      <div class="doc-card-grid">
        ${items.map((item) => renderDocumentCard(item)).join("")}
      </div>
    </article>
  `;
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

function renderFullStoryBlock(item, context, galleryId = null) {
  if (!item) {
    return singleAssetMessage("总片", "当前版本还没有生成完整成片。");
  }

  const effectiveGroupId = galleryId || `${context}:full:${item.path}`;
  if (!galleryId) {
    registerGallery(effectiveGroupId, [{ ...item, kind: "video" }]);
  }
  const index = findGalleryIndex(effectiveGroupId, item);

  return `
    <article class="asset-block">
      <h4>总片预览</h4>
      <button
        type="button"
        class="preview-trigger"
        data-preview-group="${escapeAttr(effectiveGroupId)}"
        data-preview-index="${index}"
      >
        <video class="hero-video" controls preload="metadata" src="${item.url}"></video>
      </button>
      <div class="asset-meta">
        <a href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}</a>
      </div>
      <p class="asset-note">打开预览后可以继续切换其他视频内容。</p>
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
