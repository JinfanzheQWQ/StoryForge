import { state } from "../state.js";
import { registerGallery } from "../gallery.js";
import {
  chip,
  escapeAttr,
  escapeHtml,
  getRunStageStatus,
  getStorySourceRevision,
  singleAssetMessage,
} from "../utils.js";
import {
  renderPromptEditorPanel,
  renderRequestInspectorPanel,
  renderSegmentAssetSelector,
  renderSegmentDiagnosticsSummary,
  resolveSelectedSegmentAssetOption,
} from "./prompt_tools.js";

function resolveSegmentReviewModel({
  segment,
  run,
  rootTask,
  storySourceRevision,
  characterStatus,
  batchRepairTaskStatus,
  runHasBusyRepairTask,
  continuitySegmentLookup,
  helpers,
}) {
  const segmentContinuity = continuitySegmentLookup.get(segment.segmentId) || null;
  const sceneTask = helpers.getLatestSegmentStageTask(run, "project.scenes", segment.segmentId);
  const videoTask = helpers.getLatestSegmentStageTask(run, "project.videos", segment.segmentId);
  const repairTask = helpers.getLatestSegmentStageTask(run, "project.continuity_repair", segment.segmentId);
  const sceneTaskStatus = run ? getRunStageStatus(sceneTask, storySourceRevision) : "idle";
  const videoTaskStatus = run ? getRunStageStatus(videoTask, storySourceRevision) : "idle";
  const repairTaskStatus = run ? getRunStageStatus(repairTask, storySourceRevision) : "idle";
  const segmentRepairRemainingActions = helpers.resolveRepairRemainingActions(run, repairTask, storySourceRevision);
  const sceneScopeLocked = helpers.isBusyTaskStatus(batchRepairTaskStatus) || runHasBusyRepairTask;
  const segmentRepairLocked = helpers.isBusyTaskStatus(repairTaskStatus);
  const canGenerateScene =
    characterStatus === "completed"
    && !sceneScopeLocked
    && !segmentRepairLocked
    && !helpers.isBusyTaskStatus(sceneTaskStatus)
    && !helpers.isBusyTaskStatus(videoTaskStatus);
  const canGenerateVideo =
    segment.sceneReady
    && !sceneScopeLocked
    && !segmentRepairLocked
    && !helpers.isBusyTaskStatus(sceneTaskStatus)
    && !helpers.isBusyTaskStatus(videoTaskStatus);
  const canRunRepair =
    characterStatus === "completed"
    && Boolean(segmentContinuity?.issue_count)
    && !sceneScopeLocked
    && !helpers.isBusyTaskStatus(repairTaskStatus)
    && !helpers.isBusyTaskStatus(sceneTaskStatus)
    && !helpers.isBusyTaskStatus(videoTaskStatus);
  const sceneRecommended = helpers.hasRecommendedContinuityAction(segmentContinuity, "regenerate_scene_images")
    || segmentRepairRemainingActions.includes("regenerate_scene_images");
  const videoRecommended = helpers.hasRecommendedContinuityAction(segmentContinuity, "regenerate_video")
    || segmentRepairRemainingActions.includes("regenerate_video");
  return {
    rootTask,
    segmentContinuity,
    sceneTask,
    videoTask,
    repairTask,
    sceneTaskStatus,
    videoTaskStatus,
    repairTaskStatus,
    segmentRepairRemainingActions,
    sceneScopeLocked,
    segmentRepairLocked,
    canGenerateScene,
    canGenerateVideo,
    canRunRepair,
    sceneRecommended,
    videoRecommended,
  };
}

export function renderSegmentReviewDetail({ segment, index, model, galleryId, characterStatus, helpers }) {
  if (!segment) {
    return singleAssetMessage("选择片段", "请从左侧选择一个 segment 进行审片。");
  }
  const selectedOption = resolveSelectedSegmentAssetOption(segment);
  const isVideoSelected = selectedOption.kind === "video";
  const canRerunSelectedAsset = isVideoSelected ? model.canGenerateVideo : model.canGenerateScene;
  const selectedRerunLabel = isVideoSelected ? "重做当前视频" : `重做${selectedOption.label}`;
  return `
    <article class="segment-review-detail-card">
      <div class="timeline-card-head">
        <span class="timeline-index">${String(index + 1).padStart(2, "0")}</span>
        <div>
          <h4>${escapeHtml(segment.title || helpers.segmentLabel(segment.segmentId, index))}</h4>
          <p class="asset-note">
            ${escapeHtml(`${segment.chapterNumber ? `第 ${segment.chapterNumber} 章 · ` : ""}${segment.sceneId ? `${segment.sceneId} · ` : ""}${segment.segmentId}${segment.durationSeconds ? ` · ${segment.durationSeconds}s` : ""}`)}
          </p>
        </div>
      </div>
      ${segment.summary ? `<p class="timeline-summary">${escapeHtml(segment.summary)}</p>` : ""}
      ${renderSegmentDiagnosticsSummary(segment)}
      <div class="timeline-preview-grid segment-review-preview-grid">
        ${helpers.renderTimelinePreview(segment.startFrame, "首帧", galleryId)}
        ${segment.requiresMidFrame ? helpers.renderTimelinePreview(segment.midFrame, "中段", galleryId) : ""}
        ${helpers.renderTimelinePreview(segment.endFrame, "尾帧", galleryId)}
        ${helpers.renderTimelinePreview(segment.clip, "视频", galleryId)}
      </div>
      <div class="timeline-card-footer">
        ${renderSegmentAssetSelector(segment, selectedOption)}
        <div class="detail-chip-row">
          ${chip(`场景 ${segment.sceneReady ? "已就绪" : "待生成"}`)}
          ${chip(`视频 ${segment.videoReady ? "已就绪" : "待生成"}`)}
          ${segment.requiresMidFrame ? chip("含中段锚点") : chip("双帧片段")}
          ${model.segmentRepairRemainingActions.length ? chip("合同已更新") : ""}
          ${helpers.renderContinuityRiskChips(model.segmentContinuity)}
        </div>
        ${helpers.renderContinuityIssueList(model.segmentContinuity)}
        <div class="timeline-actions">
          <button
            type="button"
            class="secondary small"
            data-auto-repair-segment="${escapeAttr(segment.segmentId)}"
            data-project-id="${escapeAttr(model.rootTask.project_id)}"
            data-source-task="${escapeAttr(model.rootTask.task_id)}"
            ${model.canRunRepair ? "" : "disabled"}
          >
            ${escapeHtml(helpers.buildSegmentRepairButtonLabel(segment, model.repairTaskStatus, model.segmentRepairRemainingActions.length > 0))}
          </button>
          <button
            type="button"
            class="secondary small${model.sceneRecommended ? " recommended-action" : ""}"
            data-generate-scene-segment="${escapeAttr(segment.segmentId)}"
            data-project-id="${escapeAttr(model.rootTask.project_id)}"
            data-source-task="${escapeAttr(model.rootTask.task_id)}"
            ${model.canGenerateScene ? "" : "disabled"}
          >
            ${escapeHtml(model.canGenerateScene ? helpers.buildSegmentSceneButtonLabel(segment, model.sceneTaskStatus) : helpers.buildBlockedSceneButtonLabel(segment, model.sceneTaskStatus, characterStatus))}
          </button>
          <button
            type="button"
            class="secondary small${model.videoRecommended ? " recommended-action" : ""}"
            data-generate-video-segment="${escapeAttr(segment.segmentId)}"
            data-project-id="${escapeAttr(model.rootTask.project_id)}"
            data-source-task="${escapeAttr(model.rootTask.task_id)}"
            ${model.canGenerateVideo ? "" : "disabled"}
          >
            ${escapeHtml(helpers.buildSegmentVideoButtonLabel(segment, model.videoTaskStatus))}
          </button>
          <button
            type="button"
            class="primary-button small"
            ${isVideoSelected ? `data-generate-video-segment="${escapeAttr(segment.segmentId)}"` : `data-generate-scene-segment="${escapeAttr(segment.segmentId)}" data-frame-kind="${escapeAttr(selectedOption.frameKind)}"`}
            data-project-id="${escapeAttr(model.rootTask.project_id)}"
            data-source-task="${escapeAttr(model.rootTask.task_id)}"
            ${canRerunSelectedAsset ? "" : "disabled"}
          >${escapeHtml(selectedRerunLabel)}</button>
        </div>
        ${helpers.renderSegmentTaskError(model.repairTask, "智能修复失败")}
        ${helpers.renderRepairPlanNotice(model.repairTask, model.segmentRepairRemainingActions)}
        ${model.canGenerateScene ? "" : helpers.renderSegmentSceneBlockedNotice({
          segment,
          characterStatus,
          sceneScopeLocked: model.sceneScopeLocked,
          segmentRepairLocked: model.segmentRepairLocked,
          sceneTaskStatus: model.sceneTaskStatus,
          videoTaskStatus: model.videoTaskStatus,
        })}
        ${helpers.renderSegmentTaskError(model.sceneTask, "场景图失败")}
        ${helpers.renderSegmentTaskError(model.videoTask, "视频失败")}
      </div>
      <div class="segment-review-inspector-grid">
        ${renderPromptEditorPanel(segment, model.rootTask, selectedOption)}
        ${renderRequestInspectorPanel(segment, selectedOption)}
      </div>
    </article>
  `;
}

function segmentMatchesReviewFilter(segment, segmentContinuity, filter) {
  if (filter === "risk") {
    return Number(segmentContinuity?.high_risk_count || 0) > 0;
  }
  if (filter === "scene_missing") {
    return !segment.sceneReady;
  }
  if (filter === "video_missing") {
    return !segment.videoReady;
  }
  if (filter === "video_ready") {
    return segment.videoReady;
  }
  return true;
}

export function renderSegmentReviewTab({ task, artifacts, context, run = null, helpers }) {
  if (!artifacts?.available) {
    return singleAssetMessage("分段审片台", helpers.buildArtifactPendingMessage(task, "images", run));
  }
  const timelineItems = helpers.buildTimelineGalleryItems(artifacts);
  const galleryId = `${context}:segment-review:${task.task_id}`;
  registerGallery(galleryId, timelineItems);
  const segments = helpers.buildTimelineSegments(artifacts);
  if (!segments.length) {
    return singleAssetMessage("分段审片台", helpers.buildArtifactPendingMessage(task, "images", run));
  }
  const continuitySegmentLookup = helpers.buildContinuityLookup(artifacts?.continuity_segment_groups, "segment_id");
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const characterStatus = run ? getRunStageStatus(run.latestCharacterTask, storySourceRevision) : "idle";
  const batchRepairTask = helpers.getLatestBatchRepairTask(run);
  const batchRepairTaskStatus = run ? getRunStageStatus(batchRepairTask, storySourceRevision) : "idle";
  const runHasBusyRepairTask = (run?.tasks || []).some(
    (item) => (
      (item.task_type === "project.continuity_repair" || item.task_type === "project.continuity_repair_batch")
      && helpers.isBusyTaskStatus(getRunStageStatus(item, storySourceRevision))
    ),
  );
  const activeFilter = state.segmentReviewFilter || "all";
  const filteredSegments = segments.filter((segment) => segmentMatchesReviewFilter(
    segment,
    continuitySegmentLookup.get(segment.segmentId) || null,
    activeFilter,
  ));
  const selectedSegment = filteredSegments.find((segment) => segment.segmentId === state.selectedSegmentId)
    || filteredSegments[0]
    || null;
  const selectedIndex = selectedSegment
    ? segments.findIndex((segment) => segment.segmentId === selectedSegment.segmentId)
    : -1;
  const selectedModel = selectedSegment
    ? resolveSegmentReviewModel({
      segment: selectedSegment,
      run,
      rootTask,
      storySourceRevision,
      characterStatus,
      batchRepairTaskStatus,
      runHasBusyRepairTask,
      continuitySegmentLookup,
      helpers,
    })
    : null;
  const filters = [
    ["all", "全部", segments.length],
    ["risk", "高风险", segments.filter((segment) => Number((continuitySegmentLookup.get(segment.segmentId) || {}).high_risk_count || 0) > 0).length],
    ["scene_missing", "未生成场景图", segments.filter((segment) => !segment.sceneReady).length],
    ["video_missing", "未生成视频", segments.filter((segment) => !segment.videoReady).length],
    ["video_ready", "已生成视频", segments.filter((segment) => segment.videoReady).length],
  ];

  return `
    <section class="segment-review-shell">
      <article class="asset-block segment-review-hero">
        <div>
          <p class="section-kicker">Segment Review</p>
          <h4>分段审片台</h4>
          <p class="asset-note">左侧选择片段，右侧只审当前 segment。这里集中处理关键帧、视频、prompt、实际请求和风险修复。</p>
        </div>
        <div class="segment-review-filters">
          ${filters.map(([id, label, count]) => `
            <button
              type="button"
              class="detail-tab ${activeFilter === id ? "active" : ""}"
              data-segment-review-filter="${escapeAttr(id)}"
            >${escapeHtml(label)} ${escapeHtml(String(count))}</button>
          `).join("")}
        </div>
      </article>
      <div class="segment-review-layout">
        <aside class="segment-review-sidebar">
          ${filteredSegments.length ? filteredSegments.map((segment) => {
            const issue = continuitySegmentLookup.get(segment.segmentId) || null;
            const isActive = selectedSegment?.segmentId === segment.segmentId;
            return `
              <button
                type="button"
                class="segment-review-list-item ${isActive ? "active" : ""}"
                data-select-review-segment="${escapeAttr(segment.segmentId)}"
              >
                <strong>${escapeHtml(segment.segmentId)}</strong>
                <span>${escapeHtml(segment.title || segment.segmentId)}</span>
                <small>${escapeHtml(segment.sceneId || "未绑定 scene")} · ${escapeHtml(segment.durationSeconds ? `${segment.durationSeconds}s` : "未知时长")}</small>
                <div class="detail-chip-row">
                  ${chip(`图 ${segment.sceneReady ? "OK" : "缺"}`)}
                  ${chip(`视频 ${segment.videoReady ? "OK" : "缺"}`)}
                  ${Number(issue?.high_risk_count || 0) ? `<span class="continuity-chip continuity-chip-high">高 ${issue.high_risk_count}</span>` : ""}
                </div>
              </button>
            `;
          }).join("") : `<p class="asset-note">当前筛选下没有片段。</p>`}
        </aside>
        <div class="segment-review-main">
          ${selectedModel ? renderSegmentReviewDetail({ segment: selectedSegment, index: selectedIndex, model: selectedModel, galleryId, characterStatus, helpers }) : singleAssetMessage("无片段", "当前筛选下没有可审片段。")}
        </div>
      </div>
    </section>
  `;
}
