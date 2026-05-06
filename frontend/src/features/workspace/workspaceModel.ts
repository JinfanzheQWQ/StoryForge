import type { ArtifactItem, CharacterArtifactItem, PlannedSegmentArtifact, StageTaskKind, StorySourceChapter, TaskRecord } from "../../types";

export const productionSteps = [
  {
    description: "沉浸式文稿编辑器，保存后从结构重新生产。",
    mode: "writer",
    section: "小说",
    title: "小说正文"
  },
  {
    description: "故事结构蓝图，检查 scene、segment 和承接关系。",
    mode: "blueprint",
    section: "结构化信息",
    title: "结构蓝图"
  },
  {
    description: "角色定妆墙，只管理当前选中角色的图和 prompt。",
    mode: "casting",
    section: "角色图",
    title: "角色定妆"
  },
  {
    description: "场景空间板，锁定无人物环境母图和空间锚点。",
    mode: "space",
    section: "场景母图",
    title: "场景空间"
  },
  {
    description: "审片生产台，逐段生成并检查参考图和尾帧承接。",
    mode: "review",
    section: "分段视频",
    title: "分段审片"
  },
  {
    description: "轻剪辑预览台，先合并交付，后续扩展裁切和排序。",
    mode: "delivery",
    section: "合并视频",
    title: "合并交付"
  }
];

export type ProductionStep = (typeof productionSteps)[number];

export type StageCompletionState = {
  charactersComplete: boolean;
  sceneStructureComplete: boolean;
  segmentContractsComplete: boolean;
  segmentContractsFailed: boolean;
  segmentContractsResumeReady: boolean;
};

export function getStageCompletionState({
  activeTaskStatus,
  activeTaskType,
  charactersReady,
  hasSceneStructure,
  plannedSegmentCount,
  segmentContractProgress
}: {
  activeTaskStatus?: string;
  activeTaskType?: string;
  charactersReady: boolean;
  hasSceneStructure: boolean;
  plannedSegmentCount: number;
  segmentContractProgress?: { resume_ready?: boolean; status?: string } | null;
}): StageCompletionState {
  const completedTaskType = activeTaskStatus === "completed" ? normalizeTaskType(activeTaskType) : "";
  const segmentProgressStatus = String(segmentContractProgress?.status || "").toLowerCase();
  const segmentContractsFailed = segmentProgressStatus === "failed";
  const segmentContractsInProgress = segmentProgressStatus === "queued" || segmentProgressStatus === "running";
  const segmentContractsComplete =
    segmentProgressStatus === "completed" ||
    completedTaskType === "project.segment_contracts" ||
    (!segmentContractsFailed && !segmentContractsInProgress && plannedSegmentCount > 0);
  return {
    charactersComplete: charactersReady || completedTaskType === "project.characters",
    sceneStructureComplete:
      hasSceneStructure ||
      segmentContractsComplete ||
      completedTaskType === "project.scene_structure",
    segmentContractsComplete,
    segmentContractsFailed,
    segmentContractsResumeReady: Boolean(segmentContractProgress?.resume_ready)
  };
}

export function areCharacterImagesReady(characters: CharacterArtifactItem[]) {
  if (!characters.length) return false;
  return characters.some((item) => {
    const status = String(item.status || "").toLowerCase();
    if (["failed", "planned", "queued", "running"].includes(status)) return false;
    return Boolean(String(item.url || "").trim());
  });
}

export type SceneRow = {
  frame?: ArtifactItem | null;
  prompt: string;
  ready: boolean;
  sceneId: string;
  sceneTitle: string;
  segmentCount: number;
  segmentId: string;
  summary: string;
};

export function getSceneMasterActionState(selectedScene?: SceneRow, fallbackSceneId?: string) {
  const sceneId = selectedScene?.sceneId || fallbackSceneId || "";
  const sceneReady = Boolean(selectedScene?.ready);
  return {
    disabled: !sceneId || sceneReady,
    label: sceneReady ? "场景母图已完成" : "生成当前场景母图",
    sceneId,
    state: sceneReady ? "complete" as const : !sceneId ? "waiting" as const : undefined
  };
}

export function resolveEditableSourceTaskId({
  activeTask,
  fallbackTaskId,
  tasks
}: {
  activeTask?: TaskRecord;
  fallbackTaskId?: string;
  tasks?: TaskRecord[];
}) {
  const taskList = preferActiveTask(tasks || [], activeTask);
  const visited = new Set<string>();
  const candidates = [
    readTaskString(activeTask, "source_task_id"),
    readTaskString(activeTask, "pipeline_root_task_id"),
    activeTask?.task_id,
    fallbackTaskId
  ];

  for (const candidate of candidates) {
    const resolved = resolveEditableTaskCandidate(candidate, taskList, visited);
    if (resolved) return resolved;
  }

  return taskList.find((task) => hasEditableStorySource(task))?.task_id || "";
}

export function resolveSourceTask({
  activeTask,
  sourceTaskId,
  tasks
}: {
  activeTask?: TaskRecord;
  sourceTaskId?: string;
  tasks?: TaskRecord[];
}) {
  if (!sourceTaskId) return undefined;
  return preferActiveTask(tasks || [], activeTask).find((task) => task.task_id === sourceTaskId);
}

export function hasEditableStorySource(task?: TaskRecord) {
  return Boolean(task?.result && typeof task.result.story_source_path === "string" && task.result.story_source_path);
}

export function getSegmentSceneFrame(segment: PlannedSegmentArtifact, sceneRows: SceneRow[]) {
  return segment.scene_master_frame || sceneRows.find((row) => row.sceneId === segment.scene_id)?.frame || null;
}

export function buildSceneRows(segments: PlannedSegmentArtifact[], sceneFrames: ArtifactItem[]): SceneRow[] {
  const rows = new Map<string, SceneRow>();
  for (const segment of segments) {
    const sceneId = segment.scene_id || "unknown-scene";
    const current = rows.get(sceneId) || {
      frame: segment.scene_master_frame,
      prompt: segment.scene_master_frame_prompt || "",
      ready: Boolean(segment.scene_master_frame?.url || segment.scene_ready),
      sceneId,
      sceneTitle: segment.scene_title || sceneId,
      segmentCount: 0,
      segmentId: segment.segment_id,
      summary: segment.scene_summary || segment.summary || ""
    };
    current.segmentCount += 1;
    current.frame = current.frame || segment.scene_master_frame;
    current.prompt = current.prompt || segment.scene_master_frame_prompt || "";
    current.ready = current.ready || Boolean(segment.scene_master_frame?.url || segment.scene_ready);
    current.segmentId = current.segmentId || segment.segment_id;
    rows.set(sceneId, current);
  }
  sceneFrames.forEach((frame, index) => {
    const sceneId = resolveSceneFrameSceneId(frame, rows, index);
    const existing = rows.get(sceneId);
    if (existing) {
      existing.frame = existing.frame || frame;
      existing.ready = existing.ready || Boolean(frame.url);
      rows.set(sceneId, existing);
      return;
    }
    if (!rows.has(sceneId)) {
      rows.set(sceneId, {
        frame,
        prompt: "",
        ready: Boolean(frame.url),
        sceneId,
        sceneTitle: sceneId,
        segmentCount: 0,
        segmentId: "",
        summary: "场景母图已生成"
      });
    }
  });
  return [...rows.values()];
}

function resolveSceneFrameSceneId(frame: ArtifactItem, existingRows: Map<string, SceneRow>, index: number) {
  const explicitSceneId = String(frame.scene_id || "").trim();
  if (explicitSceneId) return explicitSceneId;

  const frameName = String(frame.name || "").trim();
  const normalizedName = frameName.replace(/\.[^.]+$/, "");
  const derivedSceneId = normalizedName
    .replace(/(?:_scene)?_master(?:_frame)?$/i, "")
    .replace(/[-_]?scene[-_]?master$/i, "")
    .trim();
  if (derivedSceneId && existingRows.has(derivedSceneId)) return derivedSceneId;
  if (derivedSceneId) return derivedSceneId;
  return `scene-frame-${index}`;
}

export function selectCharacter(characters: CharacterArtifactItem[], selectedCharacterName: string) {
  if (!characters.length) return undefined;
  return (
    characters.find((item) => {
      const characterName = getCharacterName(item);
      return characterName === selectedCharacterName || item.character_id === selectedCharacterName;
    }) || characters[0]
  );
}

export function selectSceneRow(sceneRows: SceneRow[], selectedSceneId: string, fallbackSceneId?: string) {
  if (!sceneRows.length) return undefined;
  return (
    sceneRows.find((row) => row.sceneId === selectedSceneId) ||
    sceneRows.find((row) => row.sceneId === fallbackSceneId) ||
    sceneRows[0]
  );
}

export function getCharacterName(item: CharacterArtifactItem) {
  return item.character_name || item.name || item.character_id || "unknown-character";
}

function resolveEditableTaskCandidate(candidate: string | undefined, tasks: TaskRecord[], visited: Set<string>): string {
  if (!candidate || visited.has(candidate)) return "";
  visited.add(candidate);
  const task = tasks.find((item) => item.task_id === candidate);
  if (!task) return tasks.length ? "" : candidate;
  if (hasEditableStorySource(task)) return task.task_id;
  return (
    resolveEditableTaskCandidate(readTaskString(task, "source_task_id"), tasks, visited) ||
    resolveEditableTaskCandidate(readTaskString(task, "pipeline_root_task_id"), tasks, visited)
  );
}

function preferActiveTask(tasks: TaskRecord[], activeTask?: TaskRecord) {
  if (!activeTask) return tasks;
  return [activeTask, ...tasks.filter((task) => task.task_id !== activeTask.task_id)];
}

function readTaskString(task: TaskRecord | undefined, key: string) {
  const resultValue = task?.result?.[key];
  if (typeof resultValue === "string" && resultValue.trim()) return resultValue.trim();
  const payloadValue = task?.payload?.[key];
  if (typeof payloadValue === "string" && payloadValue.trim()) return payloadValue.trim();
  return "";
}

export function normalizeStoryChapter(chapter: StorySourceChapter) {
  return {
    number: chapter.number,
    title: chapter.title.trim(),
    summary: chapter.summary.trim(),
    markdown: chapter.markdown.trim()
  };
}

export function countTextChars(value: string) {
  return value.replace(/\s/g, "").length;
}

export function isVideoAsset(item: ArtifactItem) {
  return item.kind === "video" || item.name.endsWith(".mp4") || item.name.endsWith(".mov") || item.name.endsWith(".webm");
}

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "任务提交失败。";
}

export function labelTaskOperation(taskType?: string, pendingStage?: StageTaskKind) {
  const value = pendingStage || normalizeTaskType(taskType) || "";
  if (value === "scene-structure" || value === "project.scene_structure") return "生成场景结构";
  if (value === "segment-contracts" || value === "project.segment_contracts") return "生成分段合同";
  if (value === "characters" || value === "project.characters") return "生成角色图";
  if (value === "scenes" || value === "project.scenes") return "生成场景母图";
  if (value === "storyboards" || value === "project.storyboards") return "生成九宫格分镜";
  if (value === "videos" || value === "project.videos") return "生成 / 合并视频";
  if (value === "project.continuity_repair") return "连续性修复";
  if (value === "project.continuity_repair_batch") return "批量连续性修复";
  if (value === "project.novel") return "生成小说正文";
  return value ? value.replace(/^project\./, "").replace(/_/g, " ") : "等待任务";
}

function normalizeTaskType(taskType?: string) {
  if (taskType === "scene-structure" || taskType === "scene_structure") return "project.scene_structure";
  if (taskType === "segment-contracts" || taskType === "segment_contracts") return "project.segment_contracts";
  if (taskType === "characters") return "project.characters";
  if (taskType === "scenes") return "project.scenes";
  if (taskType === "storyboards") return "project.storyboards";
  if (taskType === "videos") return "project.videos";
  return taskType || "";
}

export function resolveRestorableActiveTaskId({
  latestTaskId,
  routeTaskId,
  submittedTaskId,
  tasks
}: {
  latestTaskId?: string | null;
  routeTaskId?: string;
  submittedTaskId?: string;
  tasks?: TaskRecord[];
}) {
  if (submittedTaskId) return submittedTaskId;
  const runningTask = findLatestRunningStageTask(tasks || []);
  if (runningTask) return runningTask.task_id;
  return routeTaskId || latestTaskId || "";
}

export function sectionForTaskType(taskType?: string) {
  const normalized = normalizeTaskType(taskType);
  if (normalized === "project.scene_structure" || normalized === "project.segment_contracts") return "结构化信息";
  if (normalized === "project.characters") return "角色图";
  if (normalized === "project.scenes") return "场景母图";
  if (normalized === "project.storyboards" || normalized === "project.videos") return "分段视频";
  if (normalized === "project.novel") return "小说";
  return "";
}

function findLatestRunningStageTask(tasks: TaskRecord[]) {
  const runningTasks = tasks
    .filter((task) => {
      const status = String(task.status || "");
      if (status !== "queued" && status !== "running") return false;
      return Boolean(sectionForTaskType(task.task_type || task.stage));
    })
    .sort((left, right) => Date.parse(right.created_at || "") - Date.parse(left.created_at || ""));
  return runningTasks[0];
}

export function selectSegment(segments: PlannedSegmentArtifact[], selectedSegmentId: string) {
  if (!segments.length) return undefined;
  return (
    segments.find((segment) => segment.segment_id === selectedSegmentId) ||
    segments.find((segment) => !segment.rendered_clip?.url && segment.scene_ready) ||
    segments.find((segment) => segment.rendered_clip?.url) ||
    segments[0]
  );
}
