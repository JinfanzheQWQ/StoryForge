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


class BuildProjectRequest(BaseModel):
    project_id: str | None = None
    brief: StoryBriefInput
    use_llm: bool = True
    submit_seedance: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] = "auto"


class CreateStoryTaskRequest(BaseModel):
    project_id: str | None = None
    brief: StoryBriefInput
    use_llm: bool = True
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] = "auto"


class CreateStageTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    use_llm: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] | None = None
    segment_id: str | None = None
    scene_id: str | None = None
    master_only: bool = False
    merge_only: bool = False

    @model_validator(mode="after")
    def validate_scope(self) -> "CreateStageTaskRequest":
        segment_id = str(self.segment_id or "").strip()
        scene_id = str(self.scene_id or "").strip()
        if segment_id and scene_id:
            raise ValueError("scene_id 不能与 segment_id 同时提交。")
        if self.master_only and not scene_id:
            raise ValueError("master_only=true 时必须提供 scene_id。")
        if self.master_only and segment_id:
            raise ValueError("master_only=true 不能与 segment_id 同时提交。")
        return self


class CreateContinuityRepairTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    segment_id: str
    use_llm: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    continuity_review_mode: Literal["off", "auto", "on"] | None = None

    @model_validator(mode="after")
    def validate_segment_id(self) -> "CreateContinuityRepairTaskRequest":
        if not str(self.segment_id or "").strip():
            raise ValueError("segment_id 不能为空。")
        return self


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


class ProjectDeletedResponse(BaseModel):
    project_id: str
    deleted: bool
    deleted_task_count: int
    deleted_output_count: int
    deleted_output_paths: list[str] = Field(default_factory=list)
    skipped_output_paths: list[str] = Field(default_factory=list)


class UiBootstrapResponse(BaseModel):
    default_brief: StoryBriefInput
    use_llm: bool
    submit_seedance: bool
    llm_provider: str
    llm_model: str
    continuity_review_mode: Literal["off", "auto", "on"] = "auto"
    available_llm_options: list[dict[str, str]] = Field(default_factory=list)
    seedream_model: str
    seedance_model: str


class ArtifactItem(BaseModel):
    name: str
    path: str
    url: str | None = None
    kind: str


class PlannedSegmentArtifactResponse(BaseModel):
    segment_id: str
    scene_id: str = ""
    scene_title: str = ""
    scene_summary: str = ""
    title: str
    summary: str = ""
    chapter_number: int
    duration_seconds: int | None = None
    requires_mid_frame: bool = False
    scene_master_frame: ArtifactItem | None = None
    start_frame: ArtifactItem | None = None
    mid_frame: ArtifactItem | None = None
    end_frame: ArtifactItem | None = None
    rendered_clip: ArtifactItem | None = None
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
    character_images: list[ArtifactItem] = Field(default_factory=list)
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
