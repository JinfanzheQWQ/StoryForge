from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    novel_package: NovelPackage


@dataclass(slots=True)
class StoryPipelineResult:
    output_dir: Path
    story_source_path: Path
    novel_package_path: Path
    novel_audit_path: Path
    story_source: StorySourcePackage
    novel_package: NovelPackage


def run_story_generation_pipeline(
    brief: StoryBrief,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = False,
    output_root: Path | None = None,
) -> StoryGenerationResult:
    backend = build_agent_backend(config, use_llm=use_llm)
    service = NovelGeneratorService(
        backend=backend,
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
    use_llm: bool = False,
    output_root: Path | None = None,
) -> StoryAnalysisResult:
    backend = build_agent_backend(config, use_llm=use_llm)
    service = NovelGeneratorService(
        backend=backend,
        chapter_scene_count=config.novel.chapter_scene_count,
    )
    package = service.build_novel_package_from_story_source(story_source)

    base_dir = output_root or (project_root / config.paths.output_dir)
    output_dir = _resolve_story_output_dir(base_dir, story_source.title)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_files = write_story_analysis_files(output_dir, package)

    return StoryAnalysisResult(
        output_dir=output_dir,
        novel_package_path=analysis_files.novel_package_path,
        novel_audit_path=analysis_files.novel_audit_path,
        novel_package=package,
    )


def run_story_pipeline(
    brief: StoryBrief,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = False,
    output_root: Path | None = None,
) -> StoryPipelineResult:
    generation = run_story_generation_pipeline(
        brief=brief,
        config=config,
        project_root=project_root,
        use_llm=use_llm,
        output_root=output_root,
    )
    analysis = run_story_analysis_pipeline(
        story_source=generation.story_source,
        config=config,
        project_root=project_root,
        use_llm=use_llm,
        output_root=generation.output_dir,
    )

    return StoryPipelineResult(
        output_dir=generation.output_dir,
        story_source_path=generation.story_source_path,
        novel_package_path=analysis.novel_package_path,
        novel_audit_path=analysis.novel_audit_path,
        story_source=generation.story_source,
        novel_package=analysis.novel_package,
    )


def _resolve_story_output_dir(base_dir: Path, title: str) -> Path:
    slug = slugify(title)
    if base_dir.name == slug:
        return base_dir
    return base_dir / slug
