import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createImageGenerationTask,
  getImageGenerationCapabilities,
  saveImageGenerationTask
} from "./images";

describe("image generation APIs", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("posts GPT Image 2 generation tasks", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "image-project", task_id: "task-1", status: "queued" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await createImageGenerationTask({
      mode: "image_to_image",
      model: "gpt-image-2",
      prompt: "保持主体姿态，改成清新科技感商业插画",
      reference_images: ["https://example.com/ref.png"],
      size: "2K",
      aspect_ratio: "16:9"
    });

    expect(response.task_id).toBe("task-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/images/generations",
      expect.objectContaining({
        body: JSON.stringify({
          mode: "image_to_image",
          model: "gpt-image-2",
          prompt: "保持主体姿态，改成清新科技感商业插画",
          reference_images: ["https://example.com/ref.png"],
          size: "2K",
          aspect_ratio: "16:9"
        }),
        method: "POST"
      })
    );
  });

  it("posts Seedream generation tasks with watermark", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "image-project", task_id: "task-seedream", status: "queued" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await createImageGenerationTask({
      mode: "text_to_image",
      model: "doubao-seedream-4-5-251128",
      prompt: "薄荷色未来图书馆",
      reference_images: [],
      size: "2K",
      aspect_ratio: "9:16",
      seedream_watermark: true
    });

    expect(response.task_id).toBe("task-seedream");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/images/generations",
      expect.objectContaining({
        body: JSON.stringify({
          mode: "text_to_image",
          model: "doubao-seedream-4-5-251128",
          prompt: "薄荷色未来图书馆",
          reference_images: [],
          size: "2K",
          aspect_ratio: "9:16",
          seedream_watermark: true
        }),
        method: "POST"
      })
    );
  });

  it("loads image generation capabilities", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ models: [{ label: "GPT Image 2", value: "gpt-image-2", size_options: [] }] }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const capabilities = await getImageGenerationCapabilities();

    expect(capabilities.models[0]?.value).toBe("gpt-image-2");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/images/capabilities",
      expect.any(Object)
    );
  });

  it("saves generated images into project gallery", async () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test");
    const fetchMock = vi.fn().mockResolvedValue({
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ project_id: "image-project", task_id: "task-1", status: "completed" }),
      ok: true
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await saveImageGenerationTask("task-1");

    expect(response.project_id).toBe("image-project");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://storyforge.test/v1/images/generations/task-1/save",
      expect.objectContaining({
        method: "POST"
      })
    );
  });
});
