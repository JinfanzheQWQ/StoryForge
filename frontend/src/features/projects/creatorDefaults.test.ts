import { describe, expect, it } from "vitest";
import { createNovelRequest, initialBrief, parseCommaSeparatedList } from "./creatorDefaults";

describe("creatorDefaults", () => {
  it("parses Chinese and English comma separated lists", () => {
    expect(parseCommaSeparatedList("傍晚花园， 误以为被叫,最终表白,, ")).toEqual(["傍晚花园", "误以为被叫", "最终表白"]);
  });

  it("creates the expected default novel task request", () => {
    const request = createNovelRequest(initialBrief);

    expect(request).toMatchObject({
      brief: initialBrief,
      continuity_review_mode: "auto",
      llm_model: "deepseek-chat",
      llm_provider: "deepseek",
      project_id: null,
      seedance_watermark: false,
      seedream_watermark: false,
      use_llm: true
    });
  });
});
