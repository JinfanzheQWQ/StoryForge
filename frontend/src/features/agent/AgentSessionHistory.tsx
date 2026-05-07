import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import type { AgentSession } from "../../types";
import {
  formatAgentTime,
  getAgentSessionSubtitle,
  getAgentSessionTitle,
  getAgentStatusLabel,
  truncateMiddle
} from "./agentSessionModel";

interface AgentSessionHistoryProps {
  activeSessionId?: string;
  collapsed: boolean;
  isCreating?: boolean;
  isLoading?: boolean;
  onCreate: () => void;
  onDeleteRequest: (session: AgentSession) => void;
  onSelect: (sessionId: string) => void;
  onToggleCollapsed: () => void;
  sessions: AgentSession[];
}

export function AgentSessionHistory({
  activeSessionId,
  collapsed,
  isCreating = false,
  isLoading = false,
  onCreate,
  onDeleteRequest,
  onSelect,
  onToggleCollapsed,
  sessions
}: AgentSessionHistoryProps) {
  return (
    <aside className="agent-history-panel" aria-label="Agent 历史会话">
      <header className="agent-history-header">
        {!collapsed ? (
          <div>
            <span>History</span>
            <strong>历史会话</strong>
          </div>
        ) : null}
        <button
          className="agent-history-icon-button"
          type="button"
          aria-label={collapsed ? "展开历史会话" : "收起历史会话"}
          onClick={onToggleCollapsed}
        >
          {collapsed ? <ChevronRight size={15} aria-hidden="true" /> : <ChevronLeft size={15} aria-hidden="true" />}
        </button>
      </header>

      <button
        className={collapsed ? "agent-history-new collapsed" : "agent-history-new"}
        disabled={isCreating}
        type="button"
        onClick={onCreate}
        aria-label="新建 Agent 会话"
      >
        <Plus size={15} aria-hidden="true" />
        {!collapsed ? <span>{isCreating ? "创建中..." : "新会话"}</span> : null}
      </button>

      {!collapsed ? (
        <div className="agent-history-list">
          {isLoading && sessions.length === 0 ? <p>正在读取历史...</p> : null}
          {!isLoading && sessions.length === 0 ? <p>暂无历史会话。</p> : null}
          {sessions.map((session) => {
            const active = session.session_id === activeSessionId;
            return (
              <div
                key={session.session_id}
                className={active ? "agent-history-item active" : "agent-history-item"}
              >
                <button className="agent-history-item-main" type="button" onClick={() => onSelect(session.session_id)}>
                  <span className={`agent-history-status status-${session.status}`}>{getAgentStatusLabel(session.status)}</span>
                  <strong>{getAgentSessionTitle(session)}</strong>
                  <small>{getAgentSessionSubtitle(session)}</small>
                  <em>
                    {formatAgentTime(session.updated_at)}
                    <span>{truncateMiddle(session.session_id, 6, 4)}</span>
                  </em>
                </button>
                <button
                  className="agent-history-delete"
                  type="button"
                  aria-label={`删除会话 ${getAgentSessionTitle(session)}`}
                  onClick={() => onDeleteRequest(session)}
                >
                  <Trash2 size={13} aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </aside>
  );
}
