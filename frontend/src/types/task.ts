export type TaskStatus = "queued" | "running" | "completed" | "failed" | "canceled" | string;

export interface TaskRecord {
  task_id: string;
  project_id: string;
  task_type?: string;
  stage?: string;
  status: TaskStatus;
  payload?: Record<string, unknown> | null;
  error?: string | null;
  result?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface StageTaskResponse {
  project_id: string;
  task_id: string;
  status: TaskStatus;
}

export type StageTaskKind = "scene-structure" | "segment-contracts" | "characters" | "scenes" | "videos";

export interface CreateStageTaskRequest {
  project_id: string;
  source_task_id: string;
  use_llm?: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  continuity_review_mode?: "off" | "auto" | "on" | null;
  seedream_watermark?: boolean | null;
  seedance_watermark?: boolean | null;
  character_name?: string | null;
  segment_id?: string | null;
  scene_id?: string | null;
  master_only?: boolean;
  merge_only?: boolean;
  resume_from_progress?: boolean;
}

export interface CreateContinuityRepairTaskRequest {
  project_id: string;
  source_task_id: string;
  segment_id?: string | null;
  scene_id?: string | null;
  use_llm?: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  continuity_review_mode?: "off" | "auto" | "on" | null;
  seedream_watermark?: boolean | null;
  seedance_watermark?: boolean | null;
}

export interface CreateContinuityRepairBatchTaskRequest {
  project_id: string;
  source_task_id: string;
  use_llm?: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  continuity_review_mode?: "off" | "auto" | "on" | null;
  seedream_watermark?: boolean | null;
  seedance_watermark?: boolean | null;
  severity_threshold?: "high" | "medium" | "low";
  max_units_per_batch?: number;
}
