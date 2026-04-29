export interface SegmentPromptUpdateRequest {
  scene_master_frame_prompt?: string | null;
  video_prompt?: string | null;
}

export type SegmentPromptResetField = "scene_master_frame_prompt" | "video_prompt";

export interface ResetSegmentPromptRequest {
  field: SegmentPromptResetField;
}

export interface SegmentPromptUpdateResponse {
  project_id: string;
  source_task_id: string;
  segment_id: string;
  updated_fields: string[];
  reset_field?: string;
  prompt?: string;
}

export interface CharacterPromptUpdateResponse {
  project_id: string;
  source_task_id: string;
  character_name: string;
  updated_fields: string[];
  prompt?: string;
}

export type CharacterImageVersion = "current" | "candidate";

export interface CharacterImageVersionSelectionResponse {
  project_id: string;
  source_task_id: string;
  character_name: string;
  selected_version: CharacterImageVersion;
  current_url: string;
  candidate_url: string;
}

export interface ArtifactItem {
  name: string;
  path?: string;
  url?: string;
  kind?: string;
  size?: number;
  modified_at?: string;
  [key: string]: unknown;
}

export interface CharacterArtifactItem extends ArtifactItem {
  character_id?: string;
  character_name?: string;
  prompt?: string;
  status?: string;
  candidate_url?: string | null;
  candidate_path?: string;
  character_request?: SubmittedRequest | null;
  consistency_notes?: string;
  error?: string;
  image_kind?: string;
  provider?: string;
}

export interface SceneArtifactItem {
  scene_id: string;
  chapter_number?: number;
  title?: string;
  summary?: string;
  scene_anchor?: string;
  scene_bible?: Record<string, unknown>;
  scene_transition_contract?: Record<string, unknown>;
  involved_characters?: string[];
  covered_event_ids?: string[];
  covered_event_summaries?: string[];
  segment_count?: number;
  scene_master_frame_status?: string;
  scene_master_frame_error?: string;
  scene_master_frame_prompt?: string;
  scene_master_frame?: ArtifactItem | null;
}

export interface SubmittedReferenceBinding {
  label: string;
  kind?: string;
  description?: string;
  url?: string;
  path?: string;
}

export interface SubmittedRequest {
  provider?: string;
  endpoint?: string;
  variant?: string;
  payload?: Record<string, unknown>;
  reference_bindings?: SubmittedReferenceBinding[];
}

export interface ContinuityIssueDetail {
  code?: string;
  severity?: "high" | "medium" | "low" | string;
  message?: string;
  segment_id?: string;
  scene_id?: string;
  [key: string]: unknown;
}

export interface ContinuityIssueGroup {
  id?: string;
  key?: string;
  title?: string;
  scope?: string;
  severity?: "high" | "medium" | "low" | string;
  segment_id?: string;
  scene_id?: string;
  issues?: ContinuityIssueDetail[];
  [key: string]: unknown;
}

export interface ContinuitySummary {
  total_issues?: number;
  high?: number;
  medium?: number;
  low?: number;
  status?: string;
  [key: string]: unknown;
}

export interface PlannedSegmentArtifact {
  segment_id: string;
  scene_id?: string;
  scene_title?: string;
  scene_summary?: string;
  title: string;
  summary?: string;
  chapter_number: number;
  duration_seconds?: number | null;
  scene_master_frame?: ArtifactItem | null;
  rendered_clip?: ArtifactItem | null;
  scene_master_frame_prompt?: string;
  video_prompt?: string;
  submitted_video_prompt?: string;
  seedance_motion_prompt?: string;
  motion_plan?: Record<string, string>;
  first_frame_url?: string;
  last_frame_url?: string;
  previous_clip_segment_id?: string;
  previous_clip_video_url?: string;
  character_references?: ArtifactItem[];
  diagnostics?: Record<string, unknown>;
  submitted_reference_bindings?: SubmittedReferenceBinding[];
  scene_master_frame_request?: SubmittedRequest | null;
  video_request?: SubmittedRequest | null;
  scene_ready?: boolean;
  video_ready?: boolean;
}

export interface ArtifactBundle {
  task_id?: string;
  available?: boolean;
  note?: string;
  story_title?: string | null;
  output_dir?: string | null;
  documents?: ArtifactItem[];
  character_images?: CharacterArtifactItem[];
  scenes?: SceneArtifactItem[];
  scene_frames?: ArtifactItem[];
  rendered_clips?: ArtifactItem[];
  planned_segments?: PlannedSegmentArtifact[];
  continuity_report?: ArtifactItem | null;
  story_source?: unknown;
  full_story?: ArtifactItem | null;
  continuity_summary?: ContinuitySummary | null;
  continuity_scene_groups?: ContinuityIssueGroup[];
  continuity_segment_groups?: ContinuityIssueGroup[];
  [key: string]: unknown;
}
