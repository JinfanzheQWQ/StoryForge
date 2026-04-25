import {
  buildTaskErrorMessage,
  escapeAttr,
  escapeHtml,
  getRunStageStatus,
  getStorySourceRevision,
  resolveRunContinuityReviewMode,
  stageStatusLabel,
} from "../utils.js";

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

export function renderRunStageActions({ run, helpers }) {
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
  const storyLocator = helpers.resolveStorySourceLocator(rootTask, run);
  const storyMeta = storyLocator
    ? helpers.getStorySourceMeta(storyLocator.projectId, storyLocator.sourceTaskId)
    : { dirty: false, loading: false, saving: false };
  const sceneStructureReady = sceneStructureStatus === "completed";
  const segmentContractsTask = run.latestSegmentContractsTask;
  const {
    progressLabel: segmentContractsProgressLabel,
    failureLabel: segmentContractsFailureLabel,
    resumeFromProgress: resumeSegmentContractsFromProgress,
    buttonLabel: resolvedSegmentContractsButtonLabel,
  } = helpers.resolveSegmentContractsUiState(segmentContractsTask, segmentContractsStatus);
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
    && !["queued", "running"].includes(segmentContractsStatus);
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
            ${escapeHtml(helpers.buildMergeButtonLabel(run.latestArtifacts, mergeStatus))}
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
