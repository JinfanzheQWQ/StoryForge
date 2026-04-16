from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from storyforge.api.schemas import (
    ArtifactItem,
    PlannedSegmentArtifactResponse,
    StoryBriefInput,
    TaskArtifactsResponse,
    UiBootstrapResponse,
)
from storyforge.application.tasks import TaskRecord
from storyforge.core.config import AppConfig
from storyforge.core.io import read_json
from storyforge.domains.video.contracts import SceneImageTask, SeedanceManifest, VideoSegment
from storyforge.domains.video.schemas import VideoSegmentPlanSchema


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}
DOCUMENT_PRIORITY = {
    "story_source.json": 10,
    "novel_package.json": 20,
    "novel_audit.json": 30,
    "character_visual_bible.json": 40,
    "character_image_manifest.json": 50,
    "scene_plan.json": 60,
    "segment_plan.json": 70,
    "scene_image_manifest.json": 80,
    "seedream_character_execution.json": 90,
    "seedream_scene_execution.json": 100,
    "seedance_manifest.json": 110,
    "seedance_execution.json": 120,
}
LLM_OPTION_LIBRARY = {
    "deepseek": {"provider": "deepseek", "model": "deepseek-chat", "label": "DeepSeek"},
    "openai": {"provider": "openai", "model": "gpt-5.4", "label": "ChatGPT 5.4"},
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
        llm_provider=config.llm.provider,
        llm_model=config.llm.model,
        available_llm_options=_build_available_llm_options(config),
        seedream_model=config.seedream.model,
        seedance_model=config.seedance.model,
    )


def _build_available_llm_options(config: AppConfig) -> list[dict[str, str]]:
    configured = {
        str(provider).strip().lower()
        for provider in config.llm.available_providers
        if str(provider).strip()
    }
    options: list[dict[str, str]] = []
    for provider, option in LLM_OPTION_LIBRARY.items():
        if configured and provider not in configured:
            continue
        payload = dict(option)
        if provider == config.llm.provider:
            payload["model"] = config.llm.model
        options.append(payload)

    if options:
        return options
    return [
        {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "label": config.llm.provider.title(),
        }
    ]


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
    planned_segments = _collect_planned_segments(
        output_dir=output_dir,
        output_root=resolved_output_root,
        scene_frames=scene_frames,
        rendered_clips=rendered_clips,
    )

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
        planned_segments=planned_segments,
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


def _collect_planned_segments(
    *,
    output_dir: Path,
    output_root: Path,
    scene_frames: list[ArtifactItem],
    rendered_clips: list[ArtifactItem],
) -> list[PlannedSegmentArtifactResponse]:
    scene_plan_path = output_dir / "scene_plan.json"
    segment_plan_path = output_dir / "segment_plan.json"
    if not scene_plan_path.exists() and not segment_plan_path.exists():
        return _build_fallback_planned_segments(scene_frames, rendered_clips)

    try:
        plan = _load_segment_plan(scene_plan_path, segment_plan_path)
        segments = [VideoSegment.from_dict(item.model_dump()) for item in plan.segments]
    except Exception:
        return _build_fallback_planned_segments(scene_frames, rendered_clips)
    scene_task_map = _load_scene_task_map(output_dir)
    clip_map = _load_seedance_clip_map(output_dir)
    scene_frame_map = {item.path: item for item in scene_frames}
    rendered_clip_map = {item.path: item for item in rendered_clips}
    scene_master_map = {
        scene.scene_id: _resolve_manifest_artifact(
            getattr(scene, "scene_master_frame_path", ""),
            output_root,
            scene_frame_map,
        )
        for scene in getattr(plan, "scenes", [])
    }
    planned_segments: list[PlannedSegmentArtifactResponse] = []

    for segment in segments:
        scene_task = scene_task_map.get(segment.segment_id)
        clip_task = clip_map.get(segment.segment_id)
        start_frame = _resolve_manifest_artifact(scene_task.start_frame_path if scene_task else "", output_root, scene_frame_map)
        mid_frame = _resolve_manifest_artifact(scene_task.mid_frame_path if scene_task else "", output_root, scene_frame_map)
        end_frame = _resolve_manifest_artifact(scene_task.end_frame_path if scene_task else "", output_root, scene_frame_map)
        rendered_clip = _resolve_rendered_clip_artifact(clip_task, output_root, rendered_clip_map)
        scene_ready = bool(
            scene_task
            and scene_task.start_frame_url
            and scene_task.end_frame_url
            and (
                not scene_task.requires_mid_frame
                or bool(scene_task.mid_frame_url)
            )
        )
        video_ready = bool(
            clip_task
            and (
                clip_task.downloaded_path
                or rendered_clip is not None
            )
        )
        planned_segments.append(
            PlannedSegmentArtifactResponse(
                segment_id=segment.segment_id,
                scene_id=segment.scene_id,
                scene_title=segment.scene_title,
                scene_summary=segment.scene_summary,
                title=segment.title,
                summary=segment.summary,
                chapter_number=segment.chapter_number,
                duration_seconds=segment.duration_seconds,
                requires_mid_frame=segment.requires_mid_frame,
                scene_master_frame=scene_master_map.get(segment.scene_id),
                start_frame=start_frame,
                mid_frame=mid_frame,
                end_frame=end_frame,
                rendered_clip=rendered_clip,
                scene_ready=scene_ready,
                video_ready=video_ready,
            )
        )
    return planned_segments


def _load_segment_plan(
    scene_plan_path: Path,
    segment_plan_path: Path,
) -> VideoSegmentPlanSchema:
    if scene_plan_path.exists():
        payload = read_json(scene_plan_path)
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict) and "segments" in payload[0]:
                return VideoSegmentPlanSchema.model_validate({"scenes": payload})
            return VideoSegmentPlanSchema.model_validate({"segments": payload})
        return VideoSegmentPlanSchema.model_validate(payload)
    return VideoSegmentPlanSchema.model_validate({"segments": read_json(segment_plan_path)})


def _load_scene_task_map(output_dir: Path) -> dict[str, SceneImageTask]:
    scene_images_path = output_dir / "scene_image_manifest.json"
    if not scene_images_path.exists():
        return {}
    raw_scene_tasks = read_json(scene_images_path)
    if not isinstance(raw_scene_tasks, list):
        return {}
    try:
        return {
            item.segment_id: item
            for item in (
                SceneImageTask.from_dict(raw)
                for raw in raw_scene_tasks
            )
        }
    except Exception:
        return {}


def _load_seedance_clip_map(output_dir: Path):
    manifest_path = output_dir / "seedance_manifest.json"
    if not manifest_path.exists():
        return {}
    raw_manifest = read_json(manifest_path)
    if not isinstance(raw_manifest, dict):
        return {}
    if "title" not in raw_manifest or "model" not in raw_manifest:
        return {}
    try:
        manifest = SeedanceManifest.from_dict(raw_manifest)
    except Exception:
        return {}
    return {clip.segment_id: clip for clip in manifest.clips}


def _resolve_manifest_artifact(
    relative_path: str,
    output_root: Path,
    artifact_map: dict[str, ArtifactItem],
) -> ArtifactItem | None:
    if not relative_path:
        return None
    resolved_path = Path(relative_path)
    if not resolved_path.is_absolute():
        resolved_path = output_root / relative_path
    resolved_path = resolved_path.resolve()
    existing = artifact_map.get(str(resolved_path))
    if existing is not None:
        return existing
    if resolved_path.exists():
        return _to_artifact_item(resolved_path, output_root)
    return None


def _resolve_rendered_clip_artifact(
    clip_task,
    output_root: Path,
    artifact_map: dict[str, ArtifactItem],
) -> ArtifactItem | None:
    if clip_task is None:
        return None
    clip_path = clip_task.downloaded_path or clip_task.output_path
    return _resolve_manifest_artifact(clip_path, output_root, artifact_map)


def _build_fallback_planned_segments(
    scene_frames: list[ArtifactItem],
    rendered_clips: list[ArtifactItem],
) -> list[PlannedSegmentArtifactResponse]:
    segment_map: dict[str, PlannedSegmentArtifactResponse] = {}
    for item in scene_frames:
        if item.name.endswith("_master.png") or item.name.endswith("_master.jpg") or item.name.endswith("_master.webp"):
            continue
        segment_id = _segment_id_from_asset_name(item.name)
        segment = segment_map.setdefault(
            segment_id,
            PlannedSegmentArtifactResponse(
                segment_id=segment_id,
                title=segment_id or item.name,
                chapter_number=0,
            ),
        )
        if "_end" in item.name:
            segment.end_frame = item
        elif "_mid" in item.name:
            segment.mid_frame = item
            segment.requires_mid_frame = True
        else:
            segment.start_frame = item
    for item in rendered_clips:
        segment_id = _segment_id_from_asset_name(item.name)
        segment = segment_map.setdefault(
            segment_id,
            PlannedSegmentArtifactResponse(
                segment_id=segment_id,
                title=segment_id or item.name,
                chapter_number=0,
            ),
        )
        segment.rendered_clip = item
    for segment in segment_map.values():
        segment.scene_ready = bool(
            segment.start_frame and segment.end_frame and (not segment.requires_mid_frame or segment.mid_frame)
        )
        segment.video_ready = segment.rendered_clip is not None
    return sorted(segment_map.values(), key=lambda item: item.segment_id)


def _segment_id_from_asset_name(name: str) -> str:
    return name.rsplit(".", 1)[0].removesuffix("_start").removesuffix("_mid").removesuffix("_end")
