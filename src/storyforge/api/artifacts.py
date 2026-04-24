from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from storyforge.api.schemas import (
    ArtifactItem,
    CharacterArtifactItem,
    ContinuityIssueDetailResponse,
    ContinuityIssueGroupResponse,
    ContinuityIssueSummaryResponse,
    ContinuitySummaryResponse,
    PlannedSegmentArtifactResponse,
    PromptReferenceBindingResponse,
    SubmittedRequestResponse,
    StoryBriefInput,
    TaskArtifactsResponse,
    UiBootstrapResponse,
)
from storyforge.application.tasks import TaskRecord
from storyforge.core.config import AppConfig
from storyforge.core.io import read_json
from storyforge.domains.video.contracts import VideoSegment
from storyforge.pipelines.video_planning import (
    load_scene_image_task_map,
    load_seedance_clip_map,
    load_video_segment_plan,
)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}
DOCUMENT_PRIORITY = {
    "story_source.json": 10,
    "novel_package.json": 20,
    "novel_audit.json": 30,
    "character_visual_bible.json": 40,
    "character_image_manifest.json": 50,
    "scene_plan.json": 60,
    "scene_structure_source.json": 65,
    "segment_plan.json": 70,
    "segment_contract_progress.json": 80,
    "scene_image_manifest.json": 90,
    "seedream_character_execution.json": 100,
    "seedream_scene_execution.json": 110,
    "seedance_manifest.json": 120,
    "seedance_execution.json": 130,
    "continuity_report.json": 140,
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
        continuity_review_mode="auto",
        available_llm_options=_build_available_llm_options(config),
        seedream_model=config.seedream.model,
        seedance_model=config.seedance.model,
        seedream_watermark=config.seedream.watermark,
        seedance_watermark=config.seedance.watermark,
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
    character_images = _collect_character_artifacts(
        output_dir=output_dir,
        output_root=resolved_output_root,
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
        character_images=character_images,
        scene_frames=scene_frames,
        rendered_clips=rendered_clips,
    )
    continuity_report, continuity_summary, continuity_scene_groups, continuity_segment_groups = _collect_continuity_report(
        output_dir=output_dir,
        output_root=resolved_output_root,
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
        continuity_report=continuity_report,
        continuity_summary=continuity_summary,
        continuity_scene_groups=continuity_scene_groups,
        continuity_segment_groups=continuity_segment_groups,
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


def _collect_character_artifacts(
    *,
    output_dir: Path,
    output_root: Path,
) -> list[CharacterArtifactItem]:
    artifacts = _collect_artifacts(
        output_dir / "assets" / "characters",
        output_root,
        allowed_suffixes=IMAGE_SUFFIXES,
    )
    manifest_map = _load_character_manifest_map(output_dir)
    character_items: list[CharacterArtifactItem] = []
    for artifact in artifacts:
        manifest_item = manifest_map.get(artifact.path, {})
        character_items.append(
            CharacterArtifactItem(
                **artifact.model_dump(),
                character_name=str(manifest_item.get("character_name", "") or ""),
                prompt=str(manifest_item.get("prompt", "") or ""),
                consistency_notes=str(manifest_item.get("consistency_notes", "") or ""),
                provider=str(manifest_item.get("provider", "") or ""),
                status=str(manifest_item.get("status", "") or ""),
                image_kind=str(manifest_item.get("image_kind", "") or ""),
                error=str(manifest_item.get("error", "") or ""),
            )
        )
    return character_items


def _load_character_manifest_map(output_dir: Path) -> dict[str, dict[str, object]]:
    manifest_path = output_dir / "character_image_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = read_json(manifest_path)
    except Exception:
        return {}
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("character_images") or payload.get("characters") or []
        items = raw_items if isinstance(raw_items, list) else []
    else:
        items = []

    manifest_map: dict[str, dict[str, object]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        output_path = str(item.get("output_path", "") or "").strip()
        if not output_path:
            continue
        resolved_output_path = Path(output_path)
        if not resolved_output_path.is_absolute():
            resolved_output_path = (output_dir / resolved_output_path).resolve()
        else:
            resolved_output_path = resolved_output_path.resolve()
        manifest_map[str(resolved_output_path)] = item
    return manifest_map


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
    character_images: list[ArtifactItem],
    scene_frames: list[ArtifactItem],
    rendered_clips: list[ArtifactItem],
) -> list[PlannedSegmentArtifactResponse]:
    scene_plan_path = output_dir / "scene_plan.json"
    segment_plan_path = output_dir / "segment_plan.json"
    if not scene_plan_path.exists() and not segment_plan_path.exists():
        return _build_inferred_planned_segments(scene_frames, rendered_clips)

    try:
        plan = load_video_segment_plan(output_dir)
        segments = [VideoSegment.from_dict(item.model_dump()) for item in plan.segments]
    except Exception:
        return _build_inferred_planned_segments(scene_frames, rendered_clips)
    scene_task_map = load_scene_image_task_map(output_dir)
    clip_map = load_seedance_clip_map(output_dir)
    scene_task_by_scene: dict[str, object] = {}
    for task in scene_task_map.values():
        if task.scene_id and task.scene_id not in scene_task_by_scene:
            scene_task_by_scene[task.scene_id] = task
    scene_frame_map = {item.path: item for item in scene_frames}
    rendered_clip_map = {item.path: item for item in rendered_clips}
    character_image_map = {item.path: item for item in character_images}
    scene_master_map = {
        scene.scene_id: _resolve_manifest_artifact(
            getattr(scene, "scene_master_frame_path", ""),
            output_root,
            scene_frame_map,
        )
        for scene in getattr(plan, "scenes", [])
    }
    scene_request_map = {
        scene.scene_id: (
            _build_submitted_request_response(
                getattr(scene, "scene_master_request_info", {}),
            )
            or _build_derived_scene_master_request_response(
                prompt_text=str(getattr(scene, "scene_master_frame_prompt", "") or ""),
                scene_master_frame=scene_master_map.get(scene.scene_id),
                provider=str(getattr(scene_task_by_scene.get(scene.scene_id), "provider", "") or "seedream"),
            )
        )
        for scene in getattr(plan, "scenes", [])
    }
    planned_segments: list[PlannedSegmentArtifactResponse] = []

    for segment in segments:
        scene_task = scene_task_map.get(segment.segment_id)
        clip_task = clip_map.get(segment.segment_id)
        requires_mid_frame = bool(getattr(segment, "requires_mid_frame", False))
        start_frame = _resolve_manifest_artifact(scene_task.start_frame_path if scene_task else "", output_root, scene_frame_map)
        mid_frame = (
            _resolve_manifest_artifact(scene_task.mid_frame_path if scene_task else "", output_root, scene_frame_map)
            if requires_mid_frame
            else None
        )
        end_frame = _resolve_manifest_artifact(scene_task.end_frame_path if scene_task else "", output_root, scene_frame_map)
        rendered_clip = _resolve_rendered_clip_artifact(clip_task, output_root, rendered_clip_map)
        scene_ready = bool(
            scene_task
            and scene_task.start_frame_url
            and scene_task.end_frame_url
            and (
                not requires_mid_frame
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
                requires_mid_frame=requires_mid_frame,
                mid_frame_mode=getattr(segment, "mid_frame_mode", "continuous"),
                scene_master_frame=scene_master_map.get(segment.scene_id),
                start_frame=start_frame,
                mid_frame=mid_frame,
                end_frame=end_frame,
                rendered_clip=rendered_clip,
                scene_master_frame_prompt=scene_task.scene_master_frame_prompt if scene_task else "",
                start_frame_prompt=scene_task.start_frame_prompt if scene_task else segment.start_frame_prompt,
                mid_frame_prompt=(
                    (scene_task.mid_frame_prompt if scene_task else segment.mid_frame_prompt)
                    if requires_mid_frame
                    else ""
                ),
                end_frame_prompt=scene_task.end_frame_prompt if scene_task else segment.end_frame_prompt,
                video_prompt=clip_task.prompt if clip_task else "",
                submitted_video_prompt=clip_task.submitted_prompt if clip_task else "",
                submitted_prompt_variant=clip_task.submit_variant if clip_task else "",
                submitted_reference_bindings=_build_prompt_reference_bindings(
                    clip_task.submitted_reference_bindings if clip_task else [],
                ),
                scene_master_frame_request=scene_request_map.get(segment.scene_id),
                start_frame_request=(
                    _build_submitted_request_response(
                        scene_task.start_frame_request_info if scene_task else {},
                    )
                    or _build_derived_scene_frame_request_response(
                        provider=str(getattr(scene_task, "provider", "") or "seedream"),
                        prompt=str(getattr(scene_task, "start_frame_prompt", "") or ""),
                        frame_kind="start",
                        scene_task=scene_task,
                        scene_task_map=scene_task_map,
                        scene_frame_map=scene_frame_map,
                        scene_master_frame=scene_master_map.get(segment.scene_id),
                        character_image_map=character_image_map,
                        start_frame=start_frame,
                        mid_frame=mid_frame,
                    )
                ),
                mid_frame_request=(
                    (
                        _build_submitted_request_response(
                            scene_task.mid_frame_request_info if scene_task else {},
                        )
                        or _build_derived_scene_frame_request_response(
                            provider=str(getattr(scene_task, "provider", "") or "seedream"),
                            prompt=str(getattr(scene_task, "mid_frame_prompt", "") or ""),
                            frame_kind="mid",
                            scene_task=scene_task,
                            scene_task_map=scene_task_map,
                            scene_frame_map=scene_frame_map,
                            scene_master_frame=scene_master_map.get(segment.scene_id),
                            character_image_map=character_image_map,
                            start_frame=start_frame,
                            mid_frame=mid_frame,
                        )
                    )
                    if requires_mid_frame
                    else None
                ),
                end_frame_request=(
                    _build_submitted_request_response(
                        scene_task.end_frame_request_info if scene_task else {},
                    )
                    or _build_derived_scene_frame_request_response(
                        provider=str(getattr(scene_task, "provider", "") or "seedream"),
                        prompt=str(getattr(scene_task, "end_frame_prompt", "") or ""),
                        frame_kind="end",
                        scene_task=scene_task,
                        scene_task_map=scene_task_map,
                        scene_frame_map=scene_frame_map,
                        scene_master_frame=scene_master_map.get(segment.scene_id),
                        character_image_map=character_image_map,
                        start_frame=start_frame,
                        mid_frame=mid_frame,
                    )
                ),
                video_request=(
                    _build_submitted_request_response(
                        clip_task.submitted_request_info if clip_task else {},
                    )
                    or _build_legacy_video_request_response(
                        clip_task,
                        start_frame=start_frame,
                        mid_frame=mid_frame,
                        end_frame=end_frame,
                    )
                ),
                scene_ready=scene_ready,
                video_ready=video_ready,
            )
        )
    return planned_segments


def _build_prompt_reference_bindings(
    bindings: object,
) -> list[PromptReferenceBindingResponse]:
    if not isinstance(bindings, list):
        return []
    normalized: list[PromptReferenceBindingResponse] = []
    for item in bindings:
        if not isinstance(item, dict):
            continue
        normalized.append(
            PromptReferenceBindingResponse(
                label=str(item.get("label", "") or ""),
                kind=str(item.get("kind", "") or ""),
                description=str(item.get("description", "") or ""),
                url=str(item.get("url", "") or ""),
            )
        )
    return normalized


def _build_submitted_request_response(
    request_info: object,
) -> SubmittedRequestResponse | None:
    if not isinstance(request_info, dict):
        return None
    payload = request_info.get("payload")
    reference_bindings = _build_prompt_reference_bindings(
        request_info.get("reference_bindings", []),
    )
    endpoint = str(request_info.get("endpoint", "") or "")
    provider = str(request_info.get("provider", "") or "")
    variant = str(request_info.get("variant", "") or "")
    if not provider and not endpoint and not variant and not isinstance(payload, dict) and not reference_bindings:
        return None
    return SubmittedRequestResponse(
        provider=provider,
        endpoint=endpoint,
        variant=variant,
        payload=payload if isinstance(payload, dict) else {},
        reference_bindings=reference_bindings,
    )


def _build_legacy_video_request_response(
    clip_task,
    *,
    start_frame: ArtifactItem | None,
    mid_frame: ArtifactItem | None,
    end_frame: ArtifactItem | None,
) -> SubmittedRequestResponse | None:
    if clip_task is None:
        return None
    prompt = str(
        getattr(clip_task, "submitted_prompt", "") or getattr(clip_task, "prompt", "") or ""
    ).strip()
    reference_bindings = _build_video_reference_bindings(
        clip_task,
        start_frame=start_frame,
        mid_frame=mid_frame,
        end_frame=end_frame,
    )
    if not prompt and not reference_bindings:
        return None
    content: list[dict[str, object]] = []
    if prompt:
        content.append({"type": "text", "text": prompt})
    for item in reference_bindings:
        if not item.url:
            continue
        content.append(
            {
                "role": "reference_image",
                "type": "image_url",
                "image_url": {"url": item.url},
            }
        )
    return SubmittedRequestResponse(
        provider="seedance",
        endpoint="",
        variant=str(getattr(clip_task, "submit_variant", "") or "derived_from_manifest"),
        payload={
            "mode": "derived_from_manifest",
            "content": content,
            "ratio": str(getattr(clip_task, "aspect_ratio", "") or ""),
            "duration": int(getattr(clip_task, "duration_seconds", 0) or 0),
            "generate_audio": bool(getattr(clip_task, "with_audio", True)),
        },
        reference_bindings=reference_bindings,
    )


def _build_derived_scene_master_request_response(
    *,
    prompt_text: str,
    scene_master_frame: ArtifactItem | None,
    provider: str,
) -> SubmittedRequestResponse | None:
    prompt = str(prompt_text or "").strip()
    if not prompt and scene_master_frame is None:
        return None
    return SubmittedRequestResponse(
        provider=provider or "seedream",
        endpoint="",
        variant="derived_from_manifest",
        payload={
            "mode": "derived_from_manifest",
            "prompt": prompt,
            "reference_images": [],
        },
        reference_bindings=[],
    )


def _build_derived_scene_frame_request_response(
    *,
    provider: str,
    prompt: str,
    frame_kind: str,
    scene_task,
    scene_task_map: dict[str, object],
    scene_frame_map: dict[str, ArtifactItem],
    scene_master_frame: ArtifactItem | None,
    character_image_map: dict[str, ArtifactItem],
    start_frame: ArtifactItem | None,
    mid_frame: ArtifactItem | None,
) -> SubmittedRequestResponse | None:
    if scene_task is None:
        return None
    prompt_text = str(prompt or "").strip()
    reference_bindings = _build_scene_frame_reference_bindings(
        frame_kind=frame_kind,
        scene_task=scene_task,
        scene_task_map=scene_task_map,
        scene_frame_map=scene_frame_map,
        scene_master_frame=scene_master_frame,
        character_image_map=character_image_map,
        start_frame=start_frame,
        mid_frame=mid_frame,
    )
    if not prompt_text and not reference_bindings:
        return None
    return SubmittedRequestResponse(
        provider=provider or "seedream",
        endpoint="",
        variant="derived_from_manifest",
        payload={
            "mode": "derived_from_manifest",
            "frame": frame_kind,
            "prompt": prompt_text,
            "reference_images": [item.url for item in reference_bindings if item.url],
        },
        reference_bindings=reference_bindings,
    )


def _build_scene_frame_reference_bindings(
    *,
    frame_kind: str,
    scene_task,
    scene_task_map: dict[str, object],
    scene_frame_map: dict[str, ArtifactItem],
    scene_master_frame: ArtifactItem | None,
    character_image_map: dict[str, ArtifactItem],
    start_frame: ArtifactItem | None,
    mid_frame: ArtifactItem | None,
) -> list[PromptReferenceBindingResponse]:
    bindings: list[dict[str, str]] = []
    if scene_master_frame is not None and scene_master_frame.url:
        bindings.append(
            {
                "label": f"图片{len(bindings) + 1}",
                "kind": "scene_master",
                "description": "场景母图参考，用于锁定当前 scene 的环境、空间和光线基线。",
                "url": scene_master_frame.url,
            }
        )
    frame_characters = _frame_character_names(scene_task, frame_kind)
    for artifact in _resolve_character_reference_artifacts(
        scene_task=scene_task,
        frame_characters=frame_characters,
        character_image_map=character_image_map,
    ):
        if not artifact.url:
            continue
        bindings.append(
            {
                "label": f"图片{len(bindings) + 1}",
                "kind": "character",
                "description": "角色参考图，用于锁定当前帧真实出镜角色的定妆、服装和外观。",
                "url": artifact.url,
            }
        )
    temporal_artifact = _resolve_temporal_reference_artifact(
        frame_kind=frame_kind,
        scene_task=scene_task,
        scene_task_map=scene_task_map,
        scene_frame_map=scene_frame_map,
        start_frame=start_frame,
        mid_frame=mid_frame,
    )
    if temporal_artifact is not None and temporal_artifact.url:
        bindings.append(
            {
                "label": f"图片{len(bindings) + 1}",
                "kind": "temporal",
                "description": "时间承接参考，用上一帧或上一段画面锁定动作与镜头衔接。",
                "url": temporal_artifact.url,
            }
        )
    return _build_prompt_reference_bindings(bindings)


def _frame_character_names(scene_task, frame_kind: str) -> list[str]:
    mapping = {
        "start": getattr(scene_task, "start_frame_characters", []),
        "mid": getattr(scene_task, "mid_frame_characters", []),
        "end": getattr(scene_task, "end_frame_characters", []),
    }
    raw_names = mapping.get(frame_kind, [])
    if isinstance(raw_names, list):
        return [str(item).strip() for item in raw_names if str(item).strip()]
    return []


def _resolve_character_reference_artifacts(
    *,
    scene_task,
    frame_characters: list[str],
    character_image_map: dict[str, ArtifactItem],
) -> list[ArtifactItem]:
    candidates = [
        character_image_map[path]
        for path in getattr(scene_task, "reference_images", [])
        if path in character_image_map
    ]
    if not frame_characters:
        return candidates[:1] if len(candidates) == 1 else []
    selected: list[ArtifactItem] = []
    used_paths: set[str] = set()
    for name in frame_characters:
        matched = next(
            (
                item
                for item in candidates
                if item.path not in used_paths and _character_artifact_matches_name(item, name)
            ),
            None,
        )
        if matched is None:
            continue
        used_paths.add(matched.path)
        selected.append(matched)
    if selected:
        return selected
    return candidates[:1] if len(candidates) == 1 else candidates


def _character_artifact_matches_name(artifact: ArtifactItem, character_name: str) -> bool:
    name = str(character_name or "").strip()
    if not name:
        return False
    return name in artifact.name or name in artifact.path


def _resolve_temporal_reference_artifact(
    *,
    frame_kind: str,
    scene_task,
    scene_task_map: dict[str, object],
    scene_frame_map: dict[str, ArtifactItem],
    start_frame: ArtifactItem | None,
    mid_frame: ArtifactItem | None,
) -> ArtifactItem | None:
    if frame_kind == "start":
        if not getattr(scene_task, "reuse_previous_end_frame", False):
            return None
        source_segment_id = str(getattr(scene_task, "continuity_source_segment_id", "") or "").strip()
        if not source_segment_id:
            return None
        previous_task = scene_task_map.get(source_segment_id)
        previous_end_path = str(getattr(previous_task, "end_frame_path", "") or "").strip() if previous_task else ""
        return scene_frame_map.get(previous_end_path)
    if frame_kind == "mid":
        return start_frame
    if frame_kind == "end":
        return mid_frame or start_frame
    return None


def _build_video_reference_bindings(
    clip_task,
    *,
    start_frame: ArtifactItem | None,
    mid_frame: ArtifactItem | None,
    end_frame: ArtifactItem | None,
) -> list[PromptReferenceBindingResponse]:
    bindings: list[dict[str, str]] = []
    ordered = [
        ("start", start_frame),
        ("mid", mid_frame),
        ("end", end_frame),
    ]
    descriptions = {
        "start": "开场视觉锚点，视频必须从这张图对应的构图、角色关系与动作状态自然起步。",
        "mid": "中段视觉锚点，镜头推进过程中必须自然经过这张图对应的中间状态，不要跳过或弱化。",
        "end": "收束视觉锚点，片尾必须落到这张图对应的构图、角色关系与动作结果。",
    }
    for kind, artifact in ordered:
        if artifact is None or not artifact.url:
            continue
        bindings.append(
            {
                "label": f"图片{len(bindings) + 1}",
                "kind": kind,
                "description": descriptions[kind],
                "url": artifact.url,
            }
        )
    return _build_prompt_reference_bindings(bindings)


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


def _collect_continuity_report(
    *,
    output_dir: Path,
    output_root: Path,
) -> tuple[
    ArtifactItem | None,
    ContinuitySummaryResponse | None,
    list[ContinuityIssueGroupResponse],
    list[ContinuityIssueGroupResponse],
]:
    report_path = output_dir / "continuity_report.json"
    if not report_path.exists():
        return None, None, [], []
    artifact_item = _to_artifact_item(report_path, output_root)
    try:
        payload = read_json(report_path)
    except Exception:
        return artifact_item, None, [], []
    if not isinstance(payload, dict):
        return artifact_item, None, [], []

    summary_payload = payload.get("summary")
    if not isinstance(summary_payload, dict):
        return artifact_item, None, [], []

    scene_issues = _collect_continuity_issue_details(payload.get("scene_issues"))
    segment_issues = _collect_continuity_issue_details(payload.get("segment_issues"))
    issues = [*scene_issues, *segment_issues]
    sorted_issues = sorted(
        issues,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.severity, 99),
            item.scene_id,
            item.segment_id,
            item.code,
        ),
    )
    top_issues = [
        ContinuityIssueSummaryResponse(
            severity=item.severity,
            scope=item.scope,
            code=item.code,
            message=item.message,
            scene_id=item.scene_id,
            segment_id=item.segment_id,
            recommended_action=item.recommended_action,
            recommended_action_label=item.recommended_action_label,
        )
        for item in sorted_issues[:5]
    ]
    action_labels = [
        str(item.get("label", "") or "")
        for item in payload.get("recommended_actions", [])
        if isinstance(item, dict) and str(item.get("label", "") or "")
    ]
    v2_payload = payload.get("v2_llm_review") if isinstance(payload.get("v2_llm_review"), dict) else {}
    v2_summary_payload = v2_payload.get("summary") if isinstance(v2_payload.get("summary"), dict) else {}
    return (
        artifact_item,
        ContinuitySummaryResponse(
            status=str(payload.get("status", "") or "unknown"),
            report_version=str(payload.get("report_version", "") or ""),
            generated_at=str(payload.get("generated_at", "") or "") or None,
            review_mode_requested=str(payload.get("review_mode_requested", "") or "auto"),
            review_mode_effective=str(payload.get("review_mode_effective", "") or "off"),
            v2_review_status=str(v2_payload.get("status", "") or "disabled"),
            v2_issue_count=int(v2_summary_payload.get("issue_count", 0) or 0),
            v2_note=str(v2_payload.get("note", "") or ""),
            issue_count=int(summary_payload.get("issue_count", 0) or 0),
            high_risk_count=int(summary_payload.get("high_risk_count", 0) or 0),
            medium_risk_count=int(summary_payload.get("medium_risk_count", 0) or 0),
            low_risk_count=int(summary_payload.get("low_risk_count", 0) or 0),
            scene_issue_count=int(summary_payload.get("scene_issue_count", 0) or 0),
            segment_issue_count=int(summary_payload.get("segment_issue_count", 0) or 0),
            recommended_actions=action_labels,
            top_issues=top_issues,
        ),
        _group_continuity_issues(scene_issues, scope="scene"),
        _group_continuity_issues(segment_issues, scope="segment"),
    )


def _collect_continuity_issue_details(raw_items) -> list[ContinuityIssueDetailResponse]:
    if not isinstance(raw_items, list):
        return []
    issues: list[ContinuityIssueDetailResponse] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        issues.append(
            ContinuityIssueDetailResponse(
                severity=str(item.get("severity", "") or ""),
                scope=str(item.get("scope", "") or ""),
                code=str(item.get("code", "") or ""),
                message=str(item.get("message", "") or ""),
                scene_id=str(item.get("scene_id", "") or ""),
                segment_id=str(item.get("segment_id", "") or ""),
                recommended_action=str(item.get("recommended_action", "") or ""),
                recommended_action_label=str(item.get("recommended_action_label", "") or ""),
                details=item.get("details", {}) if isinstance(item.get("details"), dict) else {},
            )
        )
    return issues


def _group_continuity_issues(
    issues: list[ContinuityIssueDetailResponse],
    *,
    scope: str,
) -> list[ContinuityIssueGroupResponse]:
    grouped: dict[tuple[str, str], list[ContinuityIssueDetailResponse]] = {}
    for issue in issues:
        key = (issue.scene_id, issue.segment_id if scope == "segment" else "")
        grouped.setdefault(key, []).append(issue)

    groups: list[ContinuityIssueGroupResponse] = []
    for (scene_id, segment_id), grouped_issues in grouped.items():
        sorted_grouped_issues = sorted(
            grouped_issues,
            key=lambda item: (
                {"high": 0, "medium": 1, "low": 2}.get(item.severity, 99),
                item.code,
            ),
        )
        recommended_actions = list(
            dict.fromkeys(
                action
                for action in (item.recommended_action for item in sorted_grouped_issues)
                if action
            )
        )
        groups.append(
            ContinuityIssueGroupResponse(
                scope=scope,
                scene_id=scene_id,
                segment_id=segment_id,
                issue_count=len(sorted_grouped_issues),
                high_risk_count=sum(1 for item in sorted_grouped_issues if item.severity == "high"),
                medium_risk_count=sum(1 for item in sorted_grouped_issues if item.severity == "medium"),
                low_risk_count=sum(1 for item in sorted_grouped_issues if item.severity == "low"),
                recommended_actions=recommended_actions,
                issues=sorted_grouped_issues,
            )
        )

    return sorted(
        groups,
        key=lambda item: (
            -(item.high_risk_count),
            -(item.medium_risk_count),
            -(item.low_risk_count),
            item.scene_id,
            item.segment_id,
        ),
    )


def _build_inferred_planned_segments(
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
