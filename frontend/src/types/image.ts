import type { TaskStatus } from "./task";

export type ImageGenerationMode = "text_to_image" | "image_to_image";

export interface CreateImageGenerationRequest {
  mode: ImageGenerationMode;
  model?: string | null;
  prompt: string;
  reference_images?: string[];
  size?: string | null;
  aspect_ratio?: string | null;
  seedream_watermark?: boolean | null;
}

export interface ImageGenerationTaskResponse {
  project_id: string;
  task_id: string;
  status: TaskStatus;
}

export interface ImageSizeOption {
  label: string;
  value: string;
  aspect_ratios: string[];
}

export interface ImageModelCapability {
  label: string;
  value: string;
  size_options: ImageSizeOption[];
}

export interface ImageGenerationCapabilities {
  models: ImageModelCapability[];
}

export interface ImageGenerationResult {
  mode?: ImageGenerationMode;
  prompt?: string;
  reference_images?: string[];
  model?: string;
  size?: string;
  aspect_ratio?: string;
  image_url?: string;
  generated_url?: string;
  output_url?: string;
  output_path?: string;
  image_saved?: boolean;
  seedream_watermark?: boolean | null;
  gpt_image_request?: {
    endpoint?: string;
    model?: string;
    payload?: Record<string, unknown>;
    reference_bindings?: Array<Record<string, unknown>>;
  };
  seedream_request?: {
    endpoint?: string;
    model?: string;
    payload?: Record<string, unknown>;
    reference_bindings?: Array<Record<string, unknown>>;
  };
  request_info?: {
    endpoint?: string;
    model?: string;
    payload?: Record<string, unknown>;
    reference_bindings?: Array<Record<string, unknown>>;
  };
  note?: string;
}
