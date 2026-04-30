import { describe, expect, it, vi } from "vitest";
import { getApiBaseUrl, resolveApiAssetUrl } from "./client";

describe("getApiBaseUrl", () => {
  it("returns the configured StoryForge API URL without trailing slash", () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://127.0.0.1:8000/");
    expect(getApiBaseUrl()).toBe("http://127.0.0.1:8000");
    vi.unstubAllEnvs();
  });

  it("resolves backend output assets against the API base URL", () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://storyforge.test/");
    expect(resolveApiAssetUrl("/outputs/images/task/generated.png?v=1")).toBe(
      "http://storyforge.test/outputs/images/task/generated.png?v=1"
    );
    expect(resolveApiAssetUrl("https://cdn.example.com/generated.png")).toBe("https://cdn.example.com/generated.png");
    vi.unstubAllEnvs();
  });
});
