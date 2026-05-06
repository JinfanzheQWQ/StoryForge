import { describe, expect, it } from "vitest";
import { resolveStoryboardSelection } from "./creatorStoryboardOptions";

describe("creatorStoryboardOptions", () => {
  it("keeps valid GPT Image 2 4K ratios", () => {
    expect(
      resolveStoryboardSelection({
        aspectRatio: "9:16",
        model: "gpt-image-2",
        size: "4K"
      })
    ).toEqual({
      aspectRatio: "9:16",
      model: "gpt-image-2",
      size: "4K"
    });
  });

  it("falls back from invalid GPT Image 2 4K square ratio to 16:9", () => {
    expect(
      resolveStoryboardSelection({
        aspectRatio: "1:1",
        model: "gpt-image-2",
        size: "4K"
      })
    ).toEqual({
      aspectRatio: "16:9",
      model: "gpt-image-2",
      size: "4K"
    });
  });
});
