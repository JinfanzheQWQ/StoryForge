from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from storyforge.agents.base import AgentBackend
from storyforge.core.config import AppConfig
from storyforge.core.io import slugify
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief, StorySourcePackage
from storyforge.domains.novel.service import NovelGeneratorService
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.story_files import (
    clear_story_derived_artifacts,
    write_story_structure_files,
    write_story_source_files,
)
from storyforge.pipelines.video_models import (
    SegmentContractProgress,
    VideoPlanningArtifacts,
    VideoSceneStructureArtifacts,
)
from storyforge.pipelines.video_planning import (
    build_video_scene_structure_artifacts,
    build_video_segment_contract_artifacts,
)


@dataclass(slots=True)
class StoryGenerationResult:
    output_dir: Path
    story_source_path: Path
    story_source: StorySourcePackage


@dataclass(slots=True)
class StorySceneStructureResult:
    output_dir: Path
    novel_package_path: Path
    novel_audit_path: Path
    story_memory_path: Path
    character_bible_path: Path
    scene_plan_path: Path
    novel_package: NovelPackage
    scene_structure: VideoSceneStructureArtifacts


@dataclass(slots=True)
class StorySegmentContractsResult:
    output_dir: Path
    story_memory_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    segment_contract_progress_path: Path
    scene_images_path: Path
    seedance_manifest_path: Path
    video_planning: VideoPlanningArtifacts


def run_story_generation_pipeline(
    brief: StoryBrief,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    output_root: Path | None = None,
    backend: AgentBackend | None = None,
) -> StoryGenerationResult:
    resolved_backend = backend or build_agent_backend(
        config,
        use_llm=use_llm,
        provider=llm_provider,
        model=llm_model,
    )
    service = NovelGeneratorService(
        backend=resolved_backend,
        chapter_scene_count=config.novel.chapter_scene_count,
    )
    story_source = service.build_story_source(brief)

    base_dir = output_root or (project_root / config.paths.output_dir)
    output_dir = _resolve_story_output_dir(base_dir, story_source.title)
    story_files = write_story_source_files(output_dir, story_source)
    clear_story_derived_artifacts(output_dir)

    return StoryGenerationResult(
        output_dir=output_dir,
        story_source_path=story_files.story_source_path,
        story_source=story_source,
    )


def run_story_scene_structure_pipeline(
    story_source: StorySourcePackage,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    output_root: Path | None = None,
    backend: AgentBackend | None = None,
    video_backend: AgentBackend | None = None,
) -> StorySceneStructureResult:
    package = _build_novel_package_from_story_source(
        story_source=story_source,
        config=config,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        backend=backend,
    )

    base_dir = output_root or (project_root / config.paths.output_dir)
    output_dir = _resolve_story_output_dir(base_dir, story_source.title)
    output_dir.mkdir(parents=True, exist_ok=True)

    clear_story_derived_artifacts(output_dir)
    analysis_files = write_story_structure_files(output_dir, package)
    scene_structure = build_video_scene_structure_artifacts(
        novel_package=package,
        config=config,
        project_root=project_root,
        output_root=output_dir,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        backend=video_backend,
    )

    return StorySceneStructureResult(
        output_dir=output_dir,
        novel_package_path=analysis_files.novel_package_path,
        novel_audit_path=analysis_files.novel_audit_path,
        story_memory_path=scene_structure.story_memory_path,
        character_bible_path=scene_structure.character_bible_path,
        scene_plan_path=scene_structure.scene_plan_path,
        novel_package=package,
        scene_structure=scene_structure,
    )


def run_story_segment_contracts_pipeline(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    continuity_review_mode: str = "auto",
    output_root: Path | None = None,
    backend: AgentBackend | None = None,
    scene_structure_artifacts: VideoSceneStructureArtifacts | None = None,
    resume_from_progress: bool = False,
    progress_callback: Callable[[SegmentContractProgress], None] | None = None,
) -> StorySegmentContractsResult:
    video_planning = build_video_segment_contract_artifacts(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=output_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        continuity_review_mode=continuity_review_mode,
        backend=backend,
        scene_structure_artifacts=scene_structure_artifacts,
        resume_from_progress=resume_from_progress,
        progress_callback=progress_callback,
    )
    return StorySegmentContractsResult(
        output_dir=video_planning.output_dir,
        story_memory_path=video_planning.story_memory_path,
        character_bible_path=video_planning.character_bible_path,
        character_images_path=video_planning.character_images_path,
        scene_plan_path=video_planning.scene_plan_path,
        segment_plan_path=video_planning.segment_plan_path,
        segment_contract_progress_path=video_planning.segment_contract_progress_path,
        scene_images_path=video_planning.scene_images_path,
        seedance_manifest_path=video_planning.manifest_path,
        video_planning=video_planning,
    )

def _build_novel_package_from_story_source(
    *,
    story_source: StorySourcePackage,
    config: AppConfig,
    use_llm: bool,
    llm_provider: str | None,
    llm_model: str | None,
    backend: AgentBackend | None,
) -> NovelPackage:
    resolved_backend = backend or build_agent_backend(
        config,
        use_llm=use_llm,
        provider=llm_provider,
        model=llm_model,
    )
    service = NovelGeneratorService(
        backend=resolved_backend,
        chapter_scene_count=config.novel.chapter_scene_count,
    )
    return service.build_novel_package_from_story_source(story_source)


def _resolve_story_output_dir(base_dir: Path, title: str) -> Path:
    slug = slugify(title)
    if base_dir.name == slug:
        return base_dir
    return base_dir / slug
