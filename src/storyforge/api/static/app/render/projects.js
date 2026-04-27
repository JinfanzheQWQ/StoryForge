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
  filterProjects,
  findPreviewAsset,
  formatShortTime,
  formatTime,
  getProjectRuns,
  getProjectRunsFromTasks,
  getRunStageStatus,
  getStorySourceRevision,
  initialLabel,
  metricCard,
  summarizeRunProgress,
  stageStatusLabel,
  statusLabel,
} from "../utils.js";
import { renderRunDetail } from "./detail.js";
import { renderInto } from "./patch.js";

function renderProjectCardMedia(project, currentRun) {
  const previewAsset = findPreviewAsset(currentRun?.latestArtifacts);
  if (!previewAsset) {
    return `
      <div class="project-card-media empty">
        <span>Story ${escapeHtml(compactId(project.project_id))}</span>
        <strong>${escapeHtml(initialLabel(project.story_title || project.title_hint))}</strong>
      </div>
    `;
  }

  if (previewAsset.kind === "video") {
    return `
      <div class="project-card-media">
        <span>${escapeHtml(previewAsset.label)}</span>
        <video preload="metadata" muted src="${escapeAttr(previewAsset.url)}"></video>
      </div>
    `;
  }

  return `
    <div class="project-card-media">
      <span>${escapeHtml(previewAsset.label)}</span>
      <img src="${escapeAttr(previewAsset.url)}" alt="${escapeAttr(previewAsset.name)}" loading="lazy" />
    </div>
  `;
}

function renderProjectCard(project) {
  const activeClass = project.project_id === state.selectedProjectId ? "active" : "";
  const title = project.story_title || project.title_hint;
  const currentRun = getProjectRunsFromTasks(project.project_id)[0] || null;
  const progress = currentRun
    ? summarizeRunProgress(currentRun)
    : {
        completedCount: project.completed_run_count ? 6 : 0,
        percent: project.latest_status === "completed" ? 100 : 12,
        label: statusLabel(project.latest_status || "queued"),
      };

  return `
    <article
      class="project-card ${activeClass}"
      data-select-project="${escapeAttr(project.project_id)}"
      role="button"
      tabindex="0"
      aria-label="打开项目 ${escapeAttr(title)} 的详情"
    >
      ${renderProjectCardMedia(project, currentRun)}
      <div class="project-card-header project-card-shell project-card-shell-rich">
        <div class="story-avatar">${escapeHtml(initialLabel(title))}</div>
        <div class="project-card-main project-card-main-rich">
          <h3>${escapeHtml(title)}</h3>
          <div class="project-meta">
            <span>${project.run_count} 个版本</span>
            <span>${project.full_story_count} 条总片</span>
            <span>${escapeHtml(formatShortTime(project.updated_at))}</span>
          </div>
          <div class="project-card-progress">
            <div class="progress-card-bar" aria-hidden="true">
              <span style="width: ${progress.percent}%"></span>
            </div>
            <strong>${progress.completedCount} / 6 阶段</strong>
            <small>${escapeHtml(progress.label)}</small>
          </div>
          <p class="project-note">${escapeHtml(buildProjectSummary(project))}</p>
        </div>
        <span class="badge ${project.latest_status || "queued"}">${statusLabel(project.latest_status || "queued")}</span>
      </div>
    </article>
  `;
}

function groupProjects(projects) {
  const groups = [
    { key: "running", title: "制作中", description: "还在继续推进的项目。", items: [] },
    { key: "completed", title: "已完成", description: "已经有较完整结果的项目。", items: [] },
    { key: "queued", title: "待开始", description: "刚创建或等待继续推进的项目。", items: [] },
    { key: "failed", title: "异常", description: "需要回看失败原因的项目。", items: [] },
  ];
  const groupMap = new Map(groups.map((group) => [group.key, group]));
  projects.forEach((project) => {
    const status = project.latest_status || "queued";
    const target = groupMap.get(status) || groupMap.get("queued");
    target.items.push(project);
  });
  return groups.filter((group) => group.items.length > 0);
}

function renderProjectGroup(group) {
  return `
    <section class="project-group">
      <div class="project-group-head">
        <div>
          <p class="section-kicker">${escapeHtml(group.title)}</p>
          <h3>${escapeHtml(group.title)}项目</h3>
          <p>${escapeHtml(group.description)}</p>
        </div>
        <span class="doc-section-count">${group.items.length} 个</span>
      </div>
      <div class="project-library-cards">
        ${group.items.map(renderProjectCard).join("")}
      </div>
    </section>
  `;
}

function renderCompareRow(run) {
  const task = run.rootTask;
  const displayTask = run.latestTask;
  const artifacts = run.latestArtifacts;
  const errorMessage = buildTaskErrorMessage(displayTask);
  const summary = artifacts?.available
    ? `角色图 ${artifacts.character_images.length} / 场景母图 ${artifacts.scene_frames.length} / 片段 ${artifacts.rendered_clips.length}${artifacts.full_story ? " / 总片" : ""}`
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

function renderRunSwitchCard(run) {
  const task = run.rootTask;
  const displayTask = run.latestTask;
  const artifacts = run.latestArtifacts;
  const storySourceRevision = getStorySourceRevision(task);
  const stageStatuses = [
    task.status,
    getRunStageStatus(run.latestSceneStructureTask, storySourceRevision),
    getRunStageStatus(run.latestSegmentContractsTask, storySourceRevision),
    getRunStageStatus(run.latestCharacterTask, storySourceRevision),
    getRunStageStatus(run.latestSceneTask, storySourceRevision),
    getRunStageStatus(run.latestVideoTask, storySourceRevision),
  ];
  const completedCount = stageStatuses.filter((status) => status === "completed").length;
  const activeClass = task.task_id === state.selectedProjectTaskId ? "active" : "";
  const mediaSummary = artifacts?.available
    ? `角色 ${artifacts.character_images.length} / 视频 ${artifacts.rendered_clips.length}`
    : "等待产物";

  return `
    <button
      type="button"
      class="run-switch-card ${activeClass}"
      data-select-project-run="${escapeAttr(task.task_id)}"
    >
      <span class="run-switch-top">
        <strong>版本 ${escapeHtml(compactId(task.task_id))}</strong>
        <span class="badge ${displayTask.status}">${statusLabel(displayTask.status)}</span>
      </span>
      <span class="run-switch-progress">
        <span style="width: ${(completedCount / stageStatuses.length) * 100}%"></span>
      </span>
      <span class="run-switch-meta">
        <small>${escapeHtml(formatShortTime(task.created_at))}</small>
        <small>${escapeHtml(buildPipelineStageLabel(displayTask, run) || stageStatusLabel(displayTask.status))}</small>
        <small>${escapeHtml(mediaSummary)}</small>
      </span>
    </button>
  `;
}

function renderProjectHeroPreview(artifacts) {
  const asset = findPreviewAsset(artifacts);
  if (!asset) {
    return `
      <div class="project-hero-preview empty">
        <span>Asset Preview</span>
        <strong>等待素材生成</strong>
      </div>
    `;
  }

  const media = asset.kind === "video"
    ? `<video preload="metadata" muted src="${escapeAttr(asset.url)}"></video>`
    : `<img src="${escapeAttr(asset.url)}" alt="${escapeAttr(asset.name)}" loading="lazy" />`;

  return `
    <div class="project-hero-preview">
      <span>${escapeHtml(asset.label)}</span>
      ${media}
    </div>
  `;
}

function renderProjectHero(detail, runs, selectedRun, artifacts) {
  const title = detail.story_title || detail.title_hint;
  const latestStage = selectedRun ? buildPipelineStageLabel(selectedRun.latestTask, selectedRun) : "等待开始";
  const fullStoryLabel = artifacts?.full_story ? "已有总片" : "暂无总片";
  const progress = summarizeRunProgress(selectedRun);

  return `
    <section class="project-hero-card">
      <div class="project-hero-main">
        <p class="section-kicker">Story Workspace</p>
        <h2>${escapeHtml(title)}</h2>
        <p class="project-hero-copy">${escapeHtml(detail.brief.idea)}</p>
        <div class="detail-chip-row">
          ${chip(`当前阶段 ${latestStage || statusLabel(detail.latest_status || "queued")}`)}
          ${chip(`版本 ${detail.run_count}`)}
          ${chip(fullStoryLabel)}
          ${chip(`故事编号 ${compactId(detail.project_id)}`)}
        </div>
      </div>
      <div class="project-hero-panel">
        ${renderProjectHeroPreview(artifacts)}
        <div class="project-hero-metrics">
          ${metricCard("制作进度", `${progress.completedCount} / 6`)}
          ${metricCard("最近更新", formatShortTime(detail.updated_at))}
          ${metricCard("角色图", String(artifacts?.character_images?.length || 0))}
          ${metricCard("场景母图", String(artifacts?.scene_frames?.length || 0))}
          ${metricCard("视频片段", String(artifacts?.rendered_clips?.length || 0))}
        </div>
      </div>
      <div class="project-hero-actions">
        <button type="button" class="secondary" data-rerun-project="${escapeAttr(detail.project_id)}">基于当前故事新建版本</button>
        <button type="button" class="secondary danger-button" data-delete-project="${escapeAttr(detail.project_id)}">删除项目</button>
      </div>
    </section>

    <section class="run-switcher-block">
      <div class="compare-head">
        <div>
          <p class="section-kicker">Versions</p>
          <h3>选择制作版本</h3>
          <p>版本切换只影响下方资产工作台，不会改变原始产物。</p>
        </div>
      </div>
      <div class="run-switch-grid">
        ${runs.map((run) => renderRunSwitchCard(run)).join("")}
      </div>
    </section>
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

  const filteredProjects = filterProjects(
    state.projects,
    state.projectListQuery,
    state.projectListStatus,
  );
  if (filteredProjects.length === 0) {
    renderInto(elements.projectList, emptyStateCard(
      "没有匹配的故事",
      "调整搜索词或状态筛选后，再试一次。",
    ));
    return;
  }

  renderInto(elements.projectList, groupProjects(filteredProjects).map(renderProjectGroup).join(""));
}

export function renderProjectDetail() {
  const detail = state.projectDetails.get(state.selectedProjectId);
  if (!detail) {
    renderInto(elements.projectDetailView, emptyStateCard(
      "等待选择故事",
      "从作品库进入一个故事后，这里会展示它的版本历史、阶段状态与全部资产。",
    ));
    return;
  }

  const runs = getProjectRuns(detail);
  const selectedRun = runs.find((run) => run.rootTask?.task_id === state.selectedProjectTaskId) || runs[0] || null;
  const selectedTask = selectedRun?.rootTask || null;
  const artifacts = selectedRun?.latestArtifacts || null;

  renderInto(elements.projectDetailView, `
    <section class="detail-view-shell project-workspace-shell">
      ${renderProjectHero(detail, runs, selectedRun, artifacts)}
      <section class="run-detail-block">
        ${selectedTask && selectedRun ? renderRunDetail(selectedTask, artifacts, "project", selectedRun) : emptyStateCard("还没有版本记录", "这个故事还没有可展示的制作记录。")}
      </section>
      <details class="compare-block compact-version-compare">
        <summary>展开完整版本表</summary>
        <div class="compare-grid">
          ${runs.map((run) => renderCompareRow(run)).join("")}
        </div>
      </details>
    </section>
  `);
}
