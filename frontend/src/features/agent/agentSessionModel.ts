import type { ArtifactBundle, AgentMessage, AgentSession, AgentSessionEvent } from "../../types";

const AGENT_SESSION_STORAGE_KEY = "storyforge.agentSessionId";
const AGENT_HISTORY_COLLAPSED_STORAGE_KEY = "storyforge.agentHistoryCollapsed";

export const agentProductionStages = [
  { key: "waiting_story", label: "小说正文" },
  { key: "waiting_scene_structure", label: "场景结构" },
  { key: "waiting_segment_contracts", label: "分段合同" },
  { key: "waiting_characters", label: "角色图" },
  { key: "waiting_scenes", label: "场景母图" },
  { key: "waiting_storyboards", label: "九宫格" },
  { key: "waiting_videos", label: "分段视频" },
  { key: "waiting_merge", label: "合并成片" },
  { key: "completed", label: "完成" }
] as const;

export function readStoredAgentSessionId(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(AGENT_SESSION_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function writeStoredAgentSessionId(sessionId: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AGENT_SESSION_STORAGE_KEY, sessionId);
  } catch {
    // Storage can be unavailable in private contexts; the backend session still works for this render.
  }
}

export function clearStoredAgentSessionId() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(AGENT_SESSION_STORAGE_KEY);
  } catch {
    // Ignore storage failures.
  }
}

export function readStoredAgentHistoryCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(AGENT_HISTORY_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeStoredAgentHistoryCollapsed(collapsed: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(AGENT_HISTORY_COLLAPSED_STORAGE_KEY, collapsed ? "true" : "false");
  } catch {
    // Ignore storage failures.
  }
}

export function isAgentSessionActive(status?: string): boolean {
  return status === "running" || status === "waiting_task";
}

export function canPauseAgentSession(session?: AgentSession | null): boolean {
  return Boolean(session && ["running", "waiting_task"].includes(session.status));
}

export function canResumeAgentSession(session?: AgentSession | null): boolean {
  return session?.status === "paused";
}

export function canTerminateAgentSession(session?: AgentSession | null): boolean {
  return Boolean(
    session &&
      ["planning", "waiting_confirmation", "running", "waiting_task", "paused"].includes(session.status)
  );
}

export function canRerunAgentCurrentStage(session?: AgentSession | null): boolean {
  if (!session || !["paused", "failed"].includes(session.status)) return false;
  return Boolean(getRerunnableAgentStageLabel(session.current_stage));
}

export function getRerunnableAgentStageLabel(stage?: string): string {
  if (!stage) return "";
  const labels: Record<string, string> = {
    ready_to_submit_story: "小说正文",
    submitting_story: "小说正文",
    waiting_story: "小说正文",
    submitting_scene_structure: "场景结构",
    waiting_scene_structure: "场景结构",
    submitting_segment_contracts: "分段合同",
    waiting_segment_contracts: "分段合同",
    submitting_characters: "角色图",
    waiting_characters: "角色图",
    submitting_scenes: "场景母图",
    waiting_scenes: "场景母图",
    submitting_storyboards: "九宫格",
    waiting_storyboards: "九宫格",
    submitting_videos: "分段视频",
    waiting_videos: "分段视频",
    submitting_merge: "合并成片",
    waiting_merge: "合并成片"
  };
  return labels[stage] || "";
}

export function isAgentInputLocked(session?: AgentSession | null): boolean {
  if (!session) return true;
  return (
    isAgentSessionActive(session.status) ||
    session.status === "completed" ||
    session.status === "failed" ||
    session.status === "paused" ||
    session.status === "canceled"
  );
}

export function canConfirmAgentPlan(session?: AgentSession | null, messages: AgentMessage[] = []): boolean {
  if (!session || session.status !== "waiting_confirmation") return false;
  return messages.some((message) => message.role === "assistant" && message.type === "plan");
}

export function getLatestPlanMessage(messages: AgentMessage[]): AgentMessage | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.type === "plan") {
      return messages[index];
    }
  }
  return undefined;
}

export function extractPlanSummary(session?: AgentSession | null, planMessage?: AgentMessage): string {
  return (
    readString(readObject(planMessage?.payload?.plan)?.summary) ||
    readString(session?.plan?.summary) ||
    readString(planMessage?.content) ||
    ""
  );
}

export function extractPlanSteps(session?: AgentSession | null, planMessage?: AgentMessage): string[] {
  const messagePlan = readObject(planMessage?.payload?.plan);
  const messageSteps = readStringList(messagePlan?.steps);
  if (messageSteps.length) return messageSteps;
  return readStringList(session?.plan?.steps);
}

export function getAgentStatusLabel(status?: string): string {
  if (status === "created") return "等待创意";
  if (status === "planning") return "理解需求";
  if (status === "waiting_confirmation") return "等待确认";
  if (status === "running") return "提交任务";
  if (status === "waiting_task") return "自动生产中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "paused") return "已暂停";
  if (status === "canceled") return "已停止";
  return status || "未创建";
}

export function getAgentStageLabel(stage?: string): string {
  if (!stage || stage === "created") return "等待创意";
  if (stage === "waiting_confirmation") return "确认计划";
  if (stage === "ready_to_submit_story" || stage === "submitting_story") return "提交小说";
  if (stage === "submitting_scene_structure") return "提交场景结构";
  if (stage === "submitting_segment_contracts") return "提交分段合同";
  if (stage === "submitting_characters") return "提交角色图";
  if (stage === "submitting_scenes") return "提交场景母图";
  if (stage === "submitting_storyboards") return "提交九宫格";
  if (stage === "submitting_videos") return "提交分段视频";
  if (stage === "submitting_merge") return "提交合并";
  if (stage === "canceled") return "已停止";
  const matched = agentProductionStages.find((item) => item.key === stage);
  return matched?.label || stage;
}

export function getAgentWorkspacePath(session?: AgentSession | null): string {
  const projectId = readString(session?.project_id);
  if (!projectId) return "";
  const sourceTaskId = readString(session?.source_task_id);
  return sourceTaskId ? `/console/projects/${projectId}/run/${sourceTaskId}` : `/console/projects/${projectId}`;
}

export function getFinalVideoUrl(bundle?: ArtifactBundle | null): string {
  return readString(bundle?.full_story?.url);
}

export function getArtifactPreviewStats(bundle?: ArtifactBundle | null) {
  return {
    characters: bundle?.character_images?.length || 0,
    clips: bundle?.rendered_clips?.length || 0,
    scenes: bundle?.scenes?.length || bundle?.scene_frames?.length || 0,
    segments: bundle?.planned_segments?.length || 0
  };
}

export function getAgentSessionTitle(session: AgentSession): string {
  return (
    readString(session.intent?.title_hint) ||
    readString(session.intent?.idea).slice(0, 28) ||
    readString(session.user_prompt).slice(0, 28) ||
    "未命名 Agent 会话"
  );
}

export function getAgentSessionSubtitle(session: AgentSession): string {
  return (
    readString(session.intent?.genre) ||
    readString(session.intent?.tone) ||
    getAgentStageLabel(session.current_stage)
  );
}

export function getRecentAgentEvents(events: AgentSessionEvent[], limit = 5): AgentSessionEvent[] {
  return [...events].slice(-limit).reverse();
}

export function formatAgentTime(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function truncateMiddle(value?: string | null, head = 8, tail = 6): string {
  const text = readString(value);
  if (!text) return "";
  if (text.length <= head + tail + 3) return text;
  return `${text.slice(0, head)}...${text.slice(-tail)}`;
}

export function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readObject(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => readString(item)).filter(Boolean);
}
