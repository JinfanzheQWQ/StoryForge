import { afterEach, describe, expect, it, vi } from "vitest";
import { resetSegmentPrompt, updateCharacterPrompt, updateSegmentPrompts } from "./prompts";

describe("prompt update APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("updates one character prompt with an encoded character path", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", source_task_id: "t1", character_name: "苏晚", updated_fields: ["prompt"] }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await updateCharacterPrompt("p1", "t1", "苏晚", "角色 prompt");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1/character-prompts/t1/%E8%8B%8F%E6%99%9A",
      expect.objectContaining({
        body: JSON.stringify({ prompt: "角色 prompt" }),
        method: "PUT"
      })
    );
  });

  it("updates one segment prompt without posting unrelated prompt fields", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", source_task_id: "t1", segment_id: "seg-01", updated_fields: ["video_prompt"] }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await updateSegmentPrompts("p1", "t1", "seg-01", { video_prompt: "视频 prompt" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1/segment-prompts/t1/seg-01",
      expect.objectContaining({
        body: JSON.stringify({ video_prompt: "视频 prompt" }),
        method: "PUT"
      })
    );
  });

  it("resets one segment prompt field through the reset endpoint", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        project_id: "p1",
        prompt: "默认 prompt",
        reset_field: "video_prompt",
        segment_id: "seg-01",
        source_task_id: "t1",
        updated_fields: ["video_prompt"]
      }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await resetSegmentPrompt("p1", "t1", "seg-01", "video_prompt");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1/segment-prompts/t1/seg-01/reset",
      expect.objectContaining({
        body: JSON.stringify({ field: "video_prompt" }),
        method: "POST"
      })
    );
  });
});
