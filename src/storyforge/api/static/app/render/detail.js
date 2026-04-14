import { DETAIL_TABS, state } from "../state.js";
import {
  buildTaskDetailSubtitle,
  buildTaskErrorMessage,
  buildTaskTitle,
  buildPipelineStageLabel,
  chip,
  compactId,
  escapeAttr,
  escapeHtml,
  runModeLabel,
  statusLabel,
} from "../utils.js";
import { renderRunStageActions, renderRunTabContent } from "./detail_assets.js";

function renderDetailTab(tab, activeTab, context) {
  const activeClass = tab.id === activeTab ? "active" : "";
  const label = context === "queue" ? tab.queueLabel || tab.label : tab.label;
  return `
    <button
      type="button"
      class="detail-tab ${activeClass}"
      data-detail-context="${escapeAttr(context)}"
      data-detail-tab="${escapeAttr(tab.id)}"
    >
      ${escapeHtml(label)}
    </button>
  `;
}

export function renderRunDetail(task, artifacts, context, run = null) {
  const activeTab = context === "project" ? state.projectDetailTab : state.queueDetailTab;
  const displayTask = run?.latestTask || task;
  const stageText = buildPipelineStageLabel(displayTask, run);
  const errorMessage = buildTaskErrorMessage(displayTask);

  return `
    <div class="detail-header">
      <div>
        <p class="section-kicker">${context === "project" ? "Selected Version" : "Task Detail"}</p>
        <h2>${escapeHtml(buildTaskTitle(task, artifacts))}</h2>
        <p class="detail-subtitle">${escapeHtml(buildTaskDetailSubtitle(task, run))}</p>
      </div>
      <span class="badge ${displayTask.status}">${statusLabel(displayTask.status)}</span>
    </div>

    <section class="detail-summary-card">
      <div class="detail-chip-row">
        ${chip(runModeLabel(displayTask))}
        ${chip(`故事 ${compactId(task.project_id)}`)}
        ${chip(`章节 ${task.payload?.brief?.chapter_count || 0}`)}
        ${chip(`字数 ${task.payload?.brief?.total_word_target || 0}`)}
        ${stageText ? chip(stageText) : ""}
      </div>
      ${artifacts?.output_dir ? `<div class="path-line">素材目录: ${escapeHtml(artifacts.output_dir)}</div>` : ""}
      ${
        errorMessage
          ? `
            <article class="task-error-card">
              <strong>失败原因</strong>
              <p>${escapeHtml(errorMessage)}</p>
            </article>
          `
          : ""
      }
      ${context === "project" && run ? renderRunStageActions(run) : ""}
    </section>

    <div class="detail-tabs">
      ${DETAIL_TABS.map((tab) => renderDetailTab(tab, activeTab, context)).join("")}
    </div>

    ${renderRunTabContent(task, artifacts, context, activeTab, run)}
  `;
}
