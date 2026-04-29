import type { TaskRecord } from "./task";

export interface ProjectSummary {
  project_id: string;
  title_hint?: string;
  story_title?: string | null;
  latest_task_id?: string | null;
  last_output_dir?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectDetail extends ProjectSummary {
  brief?: Record<string, unknown>;
  tasks?: TaskRecord[];
}

export interface ProjectDeletedResponse {
  project_id: string;
  deleted: boolean;
  deleted_task_count: number;
  deleted_output_count: number;
  deleted_output_paths: string[];
  skipped_output_paths: string[];
}
