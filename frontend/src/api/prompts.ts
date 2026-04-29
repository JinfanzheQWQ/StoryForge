import { requestJson } from "./client";
import type {
  CharacterPromptUpdateResponse,
  SegmentPromptResetField,
  SegmentPromptUpdateRequest,
  SegmentPromptUpdateResponse
} from "../types";

export function updateCharacterPrompt(
  projectId: string,
  sourceTaskId: string,
  characterName: string,
  prompt: string
): Promise<CharacterPromptUpdateResponse> {
  return requestJson<CharacterPromptUpdateResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/character-prompts/${encodeURIComponent(sourceTaskId)}/${encodeURIComponent(characterName)}`,
    {
      method: "PUT",
      body: JSON.stringify({ prompt })
    }
  );
}

export function updateSegmentPrompts(
  projectId: string,
  sourceTaskId: string,
  segmentId: string,
  payload: SegmentPromptUpdateRequest
): Promise<SegmentPromptUpdateResponse> {
  return requestJson<SegmentPromptUpdateResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/segment-prompts/${encodeURIComponent(sourceTaskId)}/${encodeURIComponent(segmentId)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload)
    }
  );
}

export function resetSegmentPrompt(
  projectId: string,
  sourceTaskId: string,
  segmentId: string,
  field: SegmentPromptResetField
): Promise<SegmentPromptUpdateResponse> {
  return requestJson<SegmentPromptUpdateResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/segment-prompts/${encodeURIComponent(sourceTaskId)}/${encodeURIComponent(segmentId)}/reset`,
    {
      method: "POST",
      body: JSON.stringify({ field })
    }
  );
}
