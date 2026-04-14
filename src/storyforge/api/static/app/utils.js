import { state } from "./state.js";

export function getPipelineRootTaskId(task) {
  return task.result?.pipeline_root_task_id || task.payload?.pipeline_root_task_id || task.task_id;
}

export function getStorySourceRevision(task) {
  return task?.result?.story_source_revision || "";
}

export function isTaskCurrent(task, storySourceRevision) {
  if (!task || !storySourceRevision) {
    return false;
  }
  return task.status === "completed" && getStorySourceRevision(task) === storySourceRevision;
}

export function getRunStageStatus(task, storySourceRevision) {
  if (!task) {
    return "idle";
  }
  if (task.status === "completed" && storySourceRevision && getStorySourceRevision(task) !== storySourceRevision) {
    return "stale";
  }
  return task.status;
}

export function buildTaskErrorMessage(task) {
  if (!task || task.status !== "failed") {
    return "";
  }
  const candidates = [
    task.error,
    task.result?.error,
    task.result?.message,
    task.result?.detail,
  ];
  const message = candidates.find((item) => typeof item === "string" && item.trim());
  return message ? message.trim() : "后端没有返回具体失败原因，请查看服务端日志。";
}

function buildRunGroup(rootTaskId, tasks) {
  const sortedTasks = [...tasks].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  );
  const rootTask = sortedTasks.find((task) => task.task_id === rootTaskId) || sortedTasks[sortedTasks.length - 1];
  const latestTask = sortedTasks[0];
  const analysisTasks = sortedTasks.filter((task) => task.task_type === "project.story_analysis");
  const characterTasks = sortedTasks.filter(
    (task) => task.task_type === "project.characters" || task.task_type === "project.images",
  );
  const sceneTasks = sortedTasks.filter(
    (task) => task.task_type === "project.scenes" || task.task_type === "project.images",
  );
  const videoTasks = sortedTasks.filter((task) => task.task_type === "project.videos");

  return {
    rootTaskId,
    rootTask,
    latestTask,
    tasks: sortedTasks,
    latestAnalysisTask: analysisTasks[0] || null,
    latestCharacterTask: characterTasks[0] || null,
    latestSceneTask: sceneTasks[0] || null,
    latestVideoTask: videoTasks[0] || null,
    latestArtifacts: state.artifactsByTaskId.get(rootTask.task_id) || null,
  };
}

export function getProjectRunsFromTasks(projectId, tasks = state.tasks) {
  const projectTasks = tasks.filter((task) => task.project_id === projectId);
  if (!projectTasks.length) {
    return [];
  }

  const runMap = new Map();
  projectTasks.forEach((task) => {
    const rootTaskId = getPipelineRootTaskId(task);
    if (!runMap.has(rootTaskId)) {
      runMap.set(rootTaskId, []);
    }
    runMap.get(rootTaskId).push(task);
  });

  return Array.from(runMap.entries())
    .map(([rootTaskId, items]) => buildRunGroup(rootTaskId, items))
    .sort((left, right) => Date.parse(right.latestTask.created_at) - Date.parse(left.latestTask.created_at));
}

export function getTaskRun(taskId, tasks = state.tasks) {
  const task = tasks.find((item) => item.task_id === taskId);
  if (!task) {
    return null;
  }
  const rootTaskId = getPipelineRootTaskId(task);
  const runTasks = tasks.filter((item) => getPipelineRootTaskId(item) === rootTaskId);
  if (!runTasks.length) {
    return null;
  }
  return buildRunGroup(rootTaskId, runTasks);
}

export function getProjectRuns(detail) {
  return getProjectRunsFromTasks(detail.project_id, detail.tasks);
}

export function findPreviewAsset(artifacts) {
  if (!artifacts?.available) {
    return null;
  }
  if (artifacts.full_story) {
    return { ...artifacts.full_story, kind: "video", label: "完整成片" };
  }
  if (artifacts.rendered_clips.length) {
    return { ...artifacts.rendered_clips[0], kind: "video", label: "视频片段" };
  }
  if (artifacts.scene_frames.length) {
    return { ...artifacts.scene_frames[0], kind: "image", label: "场景画面" };
  }
  if (artifacts.character_images.length) {
    return { ...artifacts.character_images[0], kind: "image", label: "角色定妆" };
  }
  return null;
}

export function summarizeRunProgress(run, totalStages = 5) {
  if (!run?.rootTask) {
    return {
      completedCount: 0,
      percent: 0,
      label: "等待开始",
    };
  }

  const storySourceRevision = getStorySourceRevision(run.rootTask);
  const statuses = [
    run.rootTask.status,
    getRunStageStatus(run.latestAnalysisTask, storySourceRevision),
    getRunStageStatus(run.latestCharacterTask, storySourceRevision),
    getRunStageStatus(run.latestSceneTask, storySourceRevision),
    getRunStageStatus(run.latestVideoTask, storySourceRevision),
  ];
  const completedCount = statuses.filter((status) => status === "completed").length;
  return {
    completedCount,
    percent: Math.round((completedCount / totalStages) * 100),
    label: buildPipelineStageLabel(run.latestTask, run) || statusLabel(run.latestTask.status),
  };
}

export function buildTaskTitle(task, artifacts) {
  const title = (
    artifacts?.story_title ||
    task.result?.story_title ||
    task.payload?.brief?.title_hint ||
    task.task_id
  );
  const taskType = taskTypeLabel(task);
  return taskType ? `${title} · ${taskType}` : title;
}

export function buildTaskExcerpt(task, artifacts) {
  const stageText = buildPipelineStageLabel(task);
  const errorMessage = buildTaskErrorMessage(task);
  if (errorMessage) {
    return stageText ? `${stageText} / ${errorMessage}` : errorMessage;
  }
  if (artifacts?.available) {
    const parts = [
      `${artifacts.character_images.length} 张角色图`,
      `${artifacts.scene_frames.length} 张场景帧`,
      `${artifacts.rendered_clips.length} 条视频`,
    ];
    if (artifacts.full_story) {
      parts.push("有总片");
    }
    return stageText ? `${stageText} / ${parts.join(" / ")}` : parts.join(" / ");
  }
  return stageText || task.payload?.brief?.idea || "等待这一阶段的内容产出。";
}

export function buildTaskDetailSubtitle(task, run = null) {
  const brief = task.payload?.brief;
  if (!brief) {
    const storyTitle = task.result?.story_title || "当前故事";
    const latestStage = run ? buildPipelineStageLabel(run.latestTask, run) : buildPipelineStageLabel(task);
    return `${storyTitle} 的制作记录。${latestStage ? ` 当前阶段：${latestStage}。` : ""}`;
  }
  const latestStage = run ? buildPipelineStageLabel(run.latestTask, run) : buildPipelineStageLabel(task);
  return `${brief.idea} 类型：${brief.genre || "未设置"}；调性：${brief.tone || "未设置"}；章节：${brief.chapter_count}；目标字数：${brief.total_word_target}。${latestStage ? ` 当前阶段：${latestStage}。` : ""}`;
}

export function buildOverviewNote(task, artifacts, run = null) {
  const effectiveTask = run?.latestTask || task;
  const storySourceRevision = run ? getStorySourceRevision(run.rootTask) : getStorySourceRevision(task);
  const analysisStatus = run ? getRunStageStatus(run.latestAnalysisTask, storySourceRevision) : "idle";
  const characterStatus = run ? getRunStageStatus(run.latestCharacterTask, storySourceRevision) : "idle";
  const sceneStatus = run ? getRunStageStatus(run.latestSceneTask, storySourceRevision) : "idle";
  const videoStatus = run ? getRunStageStatus(run.latestVideoTask, storySourceRevision) : "idle";
  if (effectiveTask.status === "queued") {
    return "任务已经创建，正在等待系统开始制作。";
  }
  if (effectiveTask.status === "running") {
    return buildPipelineStageLabel(effectiveTask, run) || "当前阶段正在制作中，页面会自动刷新状态。";
  }
  if (effectiveTask.status === "failed") {
    return "这个版本在当前阶段出现异常，可以回到故事资产页比较其他版本。";
  }
  if (!artifacts?.available) {
    return "当前阶段已完成，但页面还在整理可展示的内容索引。";
  }
  if (run?.latestTask.task_type === "project.story") {
    return "故事文本已经完成。先在“小说”页确认或修改正文，再继续生成结构化信息。";
  }
  if (analysisStatus === "stale") {
    return "故事正文已经更新，当前结构化结果已过期。请先重新生成结构化信息，再继续图片和视频阶段。";
  }
  if (run?.latestTask.task_type === "project.story_analysis") {
    return "结构化信息已经完成。确认角色和章节拆分准确后，再继续生成角色图。";
  }
  if (characterStatus === "stale") {
    return "角色图仍然对应旧文本版本。请先重新生成角色图，再继续场景图。";
  }
  if (run?.latestTask.task_type === "project.characters") {
    return "角色设定已经完成。确认人物稳定后，再继续生成场景图。";
  }
  if (sceneStatus === "stale") {
    return "场景图仍然对应旧文本版本。请先重新生成场景图，再继续视频。";
  }
  if (run?.latestTask.task_type === "project.scenes") {
    return "场景镜头已经完成。确认首尾帧满意后，再继续生成视频。";
  }
  if (run?.latestTask.task_type === "project.images") {
    return "图片阶段已经完成。确认角色和场景一致后，再继续生成视频。";
  }
  if (videoStatus === "stale") {
    return "视频仍然对应旧文本版本。请按新的正文重新生成视频。";
  }
  return artifacts.full_story
    ? "这个版本已经产出完整成片，可以继续和同故事的其它版本对比。"
    : "这个版本已经产出部分内容，但还没有完整成片。";
}

export function buildArtifactPendingMessage(task, kind, run = null) {
  const effectiveTask = run?.latestTask || task;
  const storySourceRevision = run ? getStorySourceRevision(run.rootTask) : getStorySourceRevision(task);
  const analysisStatus = run ? getRunStageStatus(run.latestAnalysisTask, storySourceRevision) : "idle";
  const characterStatus = run ? getRunStageStatus(run.latestCharacterTask, storySourceRevision) : "idle";
  const sceneStatus = run ? getRunStageStatus(run.latestSceneTask, storySourceRevision) : "idle";
  if (effectiveTask.status === "running") {
    if (effectiveTask.task_type === "project.story" && kind !== "docs") {
      return "故事文本还在生成，先等待第一步完成。";
    }
    if (effectiveTask.task_type === "project.story_analysis" && kind !== "docs") {
      return "结构化信息正在生成，完成后才能继续图片和视频阶段。";
    }
    if (effectiveTask.task_type === "project.characters" && kind === "characters") {
      return "角色图正在生成，页面会自动刷新。";
    }
    if (effectiveTask.task_type === "project.scenes" && kind === "scenes") {
      return "场景图正在生成，页面会自动刷新。";
    }
    if (
      (effectiveTask.task_type === "project.images" || effectiveTask.task_type === "project.scenes")
      && kind === "videos"
    ) {
      return "图片还在生成，视频阶段暂时不能开始。";
    }
    return "任务正在执行中，页面会自动同步刷新。";
  }
  if (effectiveTask.status === "failed") {
    return "这一阶段出现异常，只能展示当前已经产出的部分内容。";
  }
  if (run?.latestTask.task_type === "project.story") {
    if (kind === "images" || kind === "characters" || kind === "scenes" || kind === "videos") {
      return "故事文本已经完成，但结构化信息阶段还没开始。请先生成结构化信息。";
    }
  }
  if (analysisStatus === "stale") {
    return "故事正文已经修改，旧的结构化结果已过期。请先重新生成结构化信息。";
  }
  if (run?.latestTask.task_type === "project.story_analysis") {
    if (kind === "images" || kind === "characters") {
      return "结构化信息已经完成，但角色图阶段还没开始。请先生成角色图。";
    }
    if (kind === "scenes" || kind === "videos") {
      return "角色图和后续媒体阶段都还没开始，建议先生成角色图。";
    }
  }
  if (characterStatus === "stale") {
    return "角色图仍然对应旧文本版本。请先重新生成角色图。";
  }
  if (run?.latestTask.task_type === "project.characters") {
    if (kind === "scenes") {
      return "角色图已经完成，但场景图阶段还没开始。请继续生成场景图。";
    }
    if (kind === "videos") {
      return "场景图和视频阶段都还没开始，建议先生成场景图。";
    }
  }
  if (
    (run?.latestTask.task_type === "project.scenes" || run?.latestTask.task_type === "project.images")
    && kind === "videos"
  ) {
    return "场景图已经完成，但视频阶段还没开始。请继续生成视频。";
  }
  if (sceneStatus === "stale") {
    return "场景图仍然对应旧文本版本。请先重新生成场景图。";
  }
  return "页面还在整理这一阶段可展示的内容索引。";
}

export function buildPipelineStageLabel(task, run = null) {
  const effectiveTask = run?.latestTask || task;
  const propagatedStage = effectiveTask.result?.pipeline_stage;
  if (propagatedStage === "story_analysis_started" && effectiveTask.status === "running") {
    return "结构化信息生成中";
  }
  if (propagatedStage === "story_analysis_completed") {
    return "结构化信息已完成";
  }
  if (propagatedStage === "characters_completed") {
    return "角色图已完成";
  }
  if (propagatedStage === "scenes_completed") {
    return "场景图已完成";
  }
  if (propagatedStage === "video_completed") {
    return "视频已完成";
  }
  if (effectiveTask.task_type === "project.story") {
    if (effectiveTask.status === "queued") return "等待故事文本";
    if (effectiveTask.status === "running") return "故事文本生成中";
    if (effectiveTask.status === "completed") return "故事文本已完成";
    if (effectiveTask.status === "failed") return "故事文本生成失败";
  }
  if (effectiveTask.task_type === "project.story_analysis") {
    if (effectiveTask.status === "queued") return "等待结构化解析";
    if (effectiveTask.status === "running") return "结构化信息生成中";
    if (effectiveTask.status === "completed") return "结构化信息已完成";
    if (effectiveTask.status === "failed") return "结构化信息生成失败";
  }
  if (effectiveTask.task_type === "project.characters") {
    if (effectiveTask.status === "queued") return "等待角色设定图";
    if (effectiveTask.status === "running") return "角色图生成中";
    if (effectiveTask.status === "completed") return "角色图已完成";
    if (effectiveTask.status === "failed") return "角色图生成失败";
  }
  if (effectiveTask.task_type === "project.scenes") {
    if (effectiveTask.status === "queued") return "等待场景镜头图";
    if (effectiveTask.status === "running") return "场景图生成中";
    if (effectiveTask.status === "completed") return "场景图已完成";
    if (effectiveTask.status === "failed") return "场景图生成失败";
  }
  if (effectiveTask.task_type === "project.images") {
    if (effectiveTask.status === "queued") return "等待生成图片";
    if (effectiveTask.status === "running") return "图片生成中";
    if (effectiveTask.status === "completed") return "图片已完成";
    if (effectiveTask.status === "failed") return "图片生成失败";
  }
  if (effectiveTask.task_type === "project.videos") {
    if (effectiveTask.status === "queued") return "等待视频生成";
    if (effectiveTask.status === "running") return "视频生成中";
    if (effectiveTask.status === "completed") return "视频已完成";
    if (effectiveTask.status === "failed") return "视频生成失败";
  }
  if (effectiveTask.task_type === "project.build") {
    const stage = effectiveTask.result?.pipeline_stage;
    if (effectiveTask.status === "running" && stage === "story_source_completed") {
      return "故事正文已完成，结构与媒体生成中";
    }
    if (effectiveTask.status === "running" && stage === "story_analysis_completed") {
      return "文本与结构已完成，媒体生成中";
    }
    if (effectiveTask.status === "running") {
      return "全链路生成中";
    }
    if (stage === "video_completed" || effectiveTask.status === "completed") {
      return "全链路完成";
    }
    if (effectiveTask.status === "failed" && stage === "story_analysis_completed") {
      return "文本与结构完成，媒体阶段失败";
    }
    if (effectiveTask.status === "failed" && stage === "story_source_completed") {
      return "故事正文完成，后续阶段失败";
    }
  }
  return "";
}

export function runModeLabel(task) {
  const llmLabel = "DeepSeek";
  if (task.task_type === "project.story") {
    return `${llmLabel} / 故事文本`;
  }
  if (task.task_type === "project.story_analysis") {
    return `${llmLabel} / 结构解析`;
  }
  if (task.task_type === "project.characters") {
    return "Seedream / 角色设定";
  }
  if (task.task_type === "project.scenes") {
    return "Seedream / 场景镜头";
  }
  if (task.task_type === "project.images") {
    return "Seedream / 图片阶段";
  }
  if (task.task_type === "project.videos") {
    return "Seedance / 视频阶段";
  }
  if (task.task_type === "project.build") {
    return `${llmLabel} / 全流程`;
  }
  return llmLabel;
}

export function taskTypeLabel(task) {
  if (task.task_type === "project.story") return "故事文本";
  if (task.task_type === "project.story_analysis") return "结构化信息";
  if (task.task_type === "project.characters") return "角色设定图";
  if (task.task_type === "project.scenes") return "场景镜头图";
  if (task.task_type === "project.images") return "图片";
  if (task.task_type === "project.videos") return "视频成片";
  if (task.task_type === "project.build") return "全流程";
  return "";
}

export function metricCard(label, value) {
  return `
    <article class="detail-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `;
}

export function chip(text) {
  return `<span class="detail-chip">${escapeHtml(text)}</span>`;
}

export function singleAssetMessage(title, message) {
  return `
    <article class="asset-block">
      <h4>${title}</h4>
      <p class="asset-note">${message}</p>
    </article>
  `;
}

export function emptyStateCard(title, message) {
  return `
    <article class="empty-state">
      <h3>${title}</h3>
      <p>${message}</p>
    </article>
  `;
}

export function statusLabel(status) {
  if (status === "queued") return "待开始";
  if (status === "running") return "制作中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "异常";
  return status;
}

export function stageStatusLabel(status) {
  if (status === "idle") return "未开始";
  if (status === "stale") return "待更新";
  return statusLabel(status);
}

export function kindLabel(kind) {
  if (kind === "json") return "JSON";
  if (kind === "markdown") return "MD";
  if (kind === "shell") return "SH";
  if (kind === "text") return "TXT";
  if (kind === "image") return "IMG";
  if (kind === "video") return "MP4";
  return "FILE";
}

export function formatTime(value) {
  if (!value) {
    return "未开始";
  }
  return new Date(value).toLocaleString();
}

export function formatShortTime(value) {
  if (!value) {
    return "未开始";
  }
  return new Date(value).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function compactId(value) {
  const text = String(value || "");
  return text ? text.slice(0, 8).toUpperCase() : "N/A";
}

export function initialLabel(value) {
  const text = String(value || "").trim();
  return text ? text.slice(0, 1).toUpperCase() : "S";
}

export function buildProjectSummary(project) {
  if (project.full_story_count) {
    return "最近版本已经产出完整成片，可进入详情页继续比较不同版本。";
  }
  if (project.completed_run_count) {
    return `这个故事已经完成 ${project.completed_run_count} 个版本，可以继续补做角色、场景或视频阶段。`;
  }
  return "故事已经创建，正在等待第一版内容完成。";
}

export function filterProjects(projects, query, status) {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  return projects.filter((project) => {
    if (status && status !== "all" && (project.latest_status || "queued") !== status) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    const candidates = [
      project.story_title,
      project.title_hint,
      project.latest_status,
      project.brief?.idea,
      project.brief?.genre,
      project.brief?.tone,
    ]
      .filter(Boolean)
      .map((item) => String(item).toLowerCase());
    return candidates.some((item) => item.includes(normalizedQuery));
  });
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function escapeAttr(value) {
  return escapeHtml(value);
}
