import { requestJson } from "./client";
import type {
  AgentMessagesResponse,
  AgentSession,
  AgentSessionDeletedResponse,
  AgentSessionsResponse,
  AgentSessionEventsResponse,
  AgentSessionWithMessages,
  CreateAgentSessionRequest,
  DeleteAgentSessionRequest,
  SendAgentMessageRequest
} from "../types";

export function createAgentSession(payload: CreateAgentSessionRequest = {}): Promise<AgentSession> {
  return requestJson<AgentSession>("/v1/agent-sessions", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listAgentSessions(limit = 50): Promise<AgentSessionsResponse> {
  return requestJson<AgentSessionsResponse>(`/v1/agent-sessions?limit=${encodeURIComponent(String(limit))}`);
}

export function getAgentSession(sessionId: string): Promise<AgentSession> {
  return requestJson<AgentSession>(`/v1/agent-sessions/${sessionId}`);
}

export function listAgentMessages(sessionId: string): Promise<AgentMessagesResponse> {
  return requestJson<AgentMessagesResponse>(`/v1/agent-sessions/${sessionId}/messages`);
}

export function listAgentEvents(sessionId: string): Promise<AgentSessionEventsResponse> {
  return requestJson<AgentSessionEventsResponse>(`/v1/agent-sessions/${sessionId}/events`);
}

export function sendAgentMessage(
  sessionId: string,
  payload: SendAgentMessageRequest
): Promise<AgentSessionWithMessages> {
  return requestJson<AgentSessionWithMessages>(`/v1/agent-sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function rerunAgentCurrentStage(sessionId: string): Promise<AgentSessionWithMessages> {
  return requestJson<AgentSessionWithMessages>(`/v1/agent-sessions/${sessionId}/rerun-current-stage`, {
    method: "POST"
  });
}

export function deleteAgentSession(
  sessionId: string,
  payload: DeleteAgentSessionRequest = {}
): Promise<AgentSessionDeletedResponse> {
  const query = payload.delete_project ? "?delete_project=true" : "";
  return requestJson<AgentSessionDeletedResponse>(`/v1/agent-sessions/${sessionId}${query}`, {
    method: "DELETE"
  });
}
