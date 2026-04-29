export interface StorySourceChapter {
  number: number;
  title: string;
  summary: string;
  markdown: string;
}

export interface StorySourceResponse {
  project_id: string;
  source_task_id: string;
  story_title: string;
  story_source_revision?: string | null;
  chapters: StorySourceChapter[];
}

export interface UpdateStorySourceRequest {
  story_title: string;
  chapters: StorySourceChapter[];
}

export interface StoryBrief {
  title_hint: string;
  idea: string;
  genre: string;
  tone: string;
  target_audience: string;
  chapter_count: number;
  total_word_target: number;
  must_include: string[];
  style_keywords: string[];
}

export interface CreateNovelRequest {
  project_id: string | null;
  brief: StoryBrief;
  use_llm: boolean;
  llm_provider: string;
  llm_model: string;
  continuity_review_mode: "off" | "auto" | "on";
  seedream_watermark: boolean;
  seedance_watermark: boolean;
}
