import { describe, expect, it, vi } from "vitest";
import { getApiBaseUrl } from "./client";

describe("getApiBaseUrl", () => {
  it("returns the configured StoryForge API URL without trailing slash", () => {
    vi.stubEnv("VITE_STORYFORGE_API_BASE_URL", "http://127.0.0.1:8000/");
    expect(getApiBaseUrl()).toBe("http://127.0.0.1:8000");
    vi.unstubAllEnvs();
  });
});
