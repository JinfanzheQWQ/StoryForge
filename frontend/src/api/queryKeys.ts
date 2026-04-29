export const queryKeys = {
  artifacts: (taskId?: string) => ["artifacts", taskId] as const,
  project: (projectId?: string) => ["project", projectId] as const,
  projectCardArtifacts: (taskId?: string | null) => ["project-card-artifacts", taskId] as const,
  projects: () => ["projects"] as const,
  storySource: (projectId?: string, sourceTaskId?: string) => ["story-source", projectId, sourceTaskId] as const,
  task: (taskId?: string) => ["task", taskId] as const
};
