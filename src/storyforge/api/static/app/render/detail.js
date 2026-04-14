import { DETAIL_TABS, state } from "../state.js";
import {
  buildTaskDetailSubtitle,
  buildTaskErrorMessage,
  buildTaskTitle,
  buildPipelineStageLabel,
  chip,
  compactId,
  escapeHtml,
  runModeLabel,
  statusLabel,
} from "../utils.js";
import { renderRunStageActions, renderRunTabContent } from "./detail_assets.js";

function renderDetailTab(tab, activeTab) {
  const activeClass = tab.id === activeTab ? "active" : "";
  return `
    <button
      type="button"
      class="detail-tab ${activeClass}"
      data-detail-tab="${escapeHtml(tab.id)}"
    >
      ${escapeHtml(tab.label)}
    </button>
  `;
}

export function renderRunDetail(task, artifacts, context, run = null) {
  const activeTab = state.projectDetailTab;
  const displayTask = run?.latestTask || task;
  const stageText = buildPipelineStageLabel(displayTask, run);
  const errorMessage = buildTaskErrorMessage(displayTask);

  return `
    <div class="detail-header">
      <div>
        <p class="section-kicker">Selected Version</p>
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
      ${run ? renderRunStageActions(run) : ""}
    </section>

    <section class="workspace-content-shell">
      <div class="workspace-content-head">
        <div>
          <p class="section-kicker">Content Navigator</p>
          <h3>查看当前版本内容</h3>
          <p class="asset-note">按故事正文、素材、视频和文件切换，当前页面始终围绕同一个制作版本展开。</p>
        </div>
        <div class="detail-tabs">
          ${DETAIL_TABS.map((tab) => renderDetailTab(tab, activeTab)).join("")}
        </div>
      </div>
      ${renderRunTabContent(task, artifacts, context, activeTab, run)}
    </section>
  `;
}
