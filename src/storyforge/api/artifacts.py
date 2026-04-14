from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from storyforge.api.schemas import ArtifactItem, StoryBriefInput, TaskArtifactsResponse, UiBootstrapResponse
from storyforge.application.tasks import TaskRecord
from storyforge.core.config import AppConfig


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}
DOCUMENT_PRIORITY = {
    "story_source.json": 10,
    "novel_package.json": 20,
    "novel_audit.json": 30,
    "character_visual_bible.json": 40,
    "character_image_manifest.json": 50,
    "segment_plan.json": 60,
    "scene_image_manifest.json": 70,
    "seedream_character_execution.json": 80,
    "seedream_scene_execution.json": 90,
    "seedance_manifest.json": 100,
    "seedance_execution.json": 110,
}


def build_ui_bootstrap(config: AppConfig) -> UiBootstrapResponse:
    return UiBootstrapResponse(
        default_brief=StoryBriefInput(
            title_hint="雾站档案",
            idea="一名调查员在暴雨夜追查失踪列车，并在封闭站台发现会提前出现的死亡播报。",
            genre="悬疑 / 都市怪谈",
            tone="压迫、潮湿、电影感",
            target_audience="成年悬疑读者",
            chapter_count=config.novel.default_chapter_count,
            total_word_target=config.novel.default_chapter_word_target * config.novel.default_chapter_count,
            must_include=["失踪列车", "广播站", "暴雨站台"],
            style_keywords=["霓虹", "监控噪点", "夜雨", "旧列车"],
        ),
        use_llm=True,
        submit_seedance=config.video.submit_seedance or config.seedance.auto_submit,
        llm_model=config.llm.model,
        seedream_model=config.seedream.model,
        seedance_model=config.seedance.model,
    )


def build_task_artifacts(
    task: TaskRecord,
    output_root: Path,
) -> TaskArtifactsResponse:
    if task.result is None or not task.result.get("output_dir"):
        return TaskArtifactsResponse(
            task_id=task.task_id,
            available=False,
            note="任务还没有产生产物目录。",
        )

    output_dir = Path(str(task.result["output_dir"])).resolve()
    resolved_output_root = output_root.resolve()
    if not output_dir.is_relative_to(resolved_output_root):
        return TaskArtifactsResponse(
            task_id=task.task_id,
            available=False,
            note="产物目录不在当前输出根目录下，页面无法安全挂载。",
        )

    documents = [
        _to_artifact_item(path, resolved_output_root)
        for path in _sorted_document_paths(output_dir.iterdir())
        if path.is_file()
    ]
    character_images = _collect_artifacts(
        output_dir / "assets" / "characters",
        resolved_output_root,
        allowed_suffixes=IMAGE_SUFFIXES,
    )
    scene_frames = _collect_artifacts(
        output_dir / "assets" / "frames",
        resolved_output_root,
        allowed_suffixes=IMAGE_SUFFIXES,
    )
    rendered_videos = _collect_artifacts(
        output_dir / "rendered",
        resolved_output_root,
        allowed_suffixes=VIDEO_SUFFIXES,
    )
    full_story = next((item for item in rendered_videos if item.name == "full_story.mp4"), None)
    rendered_clips = [item for item in rendered_videos if item.name != "full_story.mp4"]

    return TaskArtifactsResponse(
        task_id=task.task_id,
        available=True,
        note="产物已整理，可直接在页面预览或打开原文件。",
        story_title=str(task.result.get("story_title") or output_dir.name),
        output_dir=str(output_dir),
        documents=documents,
        character_images=character_images,
        scene_frames=scene_frames,
        rendered_clips=rendered_clips,
        full_story=full_story,
    )


def _collect_artifacts(
    directory: Path,
    output_root: Path,
    allowed_suffixes: set[str] | None = None,
) -> list[ArtifactItem]:
    if not directory.exists():
        return []

    items: list[ArtifactItem] = []
    for path in _sorted_paths(directory.rglob("*")):
        if not path.is_file():
            continue
        if allowed_suffixes and path.suffix.lower() not in allowed_suffixes:
            continue
        items.append(_to_artifact_item(path, output_root))
    return items


def _sorted_paths(paths: Iterable[Path]) -> list[Path]:
    return sorted(
        list(paths),
        key=lambda item: (item.is_dir(), item.name.lower()),
    )


def _sorted_document_paths(paths: Iterable[Path]) -> list[Path]:
    return sorted(
        list(paths),
        key=lambda item: (
            item.is_dir(),
            DOCUMENT_PRIORITY.get(item.name, 999),
            item.name.lower(),
        ),
    )


def _to_artifact_item(path: Path, output_root: Path) -> ArtifactItem:
    resolved_path = path.resolve()
    relative_path = resolved_path.relative_to(output_root)
    encoded_path = "/".join(quote(part) for part in relative_path.parts)
    return ArtifactItem(
        name=path.name,
        path=str(resolved_path),
        url=f"/outputs/{encoded_path}",
        kind=_detect_kind(path),
    )


def _detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    if suffix in {".txt", ".log"}:
        return "text"
    if suffix in {".sh", ".bash"}:
        return "shell"
    return "file"
