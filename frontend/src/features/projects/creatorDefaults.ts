import type { CreateNovelRequest, StoryBrief } from "../../types";

export const initialBrief: StoryBrief = {
  title_hint: "大学表白短片",
  idea: "一个内向男生在傍晚花园里向喜欢的女生表达心意。",
  genre: "青春爱情",
  tone: "清新、温柔、电影感",
  target_audience: "年轻观众",
  chapter_count: 1,
  total_word_target: 1800,
  must_include: ["傍晚花园", "误以为被叫", "最终表白"],
  style_keywords: ["大学", "青春", "小清新", "电影感"],
  video_mode: "grid_storyboard",
  image_model: "doubao-seedream-4-5-251128",
  image_size: "2K",
  image_aspect_ratio: "16:9",
  storyboard_image_model: "doubao-seedream-4-5-251128",
  storyboard_size: "2K",
  storyboard_aspect_ratio: "16:9"
};

export function createNovelRequest(brief: StoryBrief): CreateNovelRequest {
  return {
    project_id: null,
    brief,
    use_llm: true,
    llm_provider: "deepseek",
    llm_model: "deepseek-chat",
    continuity_review_mode: "auto",
    seedream_watermark: false,
    seedance_watermark: false
  };
}

export function parseCommaSeparatedList(value: string) {
  return value
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
