from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from storyforge.core.io import write_json
from storyforge.domains.novel.contracts import NovelPackage, StorySourcePackage


@dataclass(slots=True)
class StorySourceFiles:
    output_dir: Path
    story_source_path: Path


@dataclass(slots=True)
class StoryStructureFiles:
    output_dir: Path
    novel_package_path: Path
    novel_audit_path: Path


def write_story_source_files(
    output_dir: Path,
    story_source: StorySourcePackage,
) -> StorySourceFiles:
    output_dir.mkdir(parents=True, exist_ok=True)
    story_source_path = output_dir / "story_source.json"
    write_json(story_source_path, story_source)

    return StorySourceFiles(
        output_dir=output_dir,
        story_source_path=story_source_path,
    )


def write_story_structure_files(
    output_dir: Path,
    novel_package: NovelPackage,
) -> StoryStructureFiles:
    output_dir.mkdir(parents=True, exist_ok=True)
    novel_package_path = output_dir / "novel_package.json"
    novel_audit_path = output_dir / "novel_audit.json"
    write_json(novel_package_path, _build_runtime_novel_package_payload(novel_package))
    write_json(novel_audit_path, _build_novel_audit_payload(novel_package))
    return StoryStructureFiles(
        output_dir=output_dir,
        novel_package_path=novel_package_path,
        novel_audit_path=novel_audit_path,
    )


def clear_story_derived_artifacts(output_dir: Path) -> None:
    removable_files = {
        "novel_package.json",
        "novel_audit.json",
        "story_memory.json",
        "continuity_report.json",
        "character_visual_bible.json",
        "character_image_manifest.json",
        "scene_plan.json",
        "scene_structure_source.json",
        "segment_plan.json",
        "segment_contract_progress.json",
        "scene_image_manifest.json",
        "seedream_character_execution.json",
        "seedream_scene_execution.json",
        "seedance_manifest.json",
        "seedance_execution.json",
    }
    removable_dirs = {
        output_dir / "assets" / "characters",
        output_dir / "assets" / "frames",
        output_dir / "rendered",
    }

    for name in removable_files:
        path = output_dir / name
        if path.exists():
            path.unlink()

    for path in output_dir.glob("continuity_repair_*.json"):
        if path.is_file():
            path.unlink()

    for path in removable_dirs:
        if path.exists():
            shutil.rmtree(path)


def prune_story_derived_result(result: dict[str, object]) -> dict[str, object]:
    pruned = dict(result)
    for key in (
        "novel_package_path",
        "novel_audit_path",
        "story_memory_path",
        "character_bible_path",
        "character_images_path",
        "scene_plan_path",
        "segment_plan_path",
        "scene_images_path",
        "continuity_report_path",
        "repair_report_path",
        "repair_summary",
        "repair_action",
        "repair_execution_mode",
        "media_regeneration_required",
        "pending_media_actions",
        "affected_segment_ids",
        "seedream_execution_path",
        "character_seedream_execution_path",
        "scene_seedream_execution_path",
        "seedance_manifest_path",
        "seedance_execution_path",
        "rendered_clips",
        "full_story_path",
        "seedance_submitted",
    ):
        pruned.pop(key, None)
    return pruned


def _build_runtime_novel_package_payload(
    novel_package: NovelPackage,
) -> dict[str, object]:
    return {
        "brief": novel_package.brief,
        "outline": {
            "title": novel_package.outline.title,
            "visual_motifs": novel_package.outline.visual_motifs,
            "characters": novel_package.outline.characters,
            "chapters": novel_package.outline.chapters,
        },
        "chapters": [
            {
                "number": item.number,
                "title": item.title,
                "markdown": item.markdown,
                "summary": item.summary,
            }
            for item in novel_package.chapters
        ],
    }


def _build_novel_audit_payload(
    novel_package: NovelPackage,
) -> dict[str, object]:
    return {
        "title": novel_package.outline.title,
        "outline_context": {
            "premise": novel_package.outline.premise,
            "theme": novel_package.outline.theme,
            "agent_notes": novel_package.outline.agent_notes,
        },
        "chapter_context": [
            {
                "number": item.number,
                "title": item.title,
                "agent_notes": item.agent_notes,
                "visual_hooks": item.visual_hooks,
                "continuity_refs": item.continuity_refs,
            }
            for item in novel_package.chapters
        ],
        "review": novel_package.review,
        "workflow_trace": novel_package.workflow_trace,
    }
