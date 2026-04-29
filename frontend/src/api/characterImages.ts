import { requestJson } from "./client";
import type { CharacterImageVersion, CharacterImageVersionSelectionResponse } from "../types";

export function selectCharacterImageVersion(
  projectId: string,
  sourceTaskId: string,
  characterName: string,
  version: CharacterImageVersion
): Promise<CharacterImageVersionSelectionResponse> {
  return requestJson<CharacterImageVersionSelectionResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/character-images/${encodeURIComponent(sourceTaskId)}/${encodeURIComponent(characterName)}/select`,
    {
      method: "POST",
      body: JSON.stringify({ version })
    }
  );
}
