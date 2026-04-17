from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.agents.base import AgentBackend
from storyforge.core.config import AppConfig
from storyforge.core.io import slugify
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief, StorySourcePackage
from storyforge.domains.novel.service import NovelGeneratorService
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.story_files import (
    clear_story_derived_artifacts,
    write_story_analysis_files,
    write_story_source_files,
)
from storyforge.pipelines.video_models import VideoPlanningArtifacts
from storyforge.pipelines.video_planning import build_video_planning_artifacts


@dataclass(slots=True)
class StoryGenerationResult:
    output_dir: Path
    story_source_path: Path
    story_source: StorySourcePackage


@dataclass(slots=True)
class StoryAnalysisResult:
    output_dir: Path
    novel_package_path: Path
    novel_audit_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    seedance_manifest_path: Path
    novel_package: NovelPackage
    video_planning: VideoPlanningArtifacts


@dataclass(slots=True)
class StoryPipelineResult:
    output_dir: Path
    story_source_path: Path
    novel_package_path: Path
    novel_audit_path: Path
    character_bible_path: Path
    character_images_path: Path
    scene_plan_path: Path
    segment_plan_path: Path
    scene_images_path: Path
    seedance_manifest_path: Path
    story_source: StorySourcePackage
    novel_package: NovelPackage
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


def run_story_analysis_pipeline(
    story_source: StorySourcePackage,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    continuity_review_mode: str = "auto",
    output_root: Path | None = None,
    backend: AgentBackend | None = None,
    video_backend: AgentBackend | None = None,
) -> StoryAnalysisResult:
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
    package = service.build_novel_package_from_story_source(story_source)

    base_dir = output_root or (project_root / config.paths.output_dir)
    output_dir = _resolve_story_output_dir(base_dir, story_source.title)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_files = write_story_analysis_files(output_dir, package)
    video_planning = build_video_planning_artifacts(
        novel_package=package,
        config=config,
        project_root=project_root,
        output_root=output_dir,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        continuity_review_mode=continuity_review_mode,
        backend=video_backend,
    )

    return StoryAnalysisResult(
        output_dir=output_dir,
        novel_package_path=analysis_files.novel_package_path,
        novel_audit_path=analysis_files.novel_audit_path,
        character_bible_path=video_planning.character_bible_path,
        character_images_path=video_planning.character_images_path,
        scene_plan_path=video_planning.scene_plan_path,
        segment_plan_path=video_planning.segment_plan_path,
        scene_images_path=video_planning.scene_images_path,
        seedance_manifest_path=video_planning.manifest_path,
        novel_package=package,
        video_planning=video_planning,
    )


def run_story_pipeline(
    brief: StoryBrief,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    continuity_review_mode: str = "auto",
    output_root: Path | None = None,
    backend: AgentBackend | None = None,
    video_backend: AgentBackend | None = None,
) -> StoryPipelineResult:
    generation = run_story_generation_pipeline(
        brief=brief,
        config=config,
        project_root=project_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        output_root=output_root,
        backend=backend,
    )
    analysis = run_story_analysis_pipeline(
        story_source=generation.story_source,
        config=config,
        project_root=project_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        continuity_review_mode=continuity_review_mode,
        output_root=generation.output_dir,
        backend=backend,
        video_backend=video_backend,
    )

    return StoryPipelineResult(
        output_dir=generation.output_dir,
        story_source_path=generation.story_source_path,
        novel_package_path=analysis.novel_package_path,
        novel_audit_path=analysis.novel_audit_path,
        character_bible_path=analysis.character_bible_path,
        character_images_path=analysis.character_images_path,
        scene_plan_path=analysis.scene_plan_path,
        segment_plan_path=analysis.segment_plan_path,
        scene_images_path=analysis.scene_images_path,
        seedance_manifest_path=analysis.seedance_manifest_path,
        story_source=generation.story_source,
        novel_package=analysis.novel_package,
        video_planning=analysis.video_planning,
    )


def _resolve_story_output_dir(base_dir: Path, title: str) -> Path:
    slug = slugify(title)
    if base_dir.name == slug:
        return base_dir
    return base_dir / slug
