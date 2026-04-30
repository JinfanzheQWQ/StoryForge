import { requestJson } from "./client";
import type {
  CreateImageGenerationRequest,
  ImageGenerationCapabilities,
  ImageGenerationTaskResponse
} from "../types";

export function createImageGenerationTask(
  payload: CreateImageGenerationRequest
): Promise<ImageGenerationTaskResponse> {
  return requestJson<ImageGenerationTaskResponse>("/v1/images/generations", {
    body: JSON.stringify(payload),
    method: "POST"
  });
}

export function getImageGenerationCapabilities(): Promise<ImageGenerationCapabilities> {
  return requestJson<ImageGenerationCapabilities>("/v1/images/capabilities");
}

export function saveImageGenerationTask(taskId: string): Promise<ImageGenerationTaskResponse> {
  return requestJson<ImageGenerationTaskResponse>(`/v1/images/generations/${encodeURIComponent(taskId)}/save`, {
    method: "POST"
  });
}
