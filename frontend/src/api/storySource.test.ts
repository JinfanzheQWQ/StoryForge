import { afterEach, describe, expect, it, vi } from "vitest";
import { getStorySource, updateStorySource } from "./storySource";

describe("story source APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("fetches editable story source from the source task", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", source_task_id: "t1", story_title: "故事", chapters: [] }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await getStorySource("p1", "t1");

    expect(response.story_title).toBe("故事");
    expect(fetchMock).toHaveBeenCalledWith("http://storyforge.test/v1/projects/p1/story-source/t1", expect.objectContaining({}));
  });

  it("updates editable story source chapters", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const payload = {
      story_title: "新故事",
      chapters: [{ number: 1, title: "第一章", summary: "摘要", markdown: "正文" }]
    };
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", source_task_id: "t1", story_title: "新故事", chapters: payload.chapters }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await updateStorySource("p1", "t1", payload);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1/story-source/t1",
      expect.objectContaining({
        body: JSON.stringify(payload),
        method: "PUT"
      })
    );
  });
});
