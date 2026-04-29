import { afterEach, describe, expect, it, vi } from "vitest";
import { createNovelTask, createStageTask } from "./stageTasks";

describe("stage task APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("posts novel tasks to the StoryForge novel endpoint", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", task_id: "t1", status: "queued" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await createNovelTask({
      project_id: null,
      brief: {
        title_hint: "项目",
        idea: "创意",
        genre: "青春",
        tone: "清新",
        target_audience: "年轻观众",
        chapter_count: 1,
        total_word_target: 1200,
        must_include: [],
        style_keywords: []
      },
      use_llm: true,
      llm_provider: "deepseek",
      llm_model: "deepseek-chat",
      continuity_review_mode: "auto",
      seedream_watermark: false,
      seedance_watermark: false
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/novel",
      expect.objectContaining({
        method: "POST"
      })
    );
  });

  it("posts stage tasks to the StoryForge project stage endpoint", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", task_id: "t2", status: "queued" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await createStageTask("videos", {
      project_id: "p1",
      source_task_id: "t1",
      segment_id: "seg-01"
    });

    expect(response.task_id).toBe("t2");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/videos",
      expect.objectContaining({
        body: JSON.stringify({
          project_id: "p1",
          source_task_id: "t1",
          segment_id: "seg-01"
        }),
        method: "POST"
      })
    );
  });

  it("posts single character regeneration tasks with character_name", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", task_id: "t3", status: "queued" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await createStageTask("characters", {
      character_name: "苏晚",
      project_id: "p1",
      source_task_id: "t1"
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/characters",
      expect.objectContaining({
        body: JSON.stringify({
          character_name: "苏晚",
          project_id: "p1",
          source_task_id: "t1"
        }),
        method: "POST"
      })
    );
  });
});
