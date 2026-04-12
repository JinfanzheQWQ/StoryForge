import { elements } from "../dom.js";
import { state } from "../state.js";
import {
  buildTaskExcerpt,
  buildTaskTitle,
  emptyStateCard,
  escapeAttr,
  escapeHtml,
  formatShortTime,
  runModeLabel,
  statusLabel,
} from "../utils.js";
import { renderRunDetail } from "./detail.js";
import { renderInto } from "./patch.js";

function renderQueueTaskCard(task) {
  const artifacts = state.artifactsByTaskId.get(task.task_id);
  const activeClass = task.task_id === state.selectedQueueTaskId ? "active" : "";
  return `
    <article class="task-card ${activeClass}">
      <div class="task-card-header">
        <button type="button" class="task-select-button" data-select-queue-task="${escapeAttr(task.task_id)}">
          <h3>${escapeHtml(buildTaskTitle(task, artifacts))}</h3>
        </button>
        <span class="badge ${task.status}">${statusLabel(task.status)}</span>
      </div>
      <div class="project-meta">
        <span>${escapeHtml(runModeLabel(task))}</span>
        <span>${escapeHtml(formatShortTime(task.created_at))}</span>
      </div>
      <p class="project-note">${escapeHtml(buildTaskExcerpt(task, artifacts))}</p>
    </article>
  `;
}

export function renderQueueList() {
  if (state.tasks.length === 0) {
    renderInto(elements.queueTaskList, emptyStateCard(
      "还没有任务",
      "从“新建故事”开始创建第一条制作记录，这里会自动展示最新任务。",
    ));
    return;
  }

  renderInto(elements.queueTaskList, state.tasks.map(renderQueueTaskCard).join(""));
}

export function renderQueueDetail() {
  const task = state.tasks.find((item) => item.task_id === state.selectedQueueTaskId);
  if (!task) {
    renderInto(elements.queueDetailView, emptyStateCard(
      "等待选择任务",
      "从左侧任务列表选中一条记录，这里会显示该次制作的完整详情。",
    ));
    return;
  }

  const artifacts = state.artifactsByTaskId.get(task.task_id);
  renderInto(
    elements.queueDetailView,
    `<section class="detail-view-shell">${renderRunDetail(task, artifacts, "queue")}</section>`,
  );
}
