import { registerGallery } from "../gallery.js";
import {
  chip,
  escapeAttr,
  escapeHtml,
  getRunStageStatus,
  getStorySourceRevision,
  singleAssetMessage,
} from "../utils.js";
import { renderScenePromptPanel } from "./prompt_tools.js";

function hasTextValue(value) {
  if (Array.isArray(value)) {
    return value.some((item) => String(item || "").trim());
  }
  return Boolean(String(value || "").trim());
}

function renderSceneInfoRows(rows) {
  const normalizedRows = rows
    .map(([label, value]) => [label, Array.isArray(value) ? value.filter(Boolean).join("、") : value])
    .filter(([, value]) => hasTextValue(value));
  if (!normalizedRows.length) {
    return `<p class="asset-note">暂无结构化信息。</p>`;
  }
  return `
    <div class="scene-info-grid">
      ${normalizedRows.map(([label, value]) => `
        <article>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(String(value || ""))}</strong>
        </article>
      `).join("")}
    </div>
  `;
}

function renderSceneBaselinePanel(sceneGroup) {
  const bible = sceneGroup?.sceneBible || {};
  return `
    <section class="scene-info-panel">
      <div class="prompt-section-head">
        <strong>场景基准</strong>
        <span>后续关键帧必须沿用</span>
      </div>
      ${sceneGroup.sceneAnchor ? `<p class="asset-note">${escapeHtml(sceneGroup.sceneAnchor)}</p>` : ""}
      ${renderSceneInfoRows([
        ["地点", bible.location],
        ["时间", bible.time_window],
        ["天气", bible.weather],
        ["光线", bible.lighting],
        ["主色", bible.dominant_palette],
        ["背景锚点", bible.background_anchors],
        ["固定道具", bible.fixed_props],
        ["空间布局", bible.spatial_layout],
        ["角色调度", bible.character_blocking],
        ["连续性", bible.continuity_notes],
      ])}
      ${sceneGroup.coveredEventSummaries?.length ? `
        <div class="scene-event-strip">
          ${sceneGroup.coveredEventSummaries.map((item) => chip(item)).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

function renderSceneTransitionPanel(sceneGroup) {
  const contract = sceneGroup?.sceneTransitionContract || {};
  const hasContract = Object.values(contract).some((value) => hasTextValue(value));
  return `
    <section class="scene-info-panel">
      <div class="prompt-section-head">
        <strong>过渡合同</strong>
        <span>scene 到 scene 的承接要求</span>
      </div>
      ${hasContract ? renderSceneInfoRows([
        ["模式", contract.transition_mode],
        ["上一场景", contract.previous_scene_id],
        ["上一场退出", contract.previous_scene_exit_state],
        ["本场开场匹配", contract.next_scene_entry_match],
        ["桥接动作", contract.bridge_action],
        ["视觉桥", contract.visual_bridge],
        ["声音桥", contract.audio_bridge],
        ["方向策略", contract.screen_direction_policy],
        ["承接元素", contract.carry_over_elements],
        ["聚焦秒数", contract.transition_focus_seconds ? `${contract.transition_focus_seconds}s` : ""],
      ]) : `<p class="asset-note">首个 scene 或当前 scene 不需要跨场过渡合同。</p>`}
    </section>
  `;
}

function renderSceneMasterRiskPanel(sceneGroup, sceneContinuity, sceneMasterTask, helpers) {
  const issues = (sceneContinuity?.issues || []).filter((issue) => {
    const text = [
      issue.code,
      issue.message,
      issue.recommended_action,
      issue.recommended_action_label,
    ].filter(Boolean).join(" ");
    return text.includes("scene_master_frame") || text.includes("场景母图") || text.includes("母图");
  });
  const masterIssueGroup = issues.length ? { ...sceneContinuity, issues, issue_count: issues.length } : null;
  const status = sceneGroup.sceneMasterFrameStatus || (sceneGroup.sceneMasterFrame ? "ready" : "planned");
  return `
    <section class="scene-info-panel scene-master-risk-panel">
      <div class="prompt-section-head">
        <strong>母图状态</strong>
        <span>空环境基准图</span>
      </div>
      <div class="detail-chip-row">
        ${chip(`状态 ${status || "planned"}`)}
        ${sceneGroup.sceneMasterFrame ? chip("母图已生成") : chip("母图未生成")}
      </div>
      <p class="asset-note">场景母图应是无角色环境基准图。若画面出现人物、文字、水印或空间关系错误，请单独重生成场景母图。</p>
      ${sceneGroup.sceneMasterFrameError ? `<p class="asset-note">${escapeHtml(sceneGroup.sceneMasterFrameError)}</p>` : ""}
      ${helpers.renderContinuityIssueList(masterIssueGroup, "当前没有专门指向场景母图的风险。")}
      ${helpers.renderSegmentTaskError(sceneMasterTask, "场景母图失败")}
    </section>
  `;
}

export function renderSceneSegmentMatrix({ sceneGroup, segmentContinuityLookup = new Map() }) {
  if (!sceneGroup?.segments?.length) {
    return "";
  }
  return `
    <div class="scene-segment-matrix">
      <div class="scene-segment-matrix-head">
        <span>Segment</span>
        <span>首帧</span>
        <span>中段</span>
        <span>尾帧</span>
        <span>视频</span>
        <span>风险</span>
      </div>
      ${sceneGroup.segments.map((segment) => {
        const issue = segmentContinuityLookup.get(segment.segmentId) || null;
        const midState = segment.requiresMidFrame ? (segment.midFrame ? "OK" : "缺") : "无";
        const riskText = Number(issue?.high_risk_count || 0)
          ? `高 ${issue.high_risk_count}`
          : Number(issue?.medium_risk_count || 0)
            ? `中 ${issue.medium_risk_count}`
            : issue?.issue_count
              ? `低 ${issue.issue_count}`
              : "稳定";
        return `
          <article class="scene-segment-matrix-row">
            <strong>${escapeHtml(segment.segmentId)}</strong>
            <span class="matrix-state ${segment.startFrame ? "ok" : "missing"}">${segment.startFrame ? "OK" : "缺"}</span>
            <span class="matrix-state ${midState === "OK" || midState === "无" ? "ok" : "missing"}">${escapeHtml(midState)}</span>
            <span class="matrix-state ${segment.endFrame ? "ok" : "missing"}">${segment.endFrame ? "OK" : "缺"}</span>
            <span class="matrix-state ${segment.videoReady ? "ok" : "missing"}">${segment.videoReady ? "OK" : "缺"}</span>
            <span class="matrix-risk ${issue?.high_risk_count ? "high" : issue?.medium_risk_count ? "medium" : ""}">${escapeHtml(riskText)}</span>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderSceneWorkbenchActions({
  sceneGroup,
  rootTask,
  sceneContinuity,
  sceneMasterTaskStatus,
  sceneRepairTaskStatus,
  canGenerateSceneMaster,
  canRunSceneRepair,
  sceneMasterRecommended,
  sceneRepairRemainingActions,
  helpers,
}) {
  return `
    <div class="scene-workbench-action-panel">
      <div class="detail-chip-row">
        ${chip(`片段 ${sceneGroup.segments.length}`)}
        ${chip(`母图 ${sceneGroup.sceneMasterFrame ? "已生成" : "未生成"}`)}
        ${sceneRepairRemainingActions.length ? chip("修复方案已更新") : ""}
        ${helpers.renderContinuityRiskChips(sceneContinuity)}
      </div>
      <div class="timeline-actions">
        <button
          type="button"
          class="secondary small"
          data-auto-repair-scene="${escapeAttr(sceneGroup.sceneId)}"
          data-project-id="${escapeAttr(rootTask.project_id)}"
          data-source-task="${escapeAttr(rootTask.task_id)}"
          ${canRunSceneRepair ? "" : "disabled"}
        >${escapeHtml(helpers.buildSceneRepairButtonLabel(sceneRepairTaskStatus, sceneRepairRemainingActions.length > 0))}</button>
        <button
          type="button"
          class="secondary small${sceneMasterRecommended ? " recommended-action" : ""}"
          data-generate-scene-master="${escapeAttr(sceneGroup.sceneId)}"
          data-project-id="${escapeAttr(rootTask.project_id)}"
          data-source-task="${escapeAttr(rootTask.task_id)}"
          ${canGenerateSceneMaster ? "" : "disabled"}
        >${escapeHtml(helpers.buildSceneMasterButtonLabel(sceneGroup, sceneMasterTaskStatus))}</button>
      </div>
    </div>
  `;
}

export function renderSceneWorkbenchTab({ task, artifacts, context, run = null, helpers }) {
  if (!artifacts?.available) {
    return singleAssetMessage("场景工作台", helpers.buildArtifactPendingMessage(task, "images", run));
  }
  const segments = helpers.buildTimelineSegments(artifacts);
  const sceneGroups = helpers.buildSceneGroups(segments);
  const galleryId = `${context}:scenes:${task.task_id}`;
  registerGallery(galleryId, helpers.buildTimelineGalleryItems(artifacts));
  if (!sceneGroups.length) {
    return singleAssetMessage("场景工作台", "当前版本还没有可展示的 scene。请先生成分段合同。");
  }
  const continuitySceneLookup = helpers.buildContinuityLookup(artifacts?.continuity_scene_groups, "scene_id");
  const continuitySegmentLookup = helpers.buildContinuityLookup(artifacts?.continuity_segment_groups, "segment_id");
  const rootTask = run?.rootTask || task;
  const storySourceRevision = run ? getStorySourceRevision(rootTask) : getStorySourceRevision(task);
  const segmentContractsStatus = run ? getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision) : "idle";
  const batchRepairTask = helpers.getLatestBatchRepairTask(run);
  const batchRepairTaskStatus = run ? getRunStageStatus(batchRepairTask, storySourceRevision) : "idle";
  return `
    <section class="scene-workbench-shell">
      ${helpers.renderAssetSectionIntro(
        "场景工作台",
        "这里按 scene 管理空场景母图、场景风险和同场景下的片段关键帧。场景母图应优先作为无角色环境基准图。",
        [chip(`Scene ${sceneGroups.length}`), chip(`Segment ${segments.length}`)].join(""),
      )}
      <div class="scene-workbench-grid">
        ${sceneGroups.map((sceneGroup) => {
          const sceneContinuity = continuitySceneLookup.get(sceneGroup.sceneId) || null;
          const sceneMasterTask = helpers.getLatestSceneMasterTask(run, sceneGroup.sceneId);
          const sceneRepairTask = helpers.getLatestSceneRepairTask(run, sceneGroup.sceneId);
          const sceneMasterTaskStatus = run ? getRunStageStatus(sceneMasterTask, storySourceRevision) : "idle";
          const sceneRepairTaskStatus = run ? getRunStageStatus(sceneRepairTask, storySourceRevision) : "idle";
          const sceneRepairRemainingActions = helpers.resolveRepairRemainingActions(run, sceneRepairTask, storySourceRevision);
          const canGenerateSceneMaster =
            segmentContractsStatus === "completed"
            && !helpers.isBusyTaskStatus(batchRepairTaskStatus)
            && !helpers.isBusyTaskStatus(sceneRepairTaskStatus)
            && !helpers.isBusyTaskStatus(sceneMasterTaskStatus);
          const canRunSceneRepair =
            segmentContractsStatus === "completed"
            && Boolean(sceneContinuity?.issue_count)
            && !helpers.isBusyTaskStatus(batchRepairTaskStatus)
            && !helpers.isBusyTaskStatus(sceneRepairTaskStatus)
            && !helpers.isBusyTaskStatus(sceneMasterTaskStatus);
          const sceneMasterRecommended = helpers.hasRecommendedContinuityAction(sceneContinuity, "regenerate_scene_master_frame")
            || sceneRepairRemainingActions.includes("regenerate_scene_master_frame");
          return `
            <article class="asset-block scene-workbench-card">
              <div class="story-editor-head">
                <div>
                  <p class="section-kicker">${escapeHtml(sceneGroup.sceneId)}</p>
                  <h4>${escapeHtml(sceneGroup.sceneTitle || sceneGroup.sceneId)}</h4>
                  ${sceneGroup.sceneSummary ? `<p class="asset-note">${escapeHtml(sceneGroup.sceneSummary)}</p>` : ""}
                </div>
                ${renderSceneWorkbenchActions({
                  sceneGroup,
                  rootTask,
                  sceneContinuity,
                  sceneMasterTaskStatus,
                  sceneRepairTaskStatus,
                  canGenerateSceneMaster,
                  canRunSceneRepair,
                  sceneMasterRecommended,
                  sceneRepairRemainingActions,
                  helpers,
                })}
              </div>
              <div class="scene-workbench-master-row">
                ${helpers.renderTimelinePreview(sceneGroup.sceneMasterFrame, "场景母图", galleryId)}
                <div>
                  ${renderSceneBaselinePanel(sceneGroup)}
                  ${renderSceneTransitionPanel(sceneGroup)}
                  ${renderSceneMasterRiskPanel(sceneGroup, sceneContinuity, sceneMasterTask, helpers)}
                  ${renderScenePromptPanel(sceneGroup, rootTask)}
                  ${helpers.renderContinuityIssueList(sceneContinuity, "当前 scene 没有连续性风险。")}
                  ${helpers.renderSegmentTaskError(sceneRepairTask, "场景智能修复失败")}
                  ${helpers.renderRepairPlanNotice(sceneRepairTask, sceneRepairRemainingActions)}
                </div>
              </div>
              ${renderSceneSegmentMatrix({ sceneGroup, segmentContinuityLookup: continuitySegmentLookup })}
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;
}
