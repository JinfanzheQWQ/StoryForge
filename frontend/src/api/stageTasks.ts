import { requestJson } from "./client";
import type { CreateNovelRequest, CreateStageTaskRequest, StageTaskKind, StageTaskResponse } from "../types";

export function createNovelTask(payload: CreateNovelRequest): Promise<StageTaskResponse> {
  return requestJson<StageTaskResponse>("/v1/projects/novel", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createStageTask(stage: StageTaskKind, payload: CreateStageTaskRequest): Promise<StageTaskResponse> {
  return requestJson<StageTaskResponse>(`/v1/projects/${stage}`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
