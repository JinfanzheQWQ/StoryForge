import {
  buildTaskErrorMessage,
  chip,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  getRunStageStatus,
  getStorySourceRevision,
  singleAssetMessage,
  stageStatusLabel,
} from "../utils.js";

export function renderStoryTab({ task, run = null, helpers }) {
  const locator = helpers.resolveStorySourceLocator(task, run);
  if (!locator) {
    return singleAssetMessage("故事文本", "当前版本还没有可展示或编辑的故事正文。");
  }

  const storySource = helpers.getStorySourceDraft(locator.projectId, locator.sourceTaskId);
  const meta = helpers.getStorySourceMeta(locator.projectId, locator.sourceTaskId);
  if (meta.loading && !storySource) {
    return singleAssetMessage("故事文本", "故事正文加载中。");
  }
  if (!storySource) {
    return singleAssetMessage("故事文本", meta.message || "故事正文暂时不可用。");
  }

  const storySourceRevision = run ? getStorySourceRevision(run.rootTask) : storySource.story_source_revision;
  const sceneStructureStatus = run ? getRunStageStatus(run.latestSceneStructureTask, storySourceRevision) : "idle";
  const segmentContractsStatus = run ? getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision) : "idle";
  const segmentContractsTask = run?.latestSegmentContractsTask || null;
  const segmentContractsError = buildTaskErrorMessage(segmentContractsTask);
  const {
    progress: segmentContractsProgress,
    progressLabel: segmentContractsProgressLabel,
    failureLabel: segmentContractsFailureLabel,
    resumeFromProgress: resumeSegmentContractsFromProgress,
    buttonLabel: resolvedSegmentContractsLabel,
  } = helpers.resolveSegmentContractsUiState(segmentContractsTask, segmentContractsStatus);
  const canGenerateSceneStructure =
    !meta.loading
    && !meta.saving
    && !meta.dirty
    && !["queued", "running", "completed"].includes(sceneStructureStatus);
  const canGenerateSegmentContracts =
    !meta.loading
    && !meta.saving
    && !meta.dirty
    && sceneStructureStatus === "completed"
    && !["queued", "running", "completed"].includes(segmentContractsStatus);
  const sceneStructureLabel =
    sceneStructureStatus === "completed"
      ? "场景结构已完成"
      : sceneStructureStatus === "stale"
        ? "重新生成场景结构"
        : sceneStructureStatus === "running"
          ? "场景结构生成中"
          : "生成场景结构";
  const segmentContractsLabel = resolvedSegmentContractsLabel;
  const statusText =
    meta.message
    || (sceneStructureStatus === "stale"
      ? "故事文本已变更，旧的场景结构结果已失效。请保存后重新生成场景结构。"
      : segmentContractsStatus === "stale"
        ? "分段合同已失效。请先重新生成场景结构，再继续生成分段合同。"
        : segmentContractsStatus === "running"
          ? (
            segmentContractsProgressLabel
              ? `分段合同正在生成，当前已完成 ${segmentContractsProgressLabel}。页面会自动刷新。`
              : "分段合同正在生成，页面会自动刷新。"
          )
          : segmentContractsStatus === "failed"
            ? (
              resumeSegmentContractsFromProgress
                ? [
                  segmentContractsFailureLabel
                    ? `分段合同中断：${segmentContractsFailureLabel}。`
                    : "分段合同生成中断。",
                  segmentContractsProgressLabel ? `当前已完成 ${segmentContractsProgressLabel}。` : "",
                  "可以直接从失败位置继续，无需整次重跑。",
                  segmentContractsError ? `失败原因：${segmentContractsError}` : "",
                ]
                  .filter(Boolean)
                  .join("")
                : [
                  "分段合同生成失败。",
                  segmentContractsError ? `失败原因：${segmentContractsError}` : "",
                ]
                  .filter(Boolean)
                  .join("")
            )
            : segmentContractsStatus === "completed"
              ? "场景结构和分段合同都已完成。继续生成角色图，或修改并保存正文后重新规划。"
              : sceneStructureStatus === "completed"
                ? "场景结构已完成。请先检查 scene 划分，再继续生成分段合同。"
                : "先检查并按需修改小说正文，保存后再进入场景结构和分段合同解析。");

  return `
    <section class="story-editor-shell">
      <article class="asset-block story-editor-hero">
        <div class="story-editor-head">
          <div>
            <h4>可编辑小说正文</h4>
            <p class="asset-note">这一层是当前版本的事实文本源。保存后，后续场景结构、分段合同、角色图、场景图和视频都应基于这份正文重新生成。</p>
          </div>
          <div class="story-editor-actions">
            <button
              type="button"
              class="secondary"
              data-story-source-project="${escapeAttr(locator.projectId)}"
              data-save-story-source="${escapeAttr(locator.sourceTaskId)}"
              ${meta.saving || meta.loading || !meta.dirty ? "disabled" : ""}
            >
              ${meta.saving ? "保存中" : meta.dirty ? "保存正文" : "已保存"}
            </button>
            <button
              type="button"
              class="secondary"
              data-story-source-project="${escapeAttr(locator.projectId)}"
              data-generate-scene-structure="${escapeAttr(locator.sourceTaskId)}"
              ${canGenerateSceneStructure ? "" : "disabled"}
            >
              ${escapeHtml(sceneStructureLabel)}
            </button>
            <button
              type="button"
              class="secondary"
              data-story-source-project="${escapeAttr(locator.projectId)}"
              data-generate-segment-contracts="${escapeAttr(locator.sourceTaskId)}"
              data-resume-from-progress="${resumeSegmentContractsFromProgress ? "true" : "false"}"
              ${canGenerateSegmentContracts ? "" : "disabled"}
            >
              ${escapeHtml(segmentContractsLabel)}
            </button>
          </div>
        </div>
        <div class="detail-chip-row">
          ${chip(`章节 ${storySource.chapters.length}`)}
          ${chip(`文本 ${meta.dirty ? "待保存" : "已保存"}`)}
          ${chip(`场景结构 ${stageStatusLabel(sceneStructureStatus)}`)}
          ${chip(`分段合同 ${stageStatusLabel(segmentContractsStatus)}`)}
          ${segmentContractsProgressLabel ? chip(`分段进度 ${segmentContractsProgressLabel}`) : ""}
          ${segmentContractsFailureLabel ? chip(segmentContractsFailureLabel) : ""}
          ${segmentContractsProgress?.resume_ready ? chip("支持失败后继续") : ""}
          ${storySource.story_source_revision ? chip(`修订 ${formatShortTime(storySource.story_source_revision)}`) : ""}
        </div>
        <p
          class="story-status-note"
          data-story-status-note="${escapeAttr(locator.sourceTaskId)}"
        >
          ${escapeHtml(statusText)}
        </p>
      </article>

      <article class="asset-block story-editor-card">
        <label class="story-field">
          <span>故事标题</span>
          <input
            type="text"
            value="${escapeAttr(storySource.story_title)}"
            data-story-title-input="true"
            data-story-source-project="${escapeAttr(locator.projectId)}"
            data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
            ${meta.saving ? "disabled" : ""}
          />
        </label>
      </article>

      ${storySource.chapters
        .map(
          (chapter, index) => `
            <article class="asset-block story-editor-card">
              <div class="story-chapter-head">
                <h4>第 ${chapter.number} 章</h4>
                <span class="kind-tag">chapter</span>
              </div>
              <div class="story-field-grid">
                <label class="story-field">
                  <span>章节标题</span>
                  <input
                    type="text"
                    value="${escapeAttr(chapter.title)}"
                    data-story-chapter-field="title"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  />
                </label>
                <label class="story-field">
                  <span>章节摘要</span>
                  <textarea
                    rows="4"
                    data-story-chapter-field="summary"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  >${escapeHtml(chapter.summary)}</textarea>
                </label>
                <label class="story-field story-field-wide">
                  <span>章节正文</span>
                  <textarea
                    rows="14"
                    data-story-chapter-field="markdown"
                    data-story-source-project="${escapeAttr(locator.projectId)}"
                    data-story-source-task="${escapeAttr(locator.sourceTaskId)}"
                    data-story-chapter-index="${index}"
                    ${meta.saving ? "disabled" : ""}
                  >${escapeHtml(chapter.markdown)}</textarea>
                </label>
              </div>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}
