import { requestJson } from "./client";
import type { StorySourceResponse, UpdateStorySourceRequest } from "../types";

export function getStorySource(projectId: string, sourceTaskId: string): Promise<StorySourceResponse> {
  return requestJson<StorySourceResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/story-source/${encodeURIComponent(sourceTaskId)}`
  );
}

export function updateStorySource(
  projectId: string,
  sourceTaskId: string,
  payload: UpdateStorySourceRequest
): Promise<StorySourceResponse> {
  return requestJson<StorySourceResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/story-source/${encodeURIComponent(sourceTaskId)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload)
    }
  );
}
