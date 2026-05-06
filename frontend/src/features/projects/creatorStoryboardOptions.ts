import type { StoryBrief } from "../../types";

export type StoryboardSizeOption = {
  label: string;
  value: string;
  aspectRatios: string[];
};

export type StoryboardModelOption = {
  label: string;
  value: StoryBrief["storyboard_image_model"];
  sizes: StoryboardSizeOption[];
};

export const STORYBOARD_MODEL_OPTIONS: StoryboardModelOption[] = [
  {
    label: "Seedream 4.5",
    value: "doubao-seedream-4-5-251128",
    sizes: [
      { label: "2K", value: "2K", aspectRatios: ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"] },
      { label: "4K", value: "4K", aspectRatios: ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"] }
    ]
  },
  {
    label: "GPT Image 2",
    value: "gpt-image-2",
    sizes: [
      { label: "1K", value: "1K", aspectRatios: ["auto", "1:1", "9:16", "16:9", "4:3", "3:4"] },
      { label: "2K", value: "2K", aspectRatios: ["1:1", "9:16", "16:9", "4:3", "3:4"] },
      { label: "4K", value: "4K", aspectRatios: ["9:16", "16:9", "4:3", "3:4"] }
    ]
  }
];

export function getStoryboardModelOption(model: string) {
  return STORYBOARD_MODEL_OPTIONS.find((item) => item.value === model) || STORYBOARD_MODEL_OPTIONS[0];
}

export function getStoryboardSizeOption(model: string, size: string) {
  const modelOption = getStoryboardModelOption(model);
  return modelOption.sizes.find((item) => item.value === size) || modelOption.sizes[0];
}

export function resolveStoryboardSelection({
  aspectRatio,
  model,
  size
}: {
  aspectRatio: string;
  model: string;
  size: string;
}) {
  const modelOption = getStoryboardModelOption(model);
  const sizeOption = modelOption.sizes.find((item) => item.value === size) || modelOption.sizes[0];
  const resolvedAspectRatio = sizeOption.aspectRatios.includes(aspectRatio)
    ? aspectRatio
    : sizeOption.aspectRatios.includes("16:9")
      ? "16:9"
      : sizeOption.aspectRatios[0];
  return {
    aspectRatio: resolvedAspectRatio,
    model: modelOption.value,
    size: sizeOption.value
  };
}
