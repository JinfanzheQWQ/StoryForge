import { afterEach, describe, expect, it, vi } from "vitest";
import { createContinuityRepairBatchTask, createContinuityRepairTask } from "./continuity";

describe("continuity repair APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("posts a scoped continuity repair task", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", status: "queued", task_id: "repair-1" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await createContinuityRepairTask({
      continuity_review_mode: "auto",
      project_id: "p1",
      segment_id: "seg-01",
      source_task_id: "t1",
      use_llm: true
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/continuity-repair",
      expect.objectContaining({
        body: JSON.stringify({
          continuity_review_mode: "auto",
          project_id: "p1",
          segment_id: "seg-01",
          source_task_id: "t1",
          use_llm: true
        }),
        method: "POST"
      })
    );
  });

  it("posts a batch continuity repair task with severity controls", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", status: "queued", task_id: "repair-batch-1" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    await createContinuityRepairBatchTask({
      continuity_review_mode: "auto",
      max_units_per_batch: 4,
      project_id: "p1",
      severity_threshold: "medium",
      source_task_id: "t1",
      use_llm: true
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/continuity-repair-batch",
      expect.objectContaining({
        body: JSON.stringify({
          continuity_review_mode: "auto",
          max_units_per_batch: 4,
          project_id: "p1",
          severity_threshold: "medium",
          source_task_id: "t1",
          use_llm: true
        }),
        method: "POST"
      })
    );
  });
});
