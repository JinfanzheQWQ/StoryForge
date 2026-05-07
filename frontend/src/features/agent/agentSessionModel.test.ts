import { describe, expect, it } from "vitest";
import type { AgentMessage, AgentSession } from "../../types";
import {
  canConfirmAgentPlan,
  canPauseAgentSession,
  canRerunAgentCurrentStage,
  canResumeAgentSession,
  canTerminateAgentSession,
  extractPlanSteps,
  getRerunnableAgentStageLabel,
  getAgentWorkspacePath,
  getFinalVideoUrl,
  isAgentInputLocked,
  isAgentSessionActive,
  truncateMiddle
} from "./agentSessionModel";

describe("agentSessionModel", () => {
  it("detects active and locked session states", () => {
    expect(isAgentSessionActive("waiting_task")).toBe(true);
    expect(isAgentSessionActive("running")).toBe(true);
    expect(isAgentSessionActive("waiting_confirmation")).toBe(false);
    expect(isAgentInputLocked({ status: "waiting_task" } as AgentSession)).toBe(true);
    expect(isAgentInputLocked({ status: "waiting_confirmation" } as AgentSession)).toBe(false);
    expect(isAgentInputLocked({ status: "canceled" } as AgentSession)).toBe(true);
    expect(canPauseAgentSession({ status: "waiting_task" } as AgentSession)).toBe(true);
    expect(canPauseAgentSession({ status: "paused" } as AgentSession)).toBe(false);
    expect(canResumeAgentSession({ status: "paused" } as AgentSession)).toBe(true);
    expect(canTerminateAgentSession({ status: "waiting_task" } as AgentSession)).toBe(true);
    expect(canTerminateAgentSession({ status: "completed" } as AgentSession)).toBe(false);
    expect(canRerunAgentCurrentStage({ status: "paused", current_stage: "waiting_storyboards" } as AgentSession)).toBe(true);
    expect(canRerunAgentCurrentStage({ status: "failed", current_stage: "waiting_videos" } as AgentSession)).toBe(true);
    expect(canRerunAgentCurrentStage({ status: "waiting_task", current_stage: "waiting_videos" } as AgentSession)).toBe(false);
    expect(canRerunAgentCurrentStage({ status: "canceled", current_stage: "waiting_videos" } as AgentSession)).toBe(false);
    expect(getRerunnableAgentStageLabel("waiting_storyboards")).toBe("九宫格");
  });

  it("resolves plan confirmation from session and assistant plan message", () => {
    const session = { status: "waiting_confirmation" } as AgentSession;
    const messages = [
      {
        role: "assistant",
        type: "plan"
      } as AgentMessage
    ];
    expect(canConfirmAgentPlan(session, messages)).toBe(true);
    expect(canConfirmAgentPlan({ status: "running" } as AgentSession, messages)).toBe(false);
  });

  it("extracts plan steps and workspace path", () => {
    const message = {
      content: "计划",
      created_at: "2026-05-07T00:00:00Z",
      message_id: "m1",
      payload: {
        plan: {
          steps: ["小说正文", "角色图"]
        }
      },
      role: "assistant",
      session_id: "s1",
      type: "plan"
    } satisfies AgentMessage;
    const session = {
      project_id: "project-1",
      source_task_id: "task-1"
    } as AgentSession;
    expect(extractPlanSteps(undefined, message)).toEqual(["小说正文", "角色图"]);
    expect(getAgentWorkspacePath(session)).toBe("/console/projects/project-1/run/task-1");
  });

  it("resolves preview URLs and compact ids", () => {
    expect(getFinalVideoUrl({ full_story: { name: "full_story.mp4", url: "/outputs/full_story.mp4" } })).toBe(
      "/outputs/full_story.mp4"
    );
    expect(truncateMiddle("1234567890abcdef", 4, 4)).toBe("1234...cdef");
  });
});
