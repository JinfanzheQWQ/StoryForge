import { requestJson } from "./client";
import type { ArtifactBundle } from "../types";

export function getTaskArtifacts(taskId: string): Promise<ArtifactBundle> {
  return requestJson<ArtifactBundle>(`/v1/tasks/${taskId}/artifacts`);
}
