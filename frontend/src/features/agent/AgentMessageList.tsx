import { Bot, CheckCircle2, CircleAlert, UserRound } from "lucide-react";
import type { AgentMessage, AgentSession } from "../../types";
import {
  extractPlanSteps,
  formatAgentTime,
  getLatestPlanMessage,
  readString
} from "./agentSessionModel";

interface AgentMessageListProps {
  isLoading?: boolean;
  messages: AgentMessage[];
  session?: AgentSession | null;
}

export function AgentMessageList({ isLoading = false, messages, session }: AgentMessageListProps) {
  if (isLoading && messages.length === 0) {
    return (
      <div className="agent-empty-stream" role="status">
        正在恢复会话...
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="agent-empty-stream">
        <span>一句话开始自动创作</span>
        <strong>告诉 Agent 你想做什么短片。</strong>
        <p>例如：做一个清新的校园表白短片，傍晚花园，电影感，人物对白自然。</p>
      </div>
    );
  }

  const latestPlanMessage = getLatestPlanMessage(messages);

  return (
    <div className="agent-message-list" aria-live="polite">
      {messages.map((message) => (
        <article
          key={message.message_id}
          className={[
            "agent-message",
            message.role === "user" ? "agent-message-user" : "agent-message-assistant",
            `agent-message-${message.type}`
          ].join(" ")}
        >
          <div className="agent-message-avatar" aria-hidden="true">
            {message.role === "user" ? <UserRound size={15} /> : <Bot size={15} />}
          </div>
          <div className="agent-message-body">
            <header>
              <span>{message.role === "user" ? "你" : labelAssistantMessageType(message.type)}</span>
              <time>{formatAgentTime(message.created_at)}</time>
            </header>
            <p>{message.content}</p>
            {message.type === "plan" ? (
              <PlanDetails message={message} session={session} highlighted={message.message_id === latestPlanMessage?.message_id} />
            ) : null}
            {message.type === "error" ? (
              <div className="agent-message-alert">
                <CircleAlert size={14} aria-hidden="true" />
                <span>{readString(message.payload?.stage) || "请查看当前阶段错误。"}</span>
              </div>
            ) : null}
            {message.type === "result" ? (
              <div className="agent-message-alert agent-message-result">
                <CheckCircle2 size={14} aria-hidden="true" />
                <span>成片和工作台入口已在右侧更新。</span>
              </div>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function PlanDetails({
  highlighted,
  message,
  session
}: {
  highlighted?: boolean;
  message: AgentMessage;
  session?: AgentSession | null;
}) {
  const steps = extractPlanSteps(session, message);
  if (!steps.length) return null;
  return (
    <div className={highlighted ? "agent-plan-lines active" : "agent-plan-lines"}>
      <span>生产步骤</span>
      <ol>
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </div>
  );
}

function labelAssistantMessageType(type: string): string {
  if (type === "plan") return "生产计划";
  if (type === "progress") return "进度";
  if (type === "error") return "错误";
  if (type === "result") return "结果";
  return "Agent";
}
