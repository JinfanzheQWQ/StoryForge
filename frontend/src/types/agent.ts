export type AgentSessionStatus =
  | "created"
  | "planning"
  | "waiting_confirmation"
  | "running"
  | "waiting_task"
  | "completed"
  | "failed"
  | "paused"
  | "canceled"
  | string;

export type AgentMessageRole = "user" | "assistant" | "system" | string;

export type AgentMessageType =
  | "text"
  | "plan"
  | "progress"
  | "error"
  | "result"
  | "action"
  | string;

export interface AgentSessionProgress {
  completed_steps: number;
  total_steps: number;
  percent: number;
}

export interface AgentSession {
  session_id: string;
  project_id?: string | null;
  source_task_id?: string | null;
  current_task_id?: string | null;
  product_type: string;
  mode: string;
  status: AgentSessionStatus;
  current_stage: string;
  user_prompt: string;
  intent: Record<string, unknown>;
  plan: Record<string, unknown>;
  settings: Record<string, unknown>;
  result: Record<string, unknown>;
  error?: string | null;
  progress: AgentSessionProgress;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
}

export interface AgentMessage {
  message_id: string;
  session_id: string;
  role: AgentMessageRole;
  type: AgentMessageType;
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface AgentSessionEvent {
  event_id: string;
  session_id: string;
  stage: string;
  status: string;
  message: string;
  task_id?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface CreateAgentSessionRequest {
  product_type?: "novel_to_video";
  mode?: "auto_full_pipeline";
  settings?: Record<string, unknown>;
}

export interface SendAgentMessageRequest {
  content: string;
  settings?: Record<string, unknown>;
}

export interface DeleteAgentSessionRequest {
  delete_project?: boolean;
}

export interface AgentSessionDeletedResponse {
  session_id: string;
  deleted: boolean;
  project_id?: string | null;
  project_deleted: boolean;
}

export interface AgentSessionWithMessages {
  session: AgentSession;
  messages: AgentMessage[];
}

export interface AgentSessionsResponse {
  sessions: AgentSession[];
}

export interface AgentMessagesResponse {
  messages: AgentMessage[];
}

export interface AgentSessionEventsResponse {
  events: AgentSessionEvent[];
}
