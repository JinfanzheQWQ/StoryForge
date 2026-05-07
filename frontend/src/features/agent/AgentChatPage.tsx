import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import {
  createAgentSession,
  deleteAgentSession,
  getAgentSession,
  listAgentEvents,
  listAgentMessages,
  listAgentSessions,
  rerunAgentCurrentStage,
  sendAgentMessage
} from "../../api/agentSessions";
import { getTaskArtifacts } from "../../api/artifacts";
import { ApiError } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { AgentMessage, AgentMessagesResponse, AgentSession } from "../../types";
import { AgentArtifactPreview } from "./AgentArtifactPreview";
import { AgentComposer } from "./AgentComposer";
import { AgentMessageList } from "./AgentMessageList";
import { AgentProgressRail } from "./AgentProgressRail";
import { AgentSessionHistory } from "./AgentSessionHistory";
import {
  canConfirmAgentPlan,
  clearStoredAgentSessionId,
  getAgentStatusLabel,
  isAgentInputLocked,
  isAgentSessionActive,
  readStoredAgentHistoryCollapsed,
  readStoredAgentSessionId,
  writeStoredAgentHistoryCollapsed,
  writeStoredAgentSessionId
} from "./agentSessionModel";

export function AgentChatPage() {
  const queryClient = useQueryClient();
  const createRequestedRef = useRef(false);
  const [sessionId, setSessionId] = useState(() => readStoredAgentSessionId());
  const [historyCollapsed, setHistoryCollapsed] = useState(() => readStoredAgentHistoryCollapsed());
  const [formError, setFormError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AgentSession | null>(null);
  const [deleteError, setDeleteError] = useState("");

  const sessionsQuery = useQuery({
    queryFn: () => listAgentSessions(50),
    queryKey: queryKeys.agentSessions(),
    refetchInterval: 6000
  });
  const historySessions = sessionsQuery.data?.sessions || [];

  const createSessionMutation = useMutation({
    mutationFn: () => createAgentSession(),
    onError: (error) => {
      createRequestedRef.current = false;
      setFormError(error instanceof Error ? error.message : "创建 Agent 会话失败。");
    },
    onSuccess: (session) => {
      writeStoredAgentSessionId(session.session_id);
      setSessionId(session.session_id);
      queryClient.setQueryData(queryKeys.agentSession(session.session_id), session);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentSessions() });
    }
  });

  useEffect(() => {
    if (sessionId || createRequestedRef.current || createSessionMutation.isPending) return;
    createRequestedRef.current = true;
    createSessionMutation.mutate();
  }, [createSessionMutation, sessionId]);

  const sessionQuery = useQuery({
    enabled: Boolean(sessionId),
    queryFn: () => getAgentSession(sessionId),
    queryKey: queryKeys.agentSession(sessionId),
    refetchInterval: (query) => (isAgentSessionActive(query.state.data?.status) ? 2500 : false),
    retry: false
  });
  const session = sessionQuery.data;

  useEffect(() => {
    if (!sessionQuery.error) return;
    if (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 404) {
      clearStoredAgentSessionId();
      createRequestedRef.current = false;
      setSessionId("");
      setFormError("上次 Agent 会话不存在，已准备新建会话。");
      return;
    }
    setFormError(sessionQuery.error instanceof Error ? sessionQuery.error.message : "Agent 会话读取失败。");
  }, [sessionQuery.error]);

  const messagesQuery = useQuery({
    enabled: false,
    queryFn: () => listAgentMessages(session?.session_id || ""),
    queryKey: queryKeys.agentMessages(session?.session_id)
  });
  const messages = messagesQuery.data?.messages || [];

  const eventsQuery = useQuery({
    enabled: false,
    queryFn: () => listAgentEvents(session?.session_id || ""),
    queryKey: queryKeys.agentEvents(session?.session_id)
  });
  const events = eventsQuery.data?.events || [];

  const artifactsQuery = useQuery({
    enabled: Boolean(session?.source_task_id),
    queryFn: () => getTaskArtifacts(session?.source_task_id || ""),
    queryKey: queryKeys.artifacts(session?.source_task_id || ""),
    refetchInterval: () => (isAgentSessionActive(session?.status) ? 5000 : false)
  });

  useEffect(() => {
    if (!session?.session_id || !session.updated_at) return;
    void (async () => {
      await queryClient.fetchQuery({
        queryFn: () => listAgentMessages(session.session_id),
        queryKey: queryKeys.agentMessages(session.session_id)
      });
      await queryClient.fetchQuery({
        queryFn: () => listAgentEvents(session.session_id),
        queryKey: queryKeys.agentEvents(session.session_id)
      });
    })();
    if (session.source_task_id) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.artifacts(session.source_task_id) });
    }
  }, [queryClient, session?.session_id, session?.source_task_id, session?.updated_at]);

  const sendMessageMutation = useMutation({
    mutationFn: (content: string) => sendAgentMessage(session?.session_id || sessionId, { content }),
    onMutate: async (content) => {
      setFormError("");
      const activeSessionId = session?.session_id || sessionId;
      if (!activeSessionId) return undefined;
      await queryClient.cancelQueries({ queryKey: queryKeys.agentMessages(activeSessionId) });
      const previousMessages = queryClient.getQueryData<AgentMessagesResponse>(
        queryKeys.agentMessages(activeSessionId)
      );
      const optimisticMessage: AgentMessage = {
        message_id: `optimistic-${Date.now()}`,
        session_id: activeSessionId,
        role: "user",
        type: "text",
        content,
        payload: {},
        created_at: new Date().toISOString()
      };
      queryClient.setQueryData<AgentMessagesResponse>(
        queryKeys.agentMessages(activeSessionId),
        (current) => ({
          messages: [...(current?.messages || []), optimisticMessage]
        })
      );
      return { previousMessages, sessionId: activeSessionId };
    },
    onError: (error, _content, context) => {
      if (context?.sessionId) {
        queryClient.setQueryData(queryKeys.agentMessages(context.sessionId), context.previousMessages);
      }
      setFormError(error instanceof Error ? error.message : "消息发送失败。");
    },
    onSuccess: (response) => {
      writeStoredAgentSessionId(response.session.session_id);
      setSessionId(response.session.session_id);
      queryClient.setQueryData(queryKeys.agentSession(response.session.session_id), response.session);
      queryClient.setQueryData(queryKeys.agentMessages(response.session.session_id), { messages: response.messages });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentSessions() });
      void queryClient.fetchQuery({
        queryFn: () => listAgentEvents(response.session.session_id),
        queryKey: queryKeys.agentEvents(response.session.session_id)
      });
    }
  });

  const rerunCurrentStageMutation = useMutation({
    mutationFn: () => rerunAgentCurrentStage(session?.session_id || sessionId),
    onError: (error) => {
      setFormError(error instanceof Error ? error.message : "重新跑当前阶段失败。");
    },
    onMutate: () => {
      setFormError("");
    },
    onSuccess: (response) => {
      writeStoredAgentSessionId(response.session.session_id);
      setSessionId(response.session.session_id);
      queryClient.setQueryData(queryKeys.agentSession(response.session.session_id), response.session);
      queryClient.setQueryData(queryKeys.agentMessages(response.session.session_id), { messages: response.messages });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentSessions() });
      void queryClient.fetchQuery({
        queryFn: () => listAgentEvents(response.session.session_id),
        queryKey: queryKeys.agentEvents(response.session.session_id)
      });
    }
  });

  const deleteSessionMutation = useMutation({
    mutationFn: ({ deleteProject, targetSessionId }: { deleteProject: boolean; targetSessionId: string }) =>
      deleteAgentSession(targetSessionId, { delete_project: deleteProject }),
    onError: (error) => {
      setDeleteError(error instanceof Error ? error.message : "删除 Agent 会话失败。");
    },
    onMutate: () => {
      setDeleteError("");
    },
    onSuccess: (response, variables) => {
      setDeleteTarget(null);
      if (variables.targetSessionId === sessionId) {
        clearStoredAgentSessionId();
        setSessionId("");
        createRequestedRef.current = false;
      }
      queryClient.removeQueries({ queryKey: queryKeys.agentSession(variables.targetSessionId) });
      queryClient.removeQueries({ queryKey: queryKeys.agentMessages(variables.targetSessionId) });
      queryClient.removeQueries({ queryKey: queryKeys.agentEvents(variables.targetSessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentSessions() });
      if (response.project_deleted) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.projects() });
      }
    }
  });

  const creatingSession = createSessionMutation.isPending && !session;
  const sending = sendMessageMutation.isPending || rerunCurrentStageMutation.isPending;
  const canConfirm = canConfirmAgentPlan(session, messages);
  const inputLocked = isAgentInputLocked(session);
  const composerHint = resolveComposerHint({
    canConfirm,
    creatingSession,
    inputLocked,
    sessionStatus: session?.status
  });

  function submitMessage(content: string) {
    if (!session?.session_id) {
      setFormError("Agent 会话还在创建中，请稍后再发送。");
      return;
    }
    sendMessageMutation.mutate(content);
  }

  function confirmPlan() {
    if (!session?.session_id || !canConfirm) return;
    sendMessageMutation.mutate("开始");
  }

  function stopSession() {
    if (!session?.session_id) return;
    sendMessageMutation.mutate("终止");
  }

  function pauseSession() {
    if (!session?.session_id) return;
    sendMessageMutation.mutate("暂停");
  }

  function resumeSession() {
    if (!session?.session_id) return;
    sendMessageMutation.mutate("继续");
  }

  function rerunCurrentStage() {
    if (!session?.session_id) return;
    rerunCurrentStageMutation.mutate();
  }

  function startNewSession() {
    clearStoredAgentSessionId();
    setFormError("");
    setSessionId("");
    createRequestedRef.current = false;
  }

  function selectSession(nextSessionId: string) {
    if (!nextSessionId || nextSessionId === sessionId) return;
    writeStoredAgentSessionId(nextSessionId);
    setSessionId(nextSessionId);
    setFormError("");
  }

  function toggleHistoryCollapsed() {
    setHistoryCollapsed((current) => {
      const next = !current;
      writeStoredAgentHistoryCollapsed(next);
      return next;
    });
  }

  function requestDeleteSession(target: AgentSession) {
    setDeleteError("");
    setDeleteTarget(target);
  }

  function confirmDeleteSession(deleteProject: boolean) {
    if (!deleteTarget?.session_id) return;
    deleteSessionMutation.mutate({
      deleteProject,
      targetSessionId: deleteTarget.session_id
    });
  }

  return (
    <section className={historyCollapsed ? "agent-page agent-history-collapsed" : "agent-page"} aria-labelledby="agent-title">
      <div className="agent-page-shell">
        <AgentSessionHistory
          activeSessionId={session?.session_id || sessionId}
          collapsed={historyCollapsed}
          isCreating={createSessionMutation.isPending}
          isLoading={sessionsQuery.isLoading}
          onCreate={startNewSession}
          onDeleteRequest={requestDeleteSession}
          onSelect={selectSession}
          onToggleCollapsed={toggleHistoryCollapsed}
          sessions={historySessions}
        />
        <main className="agent-chat-surface">
          <header className="agent-page-header">
            <div>
              <span>StoryForge Agent</span>
              <h1 id="agent-title">Agent 自动创作</h1>
              <p>输入创意，确认计划后自动跑完整小说转视频流程。</p>
            </div>
            <button className="agent-subtle-button" type="button" onClick={startNewSession}>
              <RotateCcw size={14} aria-hidden="true" />
              新会话
            </button>
          </header>

          {formError ? <div className="agent-form-error">{formError}</div> : null}

          <AgentMessageList
            isLoading={messagesQuery.isLoading || sessionQuery.isLoading}
            messages={messages}
            session={session}
          />

          <AgentComposer
            canConfirm={canConfirm}
            disabled={inputLocked}
            isBusy={sending}
            isCreatingSession={creatingSession}
            onConfirm={confirmPlan}
            onSubmit={submitMessage}
            statusHint={composerHint}
          />
        </main>

        <aside className="agent-side-panel">
          <AgentProgressRail
            events={events}
            isConfirming={sending}
            messages={messages}
            onConfirm={confirmPlan}
            onPause={pauseSession}
            onRerunCurrentStage={rerunCurrentStage}
            onResume={resumeSession}
            onStop={stopSession}
            session={session}
          />
          <AgentArtifactPreview
            artifacts={artifactsQuery.data}
            isLoading={artifactsQuery.isLoading}
            session={session}
          />
        </aside>
      </div>
      {deleteTarget ? (
        <div className="agent-delete-layer" role="presentation">
          <button
            className="agent-delete-scrim"
            type="button"
            aria-label="关闭删除会话确认"
            onClick={() => {
              if (!deleteSessionMutation.isPending) setDeleteTarget(null);
            }}
          />
          <section aria-labelledby="agent-delete-title" aria-modal="true" className="agent-delete-dialog" role="dialog">
            <span>Delete Session</span>
            <h2 id="agent-delete-title">删除这个 Agent 会话？</h2>
            <p>
              删除会移除这条聊天记录、进度事件和 Agent 会话状态。你可以选择保留已创建的项目，或连项目资源一起删除。
            </p>
            {deleteTarget.project_id ? (
              <small>绑定项目：{deleteTarget.project_id}</small>
            ) : (
              <small>这个会话还没有绑定项目，只会删除聊天会话。</small>
            )}
            {deleteError ? <div className="agent-delete-error">{deleteError}</div> : null}
            <div className="agent-delete-actions">
              <button
                className="agent-subtle-button"
                disabled={deleteSessionMutation.isPending}
                type="button"
                onClick={() => setDeleteTarget(null)}
              >
                取消
              </button>
              <button
                className="agent-delete-keep-project"
                disabled={deleteSessionMutation.isPending}
                type="button"
                onClick={() => confirmDeleteSession(false)}
              >
                {deleteSessionMutation.isPending ? "删除中..." : "只删会话，保留项目"}
              </button>
              {deleteTarget.project_id ? (
                <button
                  className="agent-delete-with-project"
                  disabled={deleteSessionMutation.isPending}
                  type="button"
                  onClick={() => confirmDeleteSession(true)}
                >
                  会话和项目都删除
                </button>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function resolveComposerHint({
  canConfirm,
  creatingSession,
  inputLocked,
  sessionStatus
}: {
  canConfirm: boolean;
  creatingSession: boolean;
  inputLocked: boolean;
  sessionStatus?: string;
}) {
  if (creatingSession) return "正在创建会话";
  if (canConfirm) return "可以直接确认开始，也可以继续补充修改需求";
  if (inputLocked) return `${getAgentStatusLabel(sessionStatus)}，当前不接受新需求`;
  return "输入创意";
}
