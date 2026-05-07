import { Check, LoaderCircle, OctagonX, Pause, Play, Radio, RefreshCcw, RotateCcw } from "lucide-react";
import type { AgentMessage, AgentSession, AgentSessionEvent } from "../../types";
import {
  agentProductionStages,
  canConfirmAgentPlan,
  canPauseAgentSession,
  canRerunAgentCurrentStage,
  canResumeAgentSession,
  canTerminateAgentSession,
  formatAgentTime,
  getAgentStageLabel,
  getRerunnableAgentStageLabel,
  getAgentStatusLabel,
  getRecentAgentEvents,
  truncateMiddle
} from "./agentSessionModel";

interface AgentProgressRailProps {
  events: AgentSessionEvent[];
  isConfirming?: boolean;
  messages: AgentMessage[];
  onConfirm: () => void;
  onPause: () => void;
  onRerunCurrentStage: () => void;
  onResume: () => void;
  onStop: () => void;
  session?: AgentSession | null;
}

export function AgentProgressRail({
  events,
  isConfirming = false,
  messages,
  onConfirm,
  onPause,
  onRerunCurrentStage,
  onResume,
  onStop,
  session
}: AgentProgressRailProps) {
  const completedSteps = session?.progress?.completed_steps || 0;
  const percent = session?.progress?.percent || 0;
  const canConfirm = canConfirmAgentPlan(session, messages);
  const canPause = canPauseAgentSession(session);
  const canResume = canResumeAgentSession(session);
  const canRerun = canRerunAgentCurrentStage(session);
  const canTerminate = canTerminateAgentSession(session);
  const recentEvents = getRecentAgentEvents(events);
  const rerunStageLabel = getRerunnableAgentStageLabel(session?.current_stage);

  return (
    <section className="agent-progress-rail" aria-label="Agent 自动生产进度">
      <header className="agent-panel-heading">
        <span>Production</span>
        <strong>{getAgentStatusLabel(session?.status)}</strong>
        <p>{getAgentStageLabel(session?.current_stage)}</p>
      </header>

      <div className="agent-progress-meter" aria-label={`当前进度 ${percent}%`}>
        <span style={{ width: `${percent}%` }} />
      </div>

      {canConfirm ? (
        <button className="agent-wide-action" disabled={isConfirming} type="button" onClick={onConfirm}>
          {isConfirming ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
          确认计划并开始
        </button>
      ) : null}
      {canPause ? (
        <button className="agent-wide-action agent-pause-action" disabled={isConfirming} type="button" onClick={onPause}>
          {isConfirming ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <Pause size={15} aria-hidden="true" />}
          暂停
        </button>
      ) : null}
      {canResume ? (
        <button className="agent-wide-action" disabled={isConfirming} type="button" onClick={onResume}>
          {isConfirming ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <RotateCcw size={15} aria-hidden="true" />}
          继续
        </button>
      ) : null}
      {canRerun ? (
        <button className="agent-wide-action agent-rerun-action" disabled={isConfirming} type="button" onClick={onRerunCurrentStage}>
          {isConfirming ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <RefreshCcw size={15} aria-hidden="true" />}
          重新跑{rerunStageLabel || "当前阶段"}
        </button>
      ) : null}
      {canTerminate ? (
        <button className="agent-wide-action agent-stop-action" disabled={isConfirming} type="button" onClick={onStop}>
          {isConfirming ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <OctagonX size={15} aria-hidden="true" />}
          终止
        </button>
      ) : null}

      <ol className="agent-stage-list">
        {agentProductionStages.map((stage, index) => {
          const state = resolveStageState(index, completedSteps, session?.status);
          return (
            <li key={stage.key} className={`agent-stage-item ${state}`}>
              <span aria-hidden="true">{state === "done" ? <Check size={13} /> : state === "active" ? <Radio size={13} /> : index + 1}</span>
              <strong>{stage.label}</strong>
            </li>
          );
        })}
      </ol>

      <div className="agent-session-meta">
        <MetaLine label="Session" value={truncateMiddle(session?.session_id)} />
        <MetaLine label="Project" value={truncateMiddle(session?.project_id)} />
        <MetaLine label="Task" value={truncateMiddle(session?.current_task_id)} />
      </div>

      <div className="agent-event-log">
        <strong>最近动态</strong>
        {recentEvents.length ? (
          recentEvents.map((event) => (
            <div key={event.event_id} className="agent-event-row">
              <time>{formatAgentTime(event.created_at)}</time>
              <span>{event.message}</span>
            </div>
          ))
        ) : (
          <p>等待第一条创作指令。</p>
        )}
      </div>
    </section>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div>
      <span>{label}</span>
      <code>{value}</code>
    </div>
  );
}

function resolveStageState(index: number, completedSteps: number, status?: string): "active" | "done" | "todo" {
  if (status === "completed") return "done";
  if (index < completedSteps) return "done";
  if (index === completedSteps && (status === "running" || status === "waiting_task" || status === "paused")) return "active";
  return "todo";
}
