import { requestJson } from "./client";
import type { ProjectDeletedResponse, ProjectDetail, ProjectSummary } from "../types";

export function listProjects(): Promise<ProjectSummary[]> {
  return requestJson<ProjectSummary[]>("/v1/projects");
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return requestJson<ProjectDetail>(`/v1/projects/${projectId}`);
}

export function deleteProject(projectId: string): Promise<ProjectDeletedResponse> {
  return requestJson<ProjectDeletedResponse>(`/v1/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE"
  });
}
