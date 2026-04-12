from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.core.io import slugify, write_json, write_text
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief
from storyforge.domains.novel.service import NovelGeneratorService
from storyforge.integrations.llm import build_agent_backend


@dataclass(slots=True)
class StoryPipelineResult:
    output_dir: Path
    outline_path: Path
    novel_package_path: Path
    chapter_paths: list[Path]
    novel_package: NovelPackage


def run_story_pipeline(
    brief: StoryBrief,
    config: AppConfig,
    project_root: Path,
    use_llm: bool = False,
    output_root: Path | None = None,
) -> StoryPipelineResult:
    backend = build_agent_backend(config, use_llm=use_llm)
    service = NovelGeneratorService(
        backend=backend,
        chapter_scene_count=config.novel.chapter_scene_count,
        major_character_count=config.novel.major_character_count,
    )
    package = service.build_novel_package(brief)

    base_dir = output_root or (project_root / config.paths.output_dir)
    output_dir = base_dir / slugify(package.outline.title)
    chapters_dir = output_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    outline_path = output_dir / "outline.json"
    novel_package_path = output_dir / "novel_package.json"
    review_path = output_dir / "editorial_review.json"
    workflow_trace_path = output_dir / "workflow_trace.json"
    write_json(outline_path, package.outline)
    write_json(novel_package_path, package)
    write_json(review_path, package.review)
    write_json(workflow_trace_path, package.workflow_trace)

    chapter_paths: list[Path] = []
    for chapter in package.chapters:
        chapter_path = chapters_dir / f"chapter-{chapter.number:02d}.md"
        write_text(chapter_path, chapter.markdown)
        chapter_paths.append(chapter_path)

    return StoryPipelineResult(
        output_dir=output_dir,
        outline_path=outline_path,
        novel_package_path=novel_package_path,
        chapter_paths=chapter_paths,
        novel_package=package,
    )
