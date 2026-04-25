import { state } from "../state.js";
import { findGalleryIndex, registerGallery } from "../gallery.js";
import {
  normalizeSubmittedRequest,
  renderPromptSection,
  renderScenePromptPanel,
  renderSegmentPromptPanel,
} from "./prompt_tools.js";
import { renderWorkbenchOverviewTab as renderWorkbenchOverview } from "./overview.js";
import { renderRequestDebugTab as renderRequestDebugWorkbench } from "./request_debug.js";
import { renderSceneWorkbenchTab as renderSceneWorkbench } from "./scene_workbench.js";
import { renderSegmentReviewTab as renderSegmentReviewWorkbench } from "./segment_review.js";
import { renderStoryTab as renderStoryStructure } from "./story_structure.js";
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
  buildTaskErrorMessage,
  chip,
  continuityReviewModeLabel,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  getSegmentContractProgress,
  getRunStageStatus,
  getStorySourceRevision,
  kindLabel,
  metricCard,
  resolveRunContinuityReviewMode,
  singleAssetMessage,
  stageStatusLabel,
  statusLabel,
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

const CONTINUITY_SEVERITY_LABEL = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

const CONTINUITY_STATUS_LABEL = {
  healthy: "稳定",
  warning: "需留意",
  critical: "高风险",
  unknown: "未校验",
};

const CONTINUITY_V2_STATUS_LABEL = {
  disabled: "已关闭",
  skipped: "自动跳过",
  completed: "已完成",
  failed: "失败",
};

const REPAIR_PENDING_ACTION_LABELS = {
  regenerate_scene_master_frame: "手动重生成场景母图",
  regenerate_scene_images: "手动重生成场景图",
  regenerate_video: "手动重生成视频",
};

function renderContinuityModeOptions(selectedMode) {
  const current = String(selectedMode || "auto").trim().toLowerCase() || "auto";
  return [
    ["auto", "自动"],
    ["on", "强制开启"],
    ["off", "关闭"],
  ].map(
    ([value, label]) => `<option value="${escapeAttr(value)}" ${value === current ? "selected" : ""}>${escapeHtml(label)}</option>`,
  ).join("");
}

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

function renderStageFailureList(run, storySourceRevision) {
  const failedStages = [
    ["场景结构", run.latestSceneStructureTask],
    ["分段合同", run.latestSegmentContractsTask],
    ["角色图", run.latestCharacterTask],
    ["场景图", run.latestSceneTask],
    ["视频", run.latestVideoTask],
    ["合并", run.latestMergeTask],
  ]
    .map(([label, task]) => {
      const status = getRunStageStatus(task, storySourceRevision);
      const error = buildTaskErrorMessage(task);
      if (status !== "failed" || !error) {
        return "";
      }
      return `
        <article class="stage-error-item">
          <strong>${escapeHtml(label)}</strong>
          <p>${escapeHtml(error)}</p>
        </article>
      `;
    })
    .filter(Boolean);

  if (failedStages.length === 0) {
    return "";
  }

  return `
    <div class="stage-error-list">
      ${failedStages.join("")}
    </div>
  `;
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

function renderCharacterPromptPanel(item) {
  const sections = [
    renderPromptSection("角色图 Prompt", item.prompt),
    renderPromptSection("一致性备注", item.consistency_notes, "character_image_manifest.json"),
  ].filter(Boolean);
  if (!sections.length) {
    return "";
  }
  return `
    <details class="prompt-panel">
      <summary>查看角色图 Prompt / 一致性备注</summary>
      <div class="prompt-panel-body">
        ${sections.join("")}
      </div>
    </details>
  `;
}

function renderMediaCard(item, galleryId) {
  const index = findGalleryIndex(galleryId, item);
  const isVideo = item.kind === "video";
  const preview = isVideo
    ? `<video controls preload="metadata" src="${item.url}"></video>`
    : `<img src="${item.url}" alt="${escapeAttr(item.name)}" loading="lazy" />`;
  const note = isVideo ? "可在预览里继续切换其他视频内容。" : "可在预览里继续切换其他图片内容。";
  const title = String(item.character_name || item.name || "").trim() || item.name;
  const metaChips = [
    item.provider ? chip(String(item.provider).trim()) : "",
    item.status ? chip(`状态 ${statusLabel(String(item.status).trim())}`) : "",
  ].filter(Boolean).join("");
  const characterPromptPanel = renderCharacterPromptPanel(item);
  const errorNote = String(item.status || "").trim() === "failed"
    ? String(item.error || "").trim()
    : "";

  return `
    <article class="media-card">
      <button
        type="button"
        class="preview-trigger"
        data-preview-group="${escapeAttr(galleryId)}"
        data-preview-index="${index}"
      >
        ${preview}
      </button>
      <div class="asset-meta">
        <a href="${item.url}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a>
      </div>
      ${metaChips ? `<div class="detail-chip-row">${metaChips}</div>` : ""}
      <p class="asset-note">${note}</p>
      ${errorNote ? `<p class="asset-note">${escapeHtml(errorNote)}</p>` : ""}
      ${characterPromptPanel}
    </article>
  `;
}

function renderMediaBlock(title, items, galleryId, summary = "") {
  if (!items?.length) {
    return singleAssetMessage(title, "暂无可预览内容。");
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
      <div class="media-grid">
        ${items.map((item) => renderMediaCard(item, galleryId)).join("")}
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

function segmentIdFromAssetName(name) {
  return String(name || "")
    .replace(/\.[^.]+$/, "")
    .replace(/_(start|mid|end)$/, "");
}

function segmentLabel(segmentId, index) {
  const text = String(segmentId || "").trim();
  if (!text) {
    return `片段 ${index + 1}`;
  }
  return text
    .replace(/^ch(\d+)-sc(\d+)-seg(\d+)$/i, "第 $1 章 / 场景 $2 / 片段 $3")
    .replace(/^ch(\d+)-sc(\d+)-seg(\d+)_(\d+)$/i, "第 $1 章 / 场景 $2 / 片段 $3-$4")
    .replace(/^ch(\d+)_seg(\d+)$/i, "第 $1 章 / 片段 $2")
    .replaceAll("_", " ");
}


function buildTimelineSegments(artifacts) {
  if (artifacts?.planned_segments?.length) {
    return artifacts.planned_segments.map((segment, index) => ({
      segmentId: segment.segment_id,
      sceneId: segment.scene_id || "",
      sceneTitle: segment.scene_title || "",
      sceneSummary: segment.scene_summary || "",
      sceneAnchor: segment.scene_anchor || "",
      sceneBible: segment.scene_bible && typeof segment.scene_bible === "object" ? segment.scene_bible : {},
      sceneTransitionContract: segment.scene_transition_contract && typeof segment.scene_transition_contract === "object"
        ? segment.scene_transition_contract
        : {},
      sceneMasterFrameStatus: segment.scene_master_frame_status || "",
      sceneMasterFrameError: segment.scene_master_frame_error || "",
      coveredEventIds: Array.isArray(segment.covered_event_ids) ? segment.covered_event_ids : [],
      coveredEventSummaries: Array.isArray(segment.covered_event_summaries) ? segment.covered_event_summaries : [],
      title: segment.title || segmentLabel(segment.segment_id, index),
      summary: segment.summary || "",
      chapterNumber: segment.chapter_number,
      durationSeconds: segment.duration_seconds || 0,
      requiresMidFrame: Boolean(segment.requires_mid_frame),
      sceneMasterFrame: segment.scene_master_frame ? { ...segment.scene_master_frame, kind: "image" } : null,
      startFrame: segment.start_frame ? { ...segment.start_frame, kind: "image" } : null,
      midFrame: segment.requires_mid_frame && segment.mid_frame
        ? { ...segment.mid_frame, kind: "image" }
        : null,
      endFrame: segment.end_frame ? { ...segment.end_frame, kind: "image" } : null,
      clip: segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
      sceneMasterFramePrompt: segment.scene_master_frame_prompt || "",
      startFramePrompt: segment.start_frame_prompt || "",
      midFramePrompt: segment.requires_mid_frame ? (segment.mid_frame_prompt || "") : "",
      endFramePrompt: segment.end_frame_prompt || "",
      videoPrompt: segment.video_prompt || "",
      submittedVideoPrompt: segment.submitted_video_prompt || "",
      seedanceMotionPrompt: segment.seedance_motion_prompt || "",
      motionPlan: segment.motion_plan && typeof segment.motion_plan === "object" ? segment.motion_plan : {},
      diagnostics: segment.diagnostics && typeof segment.diagnostics === "object" ? segment.diagnostics : {},
      submittedPromptVariant: segment.submitted_prompt_variant || "",
      sceneMasterFrameRequest: normalizeSubmittedRequest(segment.scene_master_frame_request),
      startFrameRequest: normalizeSubmittedRequest(segment.start_frame_request),
      midFrameRequest: segment.requires_mid_frame
        ? normalizeSubmittedRequest(segment.mid_frame_request)
        : null,
      endFrameRequest: normalizeSubmittedRequest(segment.end_frame_request),
      videoRequest: normalizeSubmittedRequest(segment.video_request),
      submittedReferenceBindings: Array.isArray(segment.submitted_reference_bindings)
        ? segment.submitted_reference_bindings
        : [],
      sceneReady: Boolean(segment.scene_ready),
      videoReady: Boolean(segment.video_ready),
    }));
  }

  const segmentMap = new Map();
  const ensureSegment = (segmentId) => {
    if (!segmentMap.has(segmentId)) {
        segmentMap.set(segmentId, {
          segmentId,
          sceneId: "",
          sceneTitle: "",
          sceneSummary: "",
          sceneAnchor: "",
          sceneBible: {},
          sceneTransitionContract: {},
          sceneMasterFrameStatus: "",
          sceneMasterFrameError: "",
          coveredEventIds: [],
          coveredEventSummaries: [],
        title: segmentId,
        summary: "",
        chapterNumber: 0,
        sceneMasterFrame: null,
        durationSeconds: 0,
        requiresMidFrame: false,
        startFrame: null,
        midFrame: null,
        endFrame: null,
        clip: null,
        seedanceMotionPrompt: "",
        motionPlan: {},
        diagnostics: {},
        sceneReady: false,
        videoReady: false,
      });
    }
    return segmentMap.get(segmentId);
  };

  for (const frame of artifacts?.scene_frames || []) {
    const segmentId = segmentIdFromAssetName(frame.name);
    const segment = ensureSegment(segmentId);
    if (String(frame.name).includes("_end")) {
      segment.endFrame = frame;
    } else if (String(frame.name).includes("_mid")) {
      segment.midFrame = frame;
    } else {
      segment.startFrame = frame;
    }
  }

  for (const clip of artifacts?.rendered_clips || []) {
    const segment = ensureSegment(segmentIdFromAssetName(clip.name));
    segment.clip = clip;
  }

  return Array.from(segmentMap.values())
    .sort((left, right) => left.segmentId.localeCompare(right.segmentId))
    .map((segment, index) => ({
      ...segment,
      title: segment.title || segmentLabel(segment.segmentId, index),
      sceneReady: Boolean(
        segment.startFrame
        && segment.endFrame
        && (!segment.requiresMidFrame || segment.midFrame),
      ),
      videoReady: Boolean(segment.clip),
    }));
}

function buildSceneGroups(segments) {
  const sceneMap = new Map();
  segments.forEach((segment, index) => {
    const sceneId = String(segment.sceneId || "").trim() || `scene-${String(index + 1).padStart(2, "0")}`;
    if (!sceneMap.has(sceneId)) {
      sceneMap.set(sceneId, {
        sceneId,
        sceneTitle: segment.sceneTitle || `场景 ${sceneMap.size + 1}`,
        sceneSummary: segment.sceneSummary || "",
        sceneAnchor: segment.sceneAnchor || "",
        sceneBible: segment.sceneBible || {},
        sceneTransitionContract: segment.sceneTransitionContract || {},
        sceneMasterFrameStatus: segment.sceneMasterFrameStatus || "",
        sceneMasterFrameError: segment.sceneMasterFrameError || "",
        coveredEventIds: segment.coveredEventIds || [],
        coveredEventSummaries: segment.coveredEventSummaries || [],
        chapterNumber: segment.chapterNumber || 0,
        sceneMasterFrame: segment.sceneMasterFrame || null,
        sceneMasterFramePrompt: segment.sceneMasterFramePrompt || "",
        sceneMasterFrameRequest: segment.sceneMasterFrameRequest || null,
        segments: [],
      });
    }
    if (!sceneMap.get(sceneId).sceneMasterFrame && segment.sceneMasterFrame) {
      sceneMap.get(sceneId).sceneMasterFrame = segment.sceneMasterFrame;
    }
    if (!sceneMap.get(sceneId).sceneMasterFramePrompt && segment.sceneMasterFramePrompt) {
      sceneMap.get(sceneId).sceneMasterFramePrompt = segment.sceneMasterFramePrompt;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameRequest && segment.sceneMasterFrameRequest) {
      sceneMap.get(sceneId).sceneMasterFrameRequest = segment.sceneMasterFrameRequest;
    }
    if (!sceneMap.get(sceneId).sceneAnchor && segment.sceneAnchor) {
      sceneMap.get(sceneId).sceneAnchor = segment.sceneAnchor;
    }
    if (!Object.keys(sceneMap.get(sceneId).sceneBible || {}).length && Object.keys(segment.sceneBible || {}).length) {
      sceneMap.get(sceneId).sceneBible = segment.sceneBible;
    }
    if (!Object.keys(sceneMap.get(sceneId).sceneTransitionContract || {}).length && Object.keys(segment.sceneTransitionContract || {}).length) {
      sceneMap.get(sceneId).sceneTransitionContract = segment.sceneTransitionContract;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameStatus && segment.sceneMasterFrameStatus) {
      sceneMap.get(sceneId).sceneMasterFrameStatus = segment.sceneMasterFrameStatus;
    }
    if (!sceneMap.get(sceneId).sceneMasterFrameError && segment.sceneMasterFrameError) {
      sceneMap.get(sceneId).sceneMasterFrameError = segment.sceneMasterFrameError;
    }
    if (!sceneMap.get(sceneId).coveredEventIds.length && segment.coveredEventIds?.length) {
      sceneMap.get(sceneId).coveredEventIds = segment.coveredEventIds;
    }
    if (!sceneMap.get(sceneId).coveredEventSummaries.length && segment.coveredEventSummaries?.length) {
      sceneMap.get(sceneId).coveredEventSummaries = segment.coveredEventSummaries;
    }
    sceneMap.get(sceneId).segments.push(segment);
  });
  return Array.from(sceneMap.values());
}

function getLatestSegmentStageTask(run, taskType, segmentId) {
  return run?.tasks?.find((task) => (
    task.task_type === taskType
    && String(task.payload?.segment_id || task.result?.segment_id || "") === String(segmentId || "")
  )) || null;
}

function getLatestSceneMasterTask(run, sceneId) {
  return run?.tasks?.find((task) => (
    task.task_type === "project.scenes"
    && Boolean(task.payload?.master_only || task.result?.master_only)
    && String(task.payload?.scene_id || task.result?.scene_id || "") === String(sceneId || "")
  )) || null;
}

function getLatestSceneRepairTask(run, sceneId) {
  return run?.tasks?.find((task) => (
    task.task_type === "project.continuity_repair"
    && String(task.payload?.scene_id || task.result?.scene_id || "") === String(sceneId || "")
    && !String(task.payload?.segment_id || task.result?.segment_id || "")
  )) || null;
}

function getLatestBatchRepairTask(run) {
  return run?.tasks?.find((task) => task.task_type === "project.continuity_repair_batch") || null;
}

function taskCreatedTimestamp(task) {
  const value = Date.parse(String(task?.created_at || ""));
  return Number.isFinite(value) ? value : 0;
}

function isBusyTaskStatus(status) {
  return status === "queued" || status === "running";
}

function isTaskStartedAfter(task, referenceTask, storySourceRevision) {
  if (!task || !referenceTask) {
    return false;
  }
  if (taskCreatedTimestamp(task) <= taskCreatedTimestamp(referenceTask)) {
    return false;
  }
  const status = getRunStageStatus(task, storySourceRevision);
  return status === "queued" || status === "running" || status === "completed";
}

function getRepairAffectedSegmentIds(task) {
  return new Set(
    (Array.isArray(task?.result?.affected_segment_ids) ? task.result.affected_segment_ids : [])
      .map((segmentId) => String(segmentId || "").trim())
      .filter(Boolean),
  );
}

function hasLaterMatchingTask(run, repairTask, storySourceRevision, matcher) {
  return (run?.tasks || []).some(
    (task) => matcher(task) && isTaskStartedAfter(task, repairTask, storySourceRevision),
  );
}

function hasSegmentStageCoverage(run, repairTask, storySourceRevision, taskType, segmentIds) {
  const targets = Array.from(segmentIds).filter(Boolean);
  if (!targets.length) {
    return false;
  }
  return targets.every((segmentId) => hasLaterMatchingTask(
    run,
    repairTask,
    storySourceRevision,
    (task) => task.task_type === taskType
      && String(task.payload?.segment_id || task.result?.segment_id || "") === segmentId,
  ));
}

function resolveRepairRemainingActions(run, repairTask, storySourceRevision) {
  if (!repairTask || repairTask.status !== "completed" || !repairTask.result?.media_regeneration_required) {
    return [];
  }
  const pendingActions = Array.isArray(repairTask.result?.pending_media_actions)
    ? repairTask.result.pending_media_actions
      .map((action) => String(action || "").trim())
      .filter(Boolean)
    : [];
  if (!pendingActions.length) {
    return [];
  }

  const sceneId = String(repairTask.payload?.scene_id || repairTask.result?.scene_id || "").trim();
  const segmentId = String(repairTask.payload?.segment_id || repairTask.result?.segment_id || "").trim();
  const affectedSegmentIds = getRepairAffectedSegmentIds(repairTask);
  if (!affectedSegmentIds.size && segmentId) {
    affectedSegmentIds.add(segmentId);
  }

  return pendingActions.filter((action) => {
    if (action === "regenerate_scene_master_frame") {
      return !hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          task.task_type === "project.scenes"
          && Boolean(task.payload?.master_only || task.result?.master_only)
          && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
        ),
      );
    }

    if (action === "regenerate_scene_images") {
      const coveredByBroadTask = hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          (
            task.task_type === "project.scenes"
            && !task.payload?.master_only
            && !task.payload?.segment_id
            && !task.payload?.scene_id
          )
          || (
            task.task_type === "project.scenes"
            && !task.payload?.master_only
            && sceneId
            && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
          )
        ),
      );
      if (coveredByBroadTask) {
        return false;
      }
      return !hasSegmentStageCoverage(run, repairTask, storySourceRevision, "project.scenes", affectedSegmentIds);
    }

    if (action === "regenerate_video") {
      const coveredByBroadTask = hasLaterMatchingTask(
        run,
        repairTask,
        storySourceRevision,
        (task) => (
          (
            task.task_type === "project.videos"
            && !task.payload?.merge_only
            && !task.payload?.segment_id
            && !task.payload?.scene_id
          )
          || (
            task.task_type === "project.videos"
            && !task.payload?.merge_only
            && sceneId
            && String(task.payload?.scene_id || task.result?.scene_id || "") === sceneId
          )
        ),
      );
      if (coveredByBroadTask) {
        return false;
      }
      return !hasSegmentStageCoverage(run, repairTask, storySourceRevision, "project.videos", affectedSegmentIds);
    }

    return true;
  });
}

function buildSceneMasterButtonLabel(sceneGroup, sceneMasterTaskStatus) {
  if (isBusyTaskStatus(sceneMasterTaskStatus)) {
    return "场景母图生成中";
  }
  if (sceneGroup.sceneMasterFrame) {
    return "重生成场景母图";
  }
  if (sceneMasterTaskStatus === "failed") {
    return "重试场景母图";
  }
  return "生成场景母图";
}

function buildSceneRepairButtonLabel(sceneRepairTaskStatus, hasPendingActions) {
  if (isBusyTaskStatus(sceneRepairTaskStatus)) {
    return "智能修复中";
  }
  if (sceneRepairTaskStatus === "failed") {
    return "重试智能修复";
  }
  if (hasPendingActions) {
    return "修复方案已更新";
  }
  if (sceneRepairTaskStatus === "completed") {
    return "重新智能修复";
  }
  return "智能修复场景";
}

function buildBatchRepairButtonLabel(batchRepairTaskStatus, batchRepairTask) {
  if (isBusyTaskStatus(batchRepairTaskStatus)) {
    return "批量修复中";
  }
  if (batchRepairTaskStatus === "failed") {
    return "重试批量修复";
  }
  if (batchRepairTask?.result?.has_more_batches) {
    return "继续修下一批";
  }
  if (batchRepairTaskStatus === "completed") {
    return "重新批量修复";
  }
  return "一键修复风险合同";
}

function buildSegmentSceneButtonLabel(segment, sceneTaskStatus) {
  if (isBusyTaskStatus(sceneTaskStatus)) {
    return "场景图生成中";
  }
  if (segment.sceneReady) {
    return "重生成场景图";
  }
  if (sceneTaskStatus === "failed") {
    return "重试场景图";
  }
  return "生成场景图";
}

function buildBlockedSceneButtonLabel(segment, sceneTaskStatus, characterStatus) {
  if (characterStatus === "failed") {
    return "角色图失败";
  }
  if (characterStatus === "stale") {
    return "先重生成角色图";
  }
  if (characterStatus === "queued" || characterStatus === "running") {
    return "角色图生成中";
  }
  if (characterStatus !== "completed" && !segment.sceneReady) {
    return "先生成角色图";
  }
  return buildSegmentSceneButtonLabel(segment, sceneTaskStatus);
}

function buildSegmentVideoButtonLabel(segment, videoTaskStatus) {
  if (isBusyTaskStatus(videoTaskStatus)) {
    return "视频生成中";
  }
  if (segment.videoReady) {
    return "重生成视频";
  }
  if (videoTaskStatus === "failed") {
    return "重试视频";
  }
  return "生成视频";
}

function buildSegmentRepairButtonLabel(segment, repairTaskStatus, hasPendingActions) {
  if (isBusyTaskStatus(repairTaskStatus)) {
    return "智能修复中";
  }
  if (hasPendingActions) {
    return "修复合同已更新";
  }
  if (segment.videoReady || segment.sceneReady) {
    return "重新智能修复";
  }
  if (repairTaskStatus === "failed") {
    return "重试智能修复";
  }
  return "智能修复该段";
}

function buildMergeButtonLabel(artifacts, mergeTaskStatus) {
  if (mergeTaskStatus === "queued" || mergeTaskStatus === "running") {
    return "合并中";
  }
  if (artifacts?.full_story) {
    return "重新合并总片";
  }
  if (mergeTaskStatus === "failed") {
    return "重试合并";
  }
  return "合并已生成片段";
}

function renderSegmentTaskError(task, label) {
  const error = buildTaskErrorMessage(task);
  if (!error) {
    return "";
  }
  return `<p class="timeline-task-error">${escapeHtml(`${label}：${error}`)}</p>`;
}

function renderRepairPlanNotice(task, remainingActions = null) {
  if (!task || task.status !== "completed" || !task.result?.media_regeneration_required) {
    return "";
  }
  const pendingActions = Array.isArray(remainingActions)
    ? remainingActions
    : (
      Array.isArray(task.result?.pending_media_actions)
        ? task.result.pending_media_actions
        : []
    );
  const actionLabels = pendingActions
      .map((action) => REPAIR_PENDING_ACTION_LABELS[action] || action)
      .filter(Boolean);
  const repairSummary = String(task.result?.repair_summary || "").trim();
  const message = actionLabels.length
    ? [
      repairSummary || "智能修复已完成，只更新了当前修复合同。",
      `媒体不会自动重跑，请按需要继续：${actionLabels.join("、")}。`,
    ].join(" ")
    : [
      repairSummary || "智能修复已完成，只更新了当前修复合同。",
      "后续媒体任务已手动提交或完成，可以继续审阅最新结果。",
    ].join(" ");
  return `<p class="asset-note">${escapeHtml(message)}</p>`;
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

function renderBatchRepairNotice(task) {
  if (!task || task.status !== "completed") {
    return "";
  }
  const summary = String(task.result?.repair_summary || "").trim();
  if (!summary) {
    return "";
  }
  return `<p class="asset-note">${escapeHtml(summary)}</p>`;
}

function buildContinuityLookup(groups, keyField) {
  return new Map(
    (groups || [])
      .filter((group) => group && group[keyField])
      .map((group) => [String(group[keyField]), group]),
  );
}

function hasRecommendedContinuityAction(group, action) {
  return Boolean(group?.recommended_actions?.includes(action));
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

function renderContinuityRiskChips(group) {
  if (!group || !group.issue_count) {
    return chip("连续性稳定");
  }
  const parts = [chip(`风险 ${group.issue_count}`)];
  if (group.high_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-high">高 ${group.high_risk_count}</span>`);
  }
  if (group.medium_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-medium">中 ${group.medium_risk_count}</span>`);
  }
  if (group.low_risk_count) {
    parts.push(`<span class="continuity-chip continuity-chip-low">低 ${group.low_risk_count}</span>`);
  }
  return parts.join("");
}

function renderContinuityIssueList(group, emptyMessage = "") {
  if (!group?.issues?.length) {
    return emptyMessage ? `<p class="continuity-empty">${escapeHtml(emptyMessage)}</p>` : "";
  }
  return `
    <div class="continuity-issue-list">
      ${group.issues.map((issue) => `
        <article class="continuity-issue continuity-issue-${escapeAttr(issue.severity || "low")}">
          <div class="continuity-issue-head">
            <span class="continuity-pill continuity-pill-${escapeAttr(issue.severity || "low")}">
              ${escapeHtml(CONTINUITY_SEVERITY_LABEL[issue.severity] || "风险")}
            </span>
            ${issue.recommended_action_label ? `<span class="continuity-action-label">${escapeHtml(issue.recommended_action_label)}</span>` : ""}
          </div>
          <p>${escapeHtml(issue.message || "")}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function renderContinuityOverview(summary) {
  if (!summary) {
    return `<p class="timeline-continuity-note">当前还没有连续性校验结果。</p>`;
  }
  const generatedAt = summary.generated_at ? formatShortTime(summary.generated_at) : "未记录";
  const modeLabel = continuityReviewModeLabel(summary.review_mode_requested);
  const v2StatusLabel = CONTINUITY_V2_STATUS_LABEL[summary.v2_review_status] || summary.v2_review_status || "未执行";
  const topIssues = summary.top_issues?.length
    ? `
      <div class="continuity-hero-list">
        ${summary.top_issues.map((issue) => `
          <article class="continuity-inline-item">
            <span class="continuity-pill continuity-pill-${escapeAttr(issue.severity || "low")}">
              ${escapeHtml(CONTINUITY_SEVERITY_LABEL[issue.severity] || "风险")}
            </span>
            <p>${escapeHtml(issue.message || "")}</p>
          </article>
        `).join("")}
      </div>
    `
    : `<p class="timeline-continuity-note">当前没有检测到需要人工处理的连续性问题。</p>`;
  return `
    <div class="timeline-continuity-summary">
      <p class="timeline-continuity-note">
        ${escapeHtml(`最近校验：${generatedAt} · 状态：${CONTINUITY_STATUS_LABEL[summary.status] || summary.status || "未校验"}`)}
      </p>
      <div class="detail-chip-row">
        ${chip(`V2 模式 ${modeLabel}`)}
        ${chip(`V2 状态 ${v2StatusLabel}`)}
        ${summary.v2_issue_count ? `<span class="continuity-chip continuity-chip-medium">V2 问题 ${summary.v2_issue_count}</span>` : ""}
      </div>
      ${summary.v2_note ? `<p class="timeline-continuity-note">${escapeHtml(summary.v2_note)}</p>` : ""}
      ${topIssues}
    </div>
  `;
}

function buildTimelineGalleryItems(artifacts) {
  const plannedItems = (artifacts?.planned_segments || []).flatMap((segment) => ([
    segment.scene_master_frame ? { ...segment.scene_master_frame, kind: "image" } : null,
    segment.start_frame ? { ...segment.start_frame, kind: "image" } : null,
    segment.requires_mid_frame && segment.mid_frame ? { ...segment.mid_frame, kind: "image" } : null,
    segment.end_frame ? { ...segment.end_frame, kind: "image" } : null,
    segment.rendered_clip ? { ...segment.rendered_clip, kind: "video" } : null,
  ])).filter(Boolean);
  if (plannedItems.length) {
    return dedupeTimelineGalleryItems([
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...plannedItems,
    ]);
  }
  return dedupeTimelineGalleryItems([
    ...artifacts.scene_frames.map((item) => ({ ...item, kind: "image" })),
    ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
    ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
  ]);
}

function dedupeTimelineGalleryItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    const key = String(item?.path || item?.url || item?.name || "");
    if (!key || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function renderTimelinePreview(item, label, galleryId) {
  if (!item) {
    return `
      <div class="timeline-empty-preview">
        <span>${escapeHtml(label)}</span>
        <strong>未生成</strong>
      </div>
    `;
  }
  const index = findGalleryIndex(galleryId, item);
  const preview = item.kind === "video"
    ? `<video preload="metadata" src="${item.url}"></video>`
    : `<img src="${item.url}" alt="${escapeAttr(item.name)}" loading="lazy" />`;
  return `
    <button
      type="button"
      class="timeline-preview"
      data-preview-group="${escapeAttr(galleryId)}"
      data-preview-index="${index}"
    >
      <span>${escapeHtml(label)}</span>
      ${preview}
    </button>
  `;
}

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

function renderDocsTab(task, artifacts, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("文档暂不可用", buildArtifactPendingMessage(task, "docs", run));
  }

  if (!artifacts.documents.length) {
    return singleAssetMessage("文档暂不可用", "当前运行没有额外落盘的文档文件。");
  }

  const documentGroups = groupDocuments(artifacts.documents);

  return `
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "运行文件面板",
        "这里只保留当前链路真正会继续消费的源文件，以及每一步的执行报告。",
        chip(`核心文件 ${artifacts.documents.length}`),
      )}
      ${documentGroups.map((group) => renderDocumentBlock(group.title, group.items)).join("")}
    </section>
  `;
}

function renderImagesTab(task, artifacts, context, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("图片暂不可用", buildArtifactPendingMessage(task, "images", run));
  }
  if (
    run
    && run.latestTask.task_type === "project.story"
    && !artifacts.character_images.length
    && !artifacts.scene_frames.length
  ) {
    return singleAssetMessage("图片暂不可用", buildArtifactPendingMessage(task, "images", run));
  }

  const galleryId = `${context}:images:${task.task_id}`;
  registerGallery(
    galleryId,
    [
      ...artifacts.character_images.map((item) => ({ ...item, kind: "image" })),
      ...artifacts.scene_frames.map((item) => ({ ...item, kind: "image" })),
    ],
  );

  return `
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "图像资产",
        "先看角色定妆，再看场景关键帧。当前页面只展示真实参与后续链路的图像资产。",
        [
          chip(`角色图 ${artifacts.character_images.length}`),
          chip(`场景帧 ${artifacts.scene_frames.length}`),
        ].join(""),
      )}
      ${
        artifacts.character_images.length
          ? renderMediaBlock(
            "角色定妆图",
            artifacts.character_images,
            galleryId,
            "角色基准参考图。后续场景关键帧和视频片段都会围绕这组角色外观继续生成。",
          )
          : singleAssetMessage("角色定妆图", buildArtifactPendingMessage(task, "characters", run))
      }
      ${
        artifacts.scene_frames.length
          ? renderMediaBlock(
            "场景关键帧",
            artifacts.scene_frames,
            galleryId,
            "每个片段的首帧、必要时的中段锚点帧，以及尾帧。它们共同决定镜头连续性、角色位置和空间氛围。",
          )
          : singleAssetMessage("场景关键帧", buildArtifactPendingMessage(task, "scenes", run))
      }
    </section>
  `;
}

function renderVideosTab(task, artifacts, context, run = null) {
  if (!artifacts?.available) {
    return singleAssetMessage("视频暂不可用", buildArtifactPendingMessage(task, "videos", run));
  }
  if (
    run
    && run.latestTask.task_type !== "project.videos"
    && !artifacts.rendered_clips.length
    && !artifacts.full_story
  ) {
    return singleAssetMessage("视频暂不可用", buildArtifactPendingMessage(task, "videos", run));
  }

  const galleryId = `${context}:videos:${task.task_id}`;
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const mergeTaskStatus = run ? getRunStageStatus(run.latestMergeTask, storySourceRevision) : "idle";
  const canMergeVideos = artifacts.rendered_clips.length >= 2 && !["queued", "running"].includes(mergeTaskStatus);
  registerGallery(
    galleryId,
    [
      ...(artifacts.full_story ? [{ ...artifacts.full_story, kind: "video" }] : []),
      ...artifacts.rendered_clips.map((item) => ({ ...item, kind: "video" })),
    ],
  );

  return `
    <section class="story-editor-shell">
      ${renderAssetSectionIntro(
        "视频资产",
        "视频片段按 segment 单独生成。总片不再自动合并，需要你手动点击合并按钮决定是否输出完整成片。",
        [
          chip(`总片 ${artifacts.full_story ? "已生成" : "未生成"}`),
          chip(`片段 ${artifacts.rendered_clips.length}`),
        ].join(""),
      )}
      <article class="asset-block video-merge-card">
        <div class="story-editor-head">
          <div>
            <h4>总片合并</h4>
            <p class="asset-note">会按 seedance_manifest.json 顺序，把当前已经存在本地 mp4 的片段合并成 full_story.mp4。</p>
          </div>
          <div class="story-editor-actions">
            <button
              type="button"
              class="secondary"
              data-merge-videos="${escapeAttr(rootTask.task_id)}"
              data-project-id="${escapeAttr(rootTask.project_id)}"
              ${canMergeVideos ? "" : "disabled"}
            >
              ${escapeHtml(buildMergeButtonLabel(artifacts, mergeTaskStatus))}
            </button>
          </div>
        </div>
      </article>
      ${renderFullStoryBlock(artifacts.full_story, context, galleryId)}
      ${renderMediaBlock(
        "视频片段",
        artifacts.rendered_clips,
        galleryId,
        "按 segment 输出的独立片段，可用于逐段审片、比较效果和局部重跑。",
      )}
    </section>
  `;
}

export function renderRunStageActions(run) {
  const rootTask = run.rootTask;
  if (!rootTask) {
    return "";
  }

  const storySourceRevision = getStorySourceRevision(rootTask);
  const sceneStructureStatus = getRunStageStatus(run.latestSceneStructureTask, storySourceRevision);
  const segmentContractsStatus = getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision);
  const characterStatus = getRunStageStatus(run.latestCharacterTask, storySourceRevision);
  const sceneStatus = getRunStageStatus(run.latestSceneTask, storySourceRevision);
  const videoStatus = getRunStageStatus(run.latestVideoTask, storySourceRevision);
  const mergeStatus = getRunStageStatus(run.latestMergeTask, storySourceRevision);
  const storyLocator = resolveStorySourceLocator(rootTask, run);
  const storyMeta = storyLocator
    ? getStorySourceMeta(storyLocator.projectId, storyLocator.sourceTaskId)
    : { dirty: false, loading: false, saving: false };
  const sceneStructureReady = sceneStructureStatus === "completed";
  const segmentContractsTask = run.latestSegmentContractsTask;
  const {
    progressLabel: segmentContractsProgressLabel,
    failureLabel: segmentContractsFailureLabel,
    resumeFromProgress: resumeSegmentContractsFromProgress,
    buttonLabel: resolvedSegmentContractsButtonLabel,
  } = resolveSegmentContractsUiState(segmentContractsTask, segmentContractsStatus);
  const segmentContractsReady = segmentContractsStatus === "completed";
  const canGenerateSceneStructure =
    rootTask.status === "completed"
    && !storyMeta.dirty
    && !storyMeta.loading
    && !storyMeta.saving
    && !["queued", "running", "completed"].includes(sceneStructureStatus);
  const canGenerateSegmentContracts =
    sceneStructureReady
    && !storyMeta.dirty
    && !storyMeta.loading
    && !storyMeta.saving
    && !["queued", "running", "completed"].includes(segmentContractsStatus);
  const canGenerateCharacters =
    segmentContractsReady && !["queued", "running", "completed"].includes(characterStatus);
  const plannedSegments = run.latestArtifacts?.planned_segments || [];
  const readySceneCount = plannedSegments.filter((segment) => segment.scene_ready).length;
  const readyVideoCount = plannedSegments.filter((segment) => segment.video_ready).length;
  const canMergeVideos = readyVideoCount >= 2 && !["queued", "running"].includes(mergeStatus);
  const continuityReviewMode = resolveRunContinuityReviewMode(run);

  const sceneStructureButtonLabel =
    sceneStructureStatus === "failed" || sceneStructureStatus === "stale"
      ? "重新生成场景结构"
      : sceneStructureStatus === "completed"
        ? "场景结构已完成"
        : sceneStructureStatus === "running"
          ? "场景结构生成中"
          : "生成场景结构";
  const segmentContractsButtonLabel = resolvedSegmentContractsButtonLabel;
  const characterButtonLabel =
    characterStatus === "failed" || characterStatus === "stale" ? "重新生成角色图" : characterStatus === "completed" ? "角色图已完成" : characterStatus === "running" ? "角色图生成中" : "生成角色图";
  const segmentContractsStepNote =
    segmentContractsFailureLabel
      ? segmentContractsProgressLabel
        ? `${segmentContractsFailureLabel} · 已完成 ${segmentContractsProgressLabel}`
        : segmentContractsFailureLabel
      : segmentContractsStatus === "running" && segmentContractsProgressLabel
        ? `当前进度 ${segmentContractsProgressLabel}`
        : segmentContractsStatus === "completed" && segmentContractsProgressLabel
          ? `章节完成 ${segmentContractsProgressLabel}`
          : "scene 拆 segment";
  const steps = [
    ["01", "小说正文", rootTask.status, "先确认故事文本"],
    ["02", "场景结构", sceneStructureStatus, "章节拆 scene"],
    ["03", "分段合同", segmentContractsStatus, segmentContractsStepNote],
    ["04", "角色图", characterStatus, "生成角色定妆"],
    ["05", "场景图", sceneStatus, plannedSegments.length ? `${readySceneCount}/${plannedSegments.length} 段已就绪` : "在时间线中逐段生成"],
    ["06", "视频", videoStatus, plannedSegments.length ? `${readyVideoCount}/${plannedSegments.length} 段已出片` : "在时间线中逐段生成"],
  ];

  return `
    <div class="pipeline-rail">
      ${steps
        .map(
          ([number, title, status, note]) => `
            <article class="pipeline-step ${escapeAttr(status)}">
              <span>${escapeHtml(number)}</span>
              <strong>${escapeHtml(title)}</strong>
              <small>${escapeHtml(stageStatusLabel(status))} · ${escapeHtml(note)}</small>
            </article>
          `,
        )
        .join("")}
    </div>
    <div class="stage-action-card">
      <div>
        <p class="section-kicker">Next Step</p>
        <strong>当前版本制作入口</strong>
        <p>这里只保留全局阶段入口。场景图和视频请在下方时间线里按片段逐段生成，总片合并也改成手动触发。</p>
      </div>
      <div class="stage-action-panel">
        <label class="continuity-mode-field">
          <span>V2 连续性软审校</span>
          <select
            data-run-continuity-review-mode="${escapeAttr(rootTask.task_id)}"
          >
            ${renderContinuityModeOptions(continuityReviewMode)}
          </select>
          <p class="field-help">V1 规则审校始终开启。自动模式会在复杂场景、跨段承接或 V1 中高风险时触发 LLM 软审校。</p>
        </label>
        <div class="action-row">
          <button
            type="button"
            class="secondary"
            data-story-source-project="${escapeAttr(rootTask.project_id)}"
            data-generate-scene-structure="${escapeAttr(rootTask.task_id)}"
            ${canGenerateSceneStructure ? "" : "disabled"}
          >
            ${escapeHtml(sceneStructureButtonLabel)}
          </button>
          <button
            type="button"
            class="secondary"
            data-story-source-project="${escapeAttr(rootTask.project_id)}"
            data-generate-segment-contracts="${escapeAttr(rootTask.task_id)}"
            data-resume-from-progress="${resumeSegmentContractsFromProgress ? "true" : "false"}"
            ${canGenerateSegmentContracts ? "" : "disabled"}
          >
            ${escapeHtml(segmentContractsButtonLabel)}
          </button>
          <button
            type="button"
            class="secondary"
            data-merge-videos="${escapeAttr(rootTask.task_id)}"
            data-project-id="${escapeAttr(rootTask.project_id)}"
            ${canMergeVideos ? "" : "disabled"}
          >
            ${escapeHtml(buildMergeButtonLabel(run.latestArtifacts, mergeStatus))}
          </button>
          <button
            type="button"
            class="secondary"
            data-generate-characters="${escapeAttr(rootTask.task_id)}"
            ${canGenerateCharacters ? "" : "disabled"}
          >
            ${escapeHtml(characterButtonLabel)}
          </button>
        </div>
      </div>
    </div>
    ${renderStageFailureList(run, storySourceRevision)}
  `;
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
