import { afterEach, describe, expect, it, vi } from "vitest";
import { getTask } from "./tasks";

describe("task APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("fetches one task detail by id", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", status: "completed", task_id: "t1" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await getTask("t1");

    expect(response.status).toBe("completed");
    expect(fetchMock).toHaveBeenCalledWith("http://storyforge.test/v1/tasks/t1", expect.objectContaining({}));
  });
});
