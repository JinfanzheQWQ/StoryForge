from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from storyforge.domains.video.contracts import (
    SeedanceManifest,
    StoryboardGridTask,
    StoryMemoryPackage,
    VideoProjectPackage,
)
from storyforge.domains.video.schemas import VideoSegmentPlanSchema
from storyforge.integrations.seedance import SeedanceExecutionReport
from storyforge.integrations.seedream import SeedreamExecutionReport


@dataclass(slots=True)
class SegmentContractChunkProgress:
    chunk_id: str
    title: str
    summary: str
    order_index: int
    must_cover: list[str] = field(default_factory=list)
    transition_goal: str = ""
    expected_segment_count: int = 1
    status: str = "pending"
    segment_count: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "SegmentContractChunkProgress":
        must_cover = raw.get("must_cover", [])
        return cls(
            chunk_id=str(raw.get("chunk_id", "") or ""),
            title=str(raw.get("title", "") or ""),
            summary=str(raw.get("summary", "") or ""),
            order_index=int(raw.get("order_index", 0) or 0),
            must_cover=[
                str(item).strip()
                for item in must_cover
                if str(item).strip()
            ]
            if isinstance(must_cover, list)
            else [],
            transition_goal=str(raw.get("transition_goal", "") or ""),
            expected_segment_count=int(raw.get("expected_segment_count", 1) or 1),
            status=str(raw.get("status", "pending") or "pending"),
            segment_count=int(raw.get("segment_count", 0) or 0),
            started_at=str(raw.get("started_at")) if raw.get("started_at") else None,
            finished_at=str(raw.get("finished_at")) if raw.get("finished_at") else None,
            error=str(raw.get("error", "") or ""),
        )


@dataclass(slots=True)
class SegmentContractSceneProgress:
    scene_id: str
    scene_title: str
    chapter_number: int
    status: str = "pending"
    chunk_count: int = 0
    completed_chunk_count: int = 0
    segment_count: int = 0
    running_chunk_id: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    failed_chunk_id: str = ""
    error: str = ""
    chunks: list[SegmentContractChunkProgress] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "SegmentContractSceneProgress":
        return cls(
            scene_id=str(raw.get("scene_id", "") or ""),
            scene_title=str(raw.get("scene_title", "") or ""),
            chapter_number=int(raw.get("chapter_number", 0) or 0),
            status=str(raw.get("status", "pending") or "pending"),
            chunk_count=int(raw.get("chunk_count", 0) or 0),
            completed_chunk_count=int(raw.get("completed_chunk_count", 0) or 0),
            segment_count=int(raw.get("segment_count", 0) or 0),
            running_chunk_id=str(raw.get("running_chunk_id", "") or ""),
            started_at=str(raw.get("started_at")) if raw.get("started_at") else None,
            finished_at=str(raw.get("finished_at")) if raw.get("finished_at") else None,
            failed_chunk_id=str(raw.get("failed_chunk_id", "") or ""),
            error=str(raw.get("error", "") or ""),
            chunks=[
                SegmentContractChunkProgress.from_dict(item)
                for item in raw.get("chunks", [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class SegmentContractChapterProgress:
    chapter_number: int
    chapter_title: str
    status: str = "pending"
    scene_count: int = 0
    completed_scene_count: int = 0
    segment_count: int = 0
    running_scene_id: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    failed_scene_id: str = ""
    error: str = ""
    scenes: list[SegmentContractSceneProgress] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "SegmentContractChapterProgress":
        return cls(
            chapter_number=int(raw.get("chapter_number", 0) or 0),
            chapter_title=str(raw.get("chapter_title", "") or ""),
            status=str(raw.get("status", "pending") or "pending"),
            scene_count=int(raw.get("scene_count", 0) or 0),
            completed_scene_count=int(raw.get("completed_scene_count", 0) or 0),
            segment_count=int(raw.get("segment_count", 0) or 0),
            running_scene_id=str(raw.get("running_scene_id", "") or ""),
            started_at=str(raw.get("started_at")) if raw.get("started_at") else None,
            finished_at=str(raw.get("finished_at")) if raw.get("finished_at") else None,
            failed_scene_id=str(raw.get("failed_scene_id", "") or ""),
            error=str(raw.get("error", "") or ""),
            scenes=[
                SegmentContractSceneProgress.from_dict(item)
                for item in raw.get("scenes", [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class SegmentContractProgress:
    schema_version: int = 3
    status: str = "pending"
    story_title: str = ""
    story_source_revision: str = ""
    total_chapters: int = 0
    total_scenes: int = 0
    total_chunks: int = 0
    completed_chapters: int = 0
    completed_scene_count: int = 0
    completed_chunk_count: int = 0
    completed_segment_count: int = 0
    running_chapter_number: int = 0
    running_scene_id: str = ""
    running_chunk_id: str = ""
    failed_chapter_number: int = 0
    failed_scene_id: str = ""
    failed_chunk_id: str = ""
    last_error: str = ""
    last_updated_at: str | None = None
    resume_ready: bool = False
    chapters: list[SegmentContractChapterProgress] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "SegmentContractProgress":
        return cls(
            schema_version=int(raw.get("schema_version", 1) or 1),
            status=str(raw.get("status", "pending") or "pending"),
            story_title=str(raw.get("story_title", "") or ""),
            story_source_revision=str(raw.get("story_source_revision", "") or ""),
            total_chapters=int(raw.get("total_chapters", 0) or 0),
            total_scenes=int(raw.get("total_scenes", 0) or 0),
            total_chunks=int(raw.get("total_chunks", 0) or 0),
            completed_chapters=int(raw.get("completed_chapters", 0) or 0),
            completed_scene_count=int(raw.get("completed_scene_count", 0) or 0),
            completed_chunk_count=int(raw.get("completed_chunk_count", 0) or 0),
            completed_segment_count=int(raw.get("completed_segment_count", 0) or 0),
            running_chapter_number=int(raw.get("running_chapter_number", 0) or 0),
            running_scene_id=str(raw.get("running_scene_id", "") or ""),
            running_chunk_id=str(raw.get("running_chunk_id", "") or ""),
            failed_chapter_number=int(raw.get("failed_chapter_number", 0) or 0),
            failed_scene_id=str(raw.get("failed_scene_id", "") or ""),
            failed_chunk_id=str(raw.get("failed_chunk_id", "") or ""),
            last_error=str(raw.get("last_error", "") or ""),
            last_updated_at=str(raw.get("last_updated_at")) if raw.get("last_updated_at") else None,
            resume_ready=bool(raw.get("resume_ready", False)),
            chapters=[
                SegmentContractChapterProgress.from_dict(item)
                for item in raw.get("chapters", [])
                if isinstance(item, dict)
            ],
        )


@dataclass(slots=True)
class CharacterImagePipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    character_seedream_execution_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None


@dataclass(slots=True)
class SceneImagePipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    seedream_execution_path: Path
    character_seedream_execution_path: Path
    scene_seedream_execution_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    seedream_execution: SeedreamExecutionReport | None


@dataclass(slots=True)
class StoryboardGridPipelineResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    storyboard_manifest_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    storyboard_tasks: list[StoryboardGridTask]
    generated_count: int
    failed_count: int
    note: str


@dataclass(slots=True)
class VideoRenderResult:
    output_dir: Path
    manifest_path: Path
    seedance_execution_path: Path
    rendered_clip_paths: list[Path]
    full_story_path: Path | None
    manifest: SeedanceManifest
    seedance_execution: SeedanceExecutionReport


@dataclass(slots=True)
class VideoMergeResult:
    output_dir: Path
    manifest_path: Path
    rendered_clip_paths: list[Path]
    full_story_path: Path
    manifest: SeedanceManifest
    merged_clip_count: int
    skipped_clip_count: int


@dataclass(slots=True)
class VideoPlanningArtifacts:
    output_dir: Path
    story_memory_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    segment_contract_progress_path: Path
    scene_images_path: Path
    manifest_path: Path
    storyboard_manifest_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    segment_contract_progress: SegmentContractProgress | None = None


@dataclass(slots=True)
class VideoSceneStructureArtifacts:
    output_dir: Path
    story_memory_path: Path
    character_bible_path: Path
    scene_plan_path: Path
    scene_plan: VideoSegmentPlanSchema
    story_memory: StoryMemoryPackage


@dataclass(slots=True)
class VideoPlanningPaths:
    output_dir: Path
    story_memory_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    segment_contract_progress_path: Path
    scene_images_path: Path
    manifest_path: Path
    storyboard_manifest_path: Path


@dataclass(slots=True)
class ContinuityRepairResult:
    output_dir: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    manifest_path: Path
    continuity_report_path: Path
    repair_report_path: Path
    project_package: VideoProjectPackage
    manifest: SeedanceManifest
    repair_summary: str
    repair_action: str = ""
    selection_mode: str = ""
    affected_segment_ids: tuple[str, ...] = ()
    segment_id: str = ""
    scene_id: str = ""
