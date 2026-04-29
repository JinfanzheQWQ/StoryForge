import { afterEach, describe, expect, it, vi } from "vitest";
import { deleteProject, getProject, listProjects } from "./projects";

describe("project APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("lists StoryForge projects", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => [{ project_id: "p1", title_hint: "项目" }],
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await listProjects();

    expect(response).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith("http://storyforge.test/v1/projects", expect.objectContaining({}));
  });

  it("fetches one project detail by id", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "p1", story_title: "故事", tasks: [] }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await getProject("p1");

    expect(response.story_title).toBe("故事");
    expect(fetchMock).toHaveBeenCalledWith("http://storyforge.test/v1/projects/p1", expect.objectContaining({}));
  });

  it("deletes one project through the dangerous project endpoint", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        deleted: true,
        deleted_output_count: 1,
        deleted_output_paths: ["outputs/run"],
        deleted_task_count: 2,
        project_id: "p1",
        skipped_output_paths: []
      }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await deleteProject("p1");

    expect(response.deleted).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/projects/p1",
      expect.objectContaining({ method: "DELETE" })
    );
  });
});
