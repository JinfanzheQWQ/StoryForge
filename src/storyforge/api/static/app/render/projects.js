import { elements } from "../dom.js";
import { state } from "../state.js";
import {
  buildPipelineStageLabel,
  buildProjectSummary,
  buildTaskErrorMessage,
  chip,
  compactId,
  emptyStateCard,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  formatTime,
  getProjectRuns,
  initialLabel,
  metricCard,
  statusLabel,
} from "../utils.js";
import { renderRunDetail } from "./detail.js";
import { renderInto } from "./patch.js";

function renderProjectCard(project) {
  const activeClass = project.project_id === state.selectedProjectId ? "active" : "";
  const title = project.story_title || project.title_hint;

  return `
    <article class="project-card ${activeClass}">
      <div class="project-card-header project-card-shell">
        <div class="story-avatar">${escapeHtml(initialLabel(title))}</div>
        <div class="project-card-main">
          <button type="button" class="project-select-button" data-select-project="${escapeAttr(project.project_id)}">
            <h3>${escapeHtml(title)}</h3>
          </button>
          <div class="project-meta">
            <span>故事编号 ${escapeHtml(compactId(project.project_id))}</span>
          </div>
          <div class="project-meta">
            <span>${project.run_count} 个版本</span>
            <span>${project.completed_run_count} 次完成</span>
            <span>${project.full_story_count} 条总片</span>
          </div>
          <p class="project-note">${escapeHtml(buildProjectSummary(project))}</p>
        </div>
        <span class="badge ${project.latest_status || "queued"}">${statusLabel(project.latest_status || "queued")}</span>
      </div>
    </article>
  `;
}

function renderCompareRow(run) {
  const task = run.rootTask;
  const displayTask = run.latestTask;
  const artifacts = run.latestArtifacts;
  const errorMessage = buildTaskErrorMessage(displayTask);
  const summary = artifacts?.available
    ? `角色图 ${artifacts.character_images.length} / 场景帧 ${artifacts.scene_frames.length} / 片段 ${artifacts.rendered_clips.length}${artifacts.full_story ? " / 总片" : ""}`
    : "等待产物";
  const activeClass = task.task_id === state.selectedProjectTaskId ? "active" : "";

  return `
    <article class="compare-row ${activeClass}">
      <div>
        <strong>${escapeHtml(formatTime(task.created_at))}</strong>
        <small>版本 ${escapeHtml(compactId(task.task_id))}</small>
      </div>
      <div>
        <span class="badge ${displayTask.status}">${statusLabel(displayTask.status)}</span>
      </div>
      <div>
        <strong>${escapeHtml(buildPipelineStageLabel(displayTask, run))}</strong>
        <small>${escapeHtml(task.payload?.brief?.genre || "未设置风格类型")}</small>
      </div>
      <div>
        <strong>${escapeHtml(summary)}</strong>
        <small>
          <button type="button" class="topbar-link" data-select-project-run="${escapeAttr(task.task_id)}">查看这个版本</button>
        </small>
        ${errorMessage ? `<small class="compare-error">失败原因：${escapeHtml(errorMessage)}</small>` : ""}
      </div>
    </article>
  `;
}

export function renderProjectList() {
  if (state.projects.length === 0) {
    renderInto(elements.projectList, emptyStateCard(
      "还没有故事",
      "完成至少一个故事文本任务后，这里会出现对应的故事档案。",
    ));
    return;
  }

  renderInto(elements.projectList, state.projects.map(renderProjectCard).join(""));
}

export function renderProjectDetail() {
  const detail = state.projectDetails.get(state.selectedProjectId);
  if (!detail) {
    renderInto(elements.projectDetailView, emptyStateCard(
      "等待选择故事",
      "从左侧选择一个故事后，这里会展示它的版本历史和资产对比。",
    ));
    return;
  }

  const runs = getProjectRuns(detail);
  const selectedRun = runs.find((run) => run.rootTask?.task_id === state.selectedProjectTaskId) || runs[0] || null;
  const selectedTask = selectedRun?.rootTask || null;
  const artifacts = selectedRun?.latestArtifacts || null;

  renderInto(elements.projectDetailView, `
    <section class="detail-view-shell">
      <div class="detail-header">
        <div>
          <p class="section-kicker">Story Profile</p>
          <h2>${escapeHtml(detail.story_title || detail.title_hint)}</h2>
          <p class="detail-subtitle">${escapeHtml(detail.brief.idea)}</p>
        </div>
        <span class="badge ${detail.latest_status || "queued"}">${statusLabel(detail.latest_status || "queued")}</span>
      </div>

      <section class="detail-summary-card">
        <div class="detail-chip-row">
          ${chip(`故事编号 ${compactId(detail.project_id)}`)}
          ${chip(`版本 ${detail.run_count}`)}
          ${chip(`已完成 ${detail.completed_run_count}`)}
          ${chip(`异常 ${detail.failed_run_count}`)}
          ${chip(`总片 ${detail.full_story_count}`)}
        </div>
        <div class="detail-metrics">
          ${metricCard("最近更新", formatShortTime(detail.updated_at))}
          ${metricCard("当前状态", statusLabel(detail.latest_status || "queued"))}
          ${metricCard("章节目标", String(detail.brief.chapter_count))}
          ${metricCard("目标字数", String(detail.brief.total_word_target))}
        </div>
        <div class="action-row">
          <button type="button" class="secondary" data-rerun-project="${escapeAttr(detail.project_id)}">基于当前故事新建版本</button>
        </div>
      </section>

      <section class="compare-block">
        <div class="compare-head">
          <div>
            <p class="section-kicker">Version Compare</p>
            <h3>同一故事的版本比较</h3>
            <p>每次从故事文本开始的制作流程都会被视为一个版本，方便你比较文字、图片和成片结果。</p>
          </div>
        </div>
        <div class="compare-grid">
          ${runs.map((run) => renderCompareRow(run)).join("")}
        </div>
      </section>

      <section class="run-detail-block">
        ${selectedTask && selectedRun ? renderRunDetail(selectedTask, artifacts, "project", selectedRun) : emptyStateCard("还没有版本记录", "这个故事还没有可展示的制作记录。")}
      </section>
    </section>
  `);
}
