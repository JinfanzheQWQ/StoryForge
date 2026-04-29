import { afterEach, describe, expect, it, vi } from "vitest";
import { selectCharacterImageVersion } from "./characterImages";

describe("character image APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("selects a candidate character image with an encoded character path", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        candidate_url: "",
        character_name: "苏晚",
        current_url: "https://cdn/current.png",
        project_id: "p1",
        selected_version: "candidate",
        source_task_id: "t1"
      }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await selectCharacterImageVersion("p1", "t1", "苏晚", "candidate");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1/character-images/t1/%E8%8B%8F%E6%99%9A/select",
      expect.objectContaining({
        body: JSON.stringify({ version: "candidate" }),
        method: "POST"
      })
    );
  });
});
