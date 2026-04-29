import { requestJson } from "./client";
import type {
  CreateContinuityRepairBatchTaskRequest,
  CreateContinuityRepairTaskRequest,
  StageTaskResponse
} from "../types";

export function createContinuityRepairTask(
  payload: CreateContinuityRepairTaskRequest
): Promise<StageTaskResponse> {
  return requestJson<StageTaskResponse>("/v1/projects/continuity-repair", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createContinuityRepairBatchTask(
  payload: CreateContinuityRepairBatchTaskRequest
): Promise<StageTaskResponse> {
  return requestJson<StageTaskResponse>("/v1/projects/continuity-repair-batch", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
