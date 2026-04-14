from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class CreateStoryTaskRequest(BaseModel):
    project_id: str | None = None
    brief: StoryBriefInput
    use_llm: bool = True


class CreateStageTaskRequest(BaseModel):
    project_id: str
    source_task_id: str
    use_llm: bool | None = None


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


class UiBootstrapResponse(BaseModel):
    default_brief: StoryBriefInput
    use_llm: bool
    submit_seedance: bool
    llm_model: str
    seedream_model: str
    seedance_model: str


class ArtifactItem(BaseModel):
    name: str
    path: str
    url: str | None = None
    kind: str


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
