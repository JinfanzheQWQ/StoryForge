from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class StoryBriefInput(BaseModel):
    title_hint: str = Field(default="未命名故事")
    idea: str
    genre: str = Field(default="通用")
    tone: str = Field(default="电影感")
    target_audience: str = Field(default="大众读者")
    chapter_count: int = Field(default=8, ge=1)
    total_word_target: int = Field(default=20000, ge=300)
    must_include: list[str] = Field(default_factory=list)
    style_keywords: list[str] = Field(default_factory=list)


class CreateStoryTaskRequest(BaseModel):
    project_id: str | None = None
    brief: StoryBriefInput
    use_llm: bool = True
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] = "auto"
    seedream_watermark: bool | None = None
    seedance_watermark: bool | None = None


class CreateStageTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    use_llm: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] | None = None
    seedream_watermark: bool | None = None
    seedance_watermark: bool | None = None
    character_name: str | None = None
    segment_id: str | None = None
    scene_id: str | None = None
    master_only: bool = False
    merge_only: bool = False
    resume_from_progress: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "CreateStageTaskRequest":
        segment_id = str(self.segment_id or "").strip()
        scene_id = str(self.scene_id or "").strip()
        if segment_id and scene_id:
            raise ValueError("scene_id 不能与 segment_id 同时提交。")
        if self.merge_only and (segment_id or scene_id):
            raise ValueError("merge_only 不能与 segment_id 或 scene_id 同时提交。")
        if self.master_only and not scene_id:
            raise ValueError("master_only=true 时必须提供 scene_id。")
        if self.master_only and segment_id:
            raise ValueError("master_only=true 不能与 segment_id 同时提交。")
        if self.resume_from_progress and (segment_id or scene_id or self.master_only or self.merge_only):
            raise ValueError("resume_from_progress 目前只支持分段合同阶段，不能和局部媒体范围一起提交。")
        return self


class CreateContinuityRepairTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    segment_id: str | None = None
    scene_id: str | None = None
    use_llm: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] | None = None
    seedream_watermark: bool | None = None
    seedance_watermark: bool | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> "CreateContinuityRepairTaskRequest":
        segment_id = str(self.segment_id or "").strip()
        scene_id = str(self.scene_id or "").strip()
        if bool(segment_id) == bool(scene_id):
            raise ValueError("segment_id 与 scene_id 必须二选一。")
        return self


class CreateContinuityRepairBatchTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    use_llm: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] | None = None
    seedream_watermark: bool | None = None
    seedance_watermark: bool | None = None
    severity_threshold: Literal["high", "medium", "low"] = "medium"
    max_units_per_batch: int = Field(default=4, ge=1, le=12)


class StorySourceChapterInput(BaseModel):
    number: int
    title: str
    summary: str
    markdown: str


class StorySourceResponse(BaseModel):
    project_id: str
    source_task_id: str
    story_title: str
    story_source_revision: str | None = None
    chapters: list[StorySourceChapterInput] = Field(default_factory=list)


class UpdateStorySourceRequest(BaseModel):
    story_title: str
    chapters: list[StorySourceChapterInput] = Field(default_factory=list)


class JobAcceptedResponse(BaseModel):
    project_id: str
    task_id: str
    status: str


class CreateImageGenerationRequest(BaseModel):
    mode: Literal["text_to_image", "image_to_image"] = "text_to_image"
    model: str | None = Field(default=None, max_length=120)
    prompt: str = Field(min_length=1, max_length=20000)
    reference_images: list[str] = Field(default_factory=list, max_length=4)
    size: str | None = Field(default=None, max_length=32)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    seedream_watermark: bool | None = None

    @model_validator(mode="after")
    def validate_reference_images(self) -> "CreateImageGenerationRequest":
        self.prompt = self.prompt.strip()
        if not self.prompt:
            raise ValueError("prompt 不能为空。")
        if self.model is not None:
            self.model = self.model.strip()
        if self.size is not None:
            self.size = self.size.strip()
        if self.aspect_ratio is not None:
            self.aspect_ratio = self.aspect_ratio.strip()
        normalized: list[str] = []
        for raw_url in self.reference_images:
            url = str(raw_url or "").strip()
            if url and url not in normalized:
                normalized.append(url)
        self.reference_images = normalized
        if self.mode == "image_to_image" and not self.reference_images:
            raise ValueError("图生图必须提供至少一张参考图 URL。")
        return self


class UpdateSegmentPromptRequest(BaseModel):
    scene_master_frame_prompt: str | None = None
    video_prompt: str | None = None


class ResetSegmentPromptRequest(BaseModel):
    field: Literal["scene_master_frame_prompt", "video_prompt"]


class SegmentPromptUpdateResponse(BaseModel):
    project_id: str
    source_task_id: str
    segment_id: str
    updated_fields: list[str] = Field(default_factory=list)
    reset_field: str = ""
    prompt: str = ""


class UpdateCharacterPromptRequest(BaseModel):
    prompt: str


class CharacterPromptUpdateResponse(BaseModel):
    project_id: str
    source_task_id: str
    character_name: str
    updated_fields: list[str] = Field(default_factory=list)
    prompt: str = ""


class SelectCharacterImageVersionRequest(BaseModel):
    version: Literal["current", "candidate"]


class CharacterImageVersionSelectionResponse(BaseModel):
    project_id: str
    source_task_id: str
    character_name: str
    selected_version: Literal["current", "candidate"]
    current_url: str = ""
    candidate_url: str = ""


class ProjectDeletedResponse(BaseModel):
    project_id: str
    deleted: bool
    deleted_task_count: int
    deleted_output_count: int
    deleted_output_paths: list[str] = Field(default_factory=list)
    skipped_output_paths: list[str] = Field(default_factory=list)


class ArtifactItem(BaseModel):
    name: str
    path: str
    url: str | None = None
    kind: str


class CharacterArtifactItem(ArtifactItem):
    character_name: str = ""
    prompt: str = ""
    consistency_notes: str = ""
    provider: str = ""
    status: str = ""
    image_kind: str = ""
    candidate_url: str | None = None
    candidate_path: str = ""
    character_request: SubmittedRequestResponse | None = None
    error: str = ""


class SceneArtifactResponse(BaseModel):
    scene_id: str
    chapter_number: int = 0
    title: str = ""
    summary: str = ""
    scene_anchor: str = ""
    scene_bible: dict[str, Any] = Field(default_factory=dict)
    scene_transition_contract: dict[str, Any] = Field(default_factory=dict)
    involved_characters: list[str] = Field(default_factory=list)
    covered_event_ids: list[str] = Field(default_factory=list)
    covered_event_summaries: list[str] = Field(default_factory=list)
    segment_count: int = 0
    scene_master_frame_status: str = ""
    scene_master_frame_error: str = ""
    scene_master_frame_prompt: str = ""
    scene_master_frame: ArtifactItem | None = None


class PromptReferenceBindingResponse(BaseModel):
    label: str
    kind: str
    description: str = ""
    url: str = ""


class SubmittedRequestResponse(BaseModel):
    provider: str = ""
    endpoint: str = ""
    variant: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    reference_bindings: list[PromptReferenceBindingResponse] = Field(default_factory=list)


class PlannedSegmentArtifactResponse(BaseModel):
    segment_id: str
    scene_id: str = ""
    scene_title: str = ""
    scene_summary: str = ""
    scene_anchor: str = ""
    scene_bible: dict[str, Any] = Field(default_factory=dict)
    scene_transition_contract: dict[str, Any] = Field(default_factory=dict)
    scene_spatial_continuity_mode: str = "uncertain"
    scene_master_frame_status: str = ""
    scene_master_frame_error: str = ""
    covered_event_ids: list[str] = Field(default_factory=list)
    covered_event_summaries: list[str] = Field(default_factory=list)
    title: str
    summary: str = ""
    chapter_number: int
    duration_seconds: int | None = None
    scene_master_frame: ArtifactItem | None = None
    rendered_clip: ArtifactItem | None = None
    scene_master_frame_prompt: str = ""
    video_prompt: str = ""
    submitted_video_prompt: str = ""
    seedance_motion_prompt: str = ""
    motion_plan: dict[str, str] = Field(default_factory=dict)
    motion_contract: dict[str, Any] = Field(default_factory=dict)
    first_frame_url: str = ""
    last_frame_url: str = ""
    previous_clip_segment_id: str = ""
    previous_clip_video_url: str = ""
    character_references: list[ArtifactItem] = Field(default_factory=list)
    scene_master_reference_images: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    submitted_prompt_variant: str = ""
    submitted_reference_bindings: list[PromptReferenceBindingResponse] = Field(default_factory=list)
    scene_master_frame_request: SubmittedRequestResponse | None = None
    video_request: SubmittedRequestResponse | None = None
    scene_ready: bool = False
    video_ready: bool = False


class ContinuityIssueSummaryResponse(BaseModel):
    severity: str
    scope: str
    code: str
    message: str
    scene_id: str = ""
    segment_id: str = ""
    recommended_action: str = ""
    recommended_action_label: str = ""


class ContinuityIssueDetailResponse(ContinuityIssueSummaryResponse):
    details: dict[str, Any] = Field(default_factory=dict)


class ContinuityIssueGroupResponse(BaseModel):
    scope: str
    scene_id: str = ""
    segment_id: str = ""
    issue_count: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    recommended_actions: list[str] = Field(default_factory=list)
    issues: list[ContinuityIssueDetailResponse] = Field(default_factory=list)


class ContinuitySummaryResponse(BaseModel):
    status: str
    report_version: str = ""
    generated_at: str | None = None
    review_mode_requested: str = "auto"
    review_mode_effective: str = "off"
    v2_review_status: str = "disabled"
    v2_issue_count: int = 0
    v2_note: str = ""
    issue_count: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    scene_issue_count: int = 0
    segment_issue_count: int = 0
    recommended_actions: list[str] = Field(default_factory=list)
    top_issues: list[ContinuityIssueSummaryResponse] = Field(default_factory=list)


class TaskArtifactsResponse(BaseModel):
    task_id: str
    available: bool
    note: str = ""
    story_title: str | None = None
    output_dir: str | None = None
    documents: list[ArtifactItem] = Field(default_factory=list)
    character_images: list[CharacterArtifactItem] = Field(default_factory=list)
    scenes: list[SceneArtifactResponse] = Field(default_factory=list)
    scene_frames: list[ArtifactItem] = Field(default_factory=list)
    rendered_clips: list[ArtifactItem] = Field(default_factory=list)
    full_story: ArtifactItem | None = None
    planned_segments: list[PlannedSegmentArtifactResponse] = Field(default_factory=list)
    continuity_report: ArtifactItem | None = None
    continuity_summary: ContinuitySummaryResponse | None = None
    continuity_scene_groups: list[ContinuityIssueGroupResponse] = Field(default_factory=list)
    continuity_segment_groups: list[ContinuityIssueGroupResponse] = Field(default_factory=list)


class TaskResponse(BaseModel):
    task_id: str
    project_id: str
    task_type: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ProjectSummaryResponse(BaseModel):
    project_id: str
    title_hint: str
    product_type: str = "novel_to_video"
    story_title: str | None = None
    created_at: str
    updated_at: str
    latest_task_id: str | None = None
    latest_status: str | None = None
    latest_output_dir: str | None = None
    run_count: int
    completed_run_count: int
    failed_run_count: int
    full_story_count: int


class ProjectDetailResponse(ProjectSummaryResponse):
    brief: StoryBriefInput
    tasks: list[TaskResponse] = Field(default_factory=list)
