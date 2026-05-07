export const queryKeys = {
  agentEvents: (sessionId?: string) => ["agent-events", sessionId] as const,
  agentMessages: (sessionId?: string) => ["agent-messages", sessionId] as const,
  agentSession: (sessionId?: string) => ["agent-session", sessionId] as const,
  agentSessions: () => ["agent-sessions"] as const,
  artifacts: (taskId?: string) => ["artifacts", taskId] as const,
  project: (projectId?: string) => ["project", projectId] as const,
  projectCardArtifacts: (taskId?: string | null) => ["project-card-artifacts", taskId] as const,
  projects: () => ["projects"] as const,
  storySource: (projectId?: string, sourceTaskId?: string) => ["story-source", projectId, sourceTaskId] as const,
  task: (taskId?: string) => ["task", taskId] as const
};
