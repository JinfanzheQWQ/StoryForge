from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import quote
import re

from storyforge.api.schemas import (
    ArtifactItem,
    CharacterArtifactItem,
    ContinuityIssueDetailResponse,
    ContinuityIssueGroupResponse,
    ContinuityIssueSummaryResponse,
    ContinuitySummaryResponse,
    PlannedSegmentArtifactResponse,
    PromptReferenceBindingResponse,
    SceneArtifactResponse,
    SubmittedRequestResponse,
    TaskArtifactsResponse,
)
from storyforge.application.tasks import TaskRecord
from storyforge.core.io import read_json
from storyforge.domains.video.contracts import SceneBible, SceneTransitionContract, VideoScene, VideoSegment
from storyforge.domains.video.text_rules import (
    ACTION_STEP_SPLIT_PATTERN,
    TIMED_BEAT_PREFIX_PATTERN,
    extract_progression_signal_terms,
    normalize_similarity_text,
    progress_text_too_generic,
)
from storyforge.pipelines.video_planning import (
    load_scene_image_task_map,
    load_seedance_clip_map,
    load_video_segment_plan,
)


TIMED_BEAT_PATTERN = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒"
)


def _scene_bible_to_dict(scene_bible: SceneBible) -> dict[str, object]:
    return {
        "location": scene_bible.location,
        "time_window": scene_bible.time_window,
        "weather": scene_bible.weather,
        "lighting": scene_bible.lighting,
        "dominant_palette": scene_bible.dominant_palette,
        "background_anchors": scene_bible.background_anchors,
        "fixed_props": scene_bible.fixed_props,
        "spatial_layout": scene_bible.spatial_layout,
        "character_blocking": scene_bible.character_blocking,
        "continuity_notes": scene_bible.continuity_notes,
    }


def _scene_transition_contract_to_dict(contract: SceneTransitionContract) -> dict[str, object]:
    return {
        "previous_scene_id": contract.previous_scene_id,
        "transition_mode": contract.transition_mode,
        "scene_spatial_continuity_mode": contract.scene_spatial_continuity_mode,
        "previous_scene_exit_state": contract.previous_scene_exit_state,
        "next_scene_entry_match": contract.next_scene_entry_match,
        "shared_environment_anchors": contract.shared_environment_anchors,
        "spatial_relation_to_previous": contract.spatial_relation_to_previous,
        "camera_handoff": contract.camera_handoff,
        "bridge_action": contract.bridge_action,
        "carry_over_elements": contract.carry_over_elements,
        "screen_direction_policy": contract.screen_direction_policy,
        "visual_bridge": contract.visual_bridge,
        "audio_bridge": contract.audio_bridge,
        "prop_bridge": contract.prop_bridge,
        "action_bridge": contract.action_bridge,
        "allowed_environment_changes": contract.allowed_environment_changes,
        "forbidden_drift": contract.forbidden_drift,
        "transition_focus_seconds": contract.transition_focus_seconds,
    }


def _segment_action_node_budget(duration_seconds: int) -> int:
    if duration_seconds <= 7:
        return 2
    if duration_seconds <= 9:
        return 3
    return 4


def _estimate_segment_action_node_count(timed_beats: list[str]) -> int:
    total_nodes = 0
    for beat in timed_beats:
        description = TIMED_BEAT_PREFIX_PATTERN.sub("", str(beat or "").strip())
        if not description:
            continue
        clause_count = 0
        for raw_clause in ACTION_STEP_SPLIT_PATTERN.split(description):
            clause = str(raw_clause or "").strip(" ，。；;")
            if not clause:
                continue
            normalized = normalize_similarity_text(clause)
            if len(normalized) < 4:
                continue
            if progress_text_too_generic(clause) and not extract_progression_signal_terms(clause):
                continue
            clause_count += 1
        total_nodes += max(1, clause_count)
    return max(1, total_nodes)


def _timed_beat_end_seconds(timed_beats: list[str]) -> float | None:
    max_end_seconds: float | None = None
    for beat in timed_beats:
        match = TIMED_BEAT_PATTERN.search(str(beat or ""))
        if not match:
            continue
        end_seconds = float(match.group("end"))
        max_end_seconds = end_seconds if max_end_seconds is None else max(max_end_seconds, end_seconds)
    return max_end_seconds


def _build_segment_diagnostics(segment: VideoSegment, continuity_group: object | None = None) -> dict[str, object]:
    duration_seconds = int(segment.duration_seconds or 0)
    timed_beats = list(segment.timed_beats or [])
    action_node_count = _estimate_segment_action_node_count(timed_beats) if timed_beats else 0
    action_node_budget = _segment_action_node_budget(duration_seconds) if duration_seconds else 0
    timed_beat_end_seconds = _timed_beat_end_seconds(timed_beats)
    missing_tail_seconds = (
        round(max(0.0, float(duration_seconds) - timed_beat_end_seconds), 2)
        if timed_beat_end_seconds is not None and duration_seconds
        else None
    )
    risk_types: list[str] = []
    if action_node_budget and action_node_count > action_node_budget:
        risk_types.append("动作容量过载")
    if missing_tail_seconds is not None and missing_tail_seconds > 0.2:
        risk_types.append("尾部节拍留空")
    if getattr(segment, "subsegment_count", 1) > 1:
        risk_types.append("拆分子段")
    if continuity_group and getattr(continuity_group, "issue_count", 0):
        risk_types.append("连续性风险")
    status = "warning" if risk_types else "ok"
    planner_warning_source = ""
    if action_node_budget and action_node_count > action_node_budget:
        planner_warning_source = "action_capacity"
    elif missing_tail_seconds is not None and missing_tail_seconds > 0.2:
        planner_warning_source = "timed_beats"
    elif getattr(segment, "subsegment_count", 1) > 1:
        planner_warning_source = "subsegment_split"
    repair_source = "continuity_report" if continuity_group and getattr(continuity_group, "issue_count", 0) else ""
    return {
        "status": status,
        "risk_type": risk_types[0] if risk_types else "",
        "risk_types": risk_types,
        "action_node_count": action_node_count,
        "action_node_budget": action_node_budget,
        "duration_auto_expanded_from": None,
        "duration_seconds": duration_seconds,
        "timed_beat_count": len(timed_beats),
        "timed_beat_end_seconds": timed_beat_end_seconds,
        "missing_tail_seconds": missing_tail_seconds,
        "subsegment_index": int(getattr(segment, "subsegment_index", 1) or 1),
        "subsegment_count": int(getattr(segment, "subsegment_count", 1) or 1),
        "repair_source": repair_source,
        "planner_warning_source": planner_warning_source,
    }


def _build_inferred_segment_diagnostics(segment: PlannedSegmentArtifactResponse) -> dict[str, object]:
    duration_seconds = int(segment.duration_seconds or 0)
    return {
        "status": "ok",
        "risk_type": "",
        "risk_types": [],
        "action_node_count": 0,
        "action_node_budget": _segment_action_node_budget(duration_seconds) if duration_seconds else 0,
        "duration_auto_expanded_from": None,
        "duration_seconds": duration_seconds,
        "timed_beat_count": 0,
        "timed_beat_end_seconds": None,
        "missing_tail_seconds": None,
        "subsegment_index": 1,
        "subsegment_count": 1,
        "repair_source": "",
        "planner_warning_source": "",
    }

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
    scenes = _collect_scene_artifacts(
        output_dir=output_dir,
        output_root=resolved_output_root,
        scene_frames=scene_frames,
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
        scenes=scenes,
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


def _collect_scene_artifacts(
    *,
    output_dir: Path,
    output_root: Path,
    scene_frames: list[ArtifactItem],
) -> list[SceneArtifactResponse]:
    if not (output_dir / "scene_plan.json").exists():
        return []
    try:
        plan = load_video_segment_plan(output_dir)
    except Exception:
        return []

    scene_task_by_scene: dict[str, object] = {}
    for task in load_scene_image_task_map(output_dir).values():
        scene_id = str(getattr(task, "scene_id", "") or "").strip()
        if not scene_id:
            continue
        current = scene_task_by_scene.get(scene_id)
        if current is None or _scene_task_master_score(task) > _scene_task_master_score(current):
            scene_task_by_scene[scene_id] = task

    scene_frame_map = {item.path: item for item in scene_frames}
    scene_items: list[SceneArtifactResponse] = []
    for scene in getattr(plan, "scenes", []):
        scene_task = scene_task_by_scene.get(scene.scene_id)
        scene_master_frame = _resolve_scene_master_artifact(
            scene=scene,
            scene_task=scene_task,
            output_root=output_root,
            scene_frame_map=scene_frame_map,
        )
        scene_items.append(
            SceneArtifactResponse(
                scene_id=scene.scene_id,
                chapter_number=int(getattr(scene, "chapter_number", 0) or 0),
                title=str(getattr(scene, "title", "") or ""),
                summary=str(getattr(scene, "summary", "") or ""),
                scene_anchor=str(getattr(scene, "scene_anchor", "") or ""),
                scene_bible=_scene_bible_to_dict(scene.scene_bible),
                scene_transition_contract=_scene_transition_contract_to_dict(scene.scene_transition_contract),
                involved_characters=list(getattr(scene, "involved_characters", []) or []),
                covered_event_ids=list(getattr(scene, "covered_event_ids", []) or []),
                covered_event_summaries=list(getattr(scene, "covered_event_summaries", []) or []),
                segment_count=len(getattr(scene, "segments", []) or []),
                scene_master_frame_status=str(getattr(scene, "scene_master_frame_status", "") or ""),
                scene_master_frame_error=str(getattr(scene, "scene_master_frame_error", "") or ""),
                scene_master_frame_prompt=str(getattr(scene, "scene_master_frame_prompt", "") or ""),
                scene_master_frame=scene_master_frame,
            )
        )
    return scene_items


def _collect_character_current_artifacts(
    directory: Path,
    output_root: Path,
) -> list[ArtifactItem]:
    if not directory.exists():
        return []
    items: list[ArtifactItem] = []
    for path in _sorted_paths(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        items.append(_to_artifact_item(path, output_root))
    return items

def _collect_character_artifacts(
    *,
    output_dir: Path,
    output_root: Path,
) -> list[CharacterArtifactItem]:
    file_artifacts = _collect_character_current_artifacts(
        output_dir / "assets" / "characters",
        output_root,
    )
    manifest_map = _load_character_manifest_map(output_dir)
    character_items: list[CharacterArtifactItem] = []
    seen_paths: set[str] = set()

    for manifest_item in manifest_map.values():
        item = _build_character_artifact_from_manifest_item(
            manifest_item,
            output_dir=output_dir,
            output_root=output_root,
        )
        if item is None:
            continue
        seen_paths.add(item.path)
        character_items.append(item)

    for artifact in file_artifacts:
        if artifact.path in seen_paths:
            continue
        character_items.append(_build_character_artifact_from_file(artifact, {}))
    return character_items


def _build_character_artifact_from_file(
    artifact: ArtifactItem,
    manifest_item: dict[str, object],
) -> CharacterArtifactItem:
    return CharacterArtifactItem(
        **artifact.model_dump(),
        character_name=str(manifest_item.get("character_name", "") or ""),
        prompt=str(manifest_item.get("prompt", "") or ""),
        consistency_notes=str(manifest_item.get("consistency_notes", "") or ""),
        provider=str(manifest_item.get("provider", "") or ""),
        status=str(manifest_item.get("status", "") or ""),
        image_kind=str(manifest_item.get("image_kind", "") or ""),
        candidate_url=None,
        candidate_path="",
        character_request=_build_submitted_request_response(manifest_item.get("request_info", {})),
        error=str(manifest_item.get("error", "") or ""),
    )


def _build_character_artifact_from_manifest_item(
    manifest_item: dict[str, object],
    *,
    output_dir: Path,
    output_root: Path,
) -> CharacterArtifactItem | None:
    artifact = _manifest_output_artifact_item(
        manifest_item.get("output_path"),
        manifest_item.get("generated_url"),
        output_dir=output_dir,
        output_root=output_root,
    )
    if artifact is None:
        return None
    item = _build_character_artifact_from_file(artifact, manifest_item)
    candidate_url = _resolve_manifest_artifact_url(
        manifest_item.get("candidate_output_path"),
        output_dir=output_dir,
        output_root=output_root,
    ) or str(manifest_item.get("candidate_generated_url", "") or "") or None
    return item.model_copy(
        update={
            "candidate_url": candidate_url,
            "candidate_path": str(manifest_item.get("candidate_output_path", "") or ""),
        }
    )


def _manifest_output_artifact_item(
    raw_path: object,
    raw_url: object,
    *,
    output_dir: Path,
    output_root: Path,
) -> ArtifactItem | None:
    path_text = str(raw_path or "").strip()
    resolved_path: Path | None = None
    if path_text:
        path = Path(path_text)
        resolved_path = (output_dir / path).resolve() if not path.is_absolute() else path.resolve()
        if resolved_path.exists() and resolved_path.is_file():
            return _to_artifact_item(resolved_path, output_root)
    url = str(raw_url or "").strip() or None
    if not path_text and not url:
        return None
    display_name = (resolved_path.name if resolved_path is not None else "") or str(raw_path or "").strip() or "character.png"
    return ArtifactItem(
        name=display_name,
        path=str(resolved_path or raw_path or ""),
        url=url,
        kind="image",
    )



def _resolve_manifest_artifact_url(
    raw_path: object,
    *,
    output_dir: Path,
    output_root: Path,
) -> str | None:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = (output_dir / path).resolve()
    else:
        path = path.resolve()
    if not path.exists() or not path.is_file():
        return None
    try:
        return _to_artifact_item(path, output_root).url
    except ValueError:
        return None

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
    revision = int(resolved_path.stat().st_mtime_ns)
    return ArtifactItem(
        name=path.name,
        path=str(resolved_path),
        url=f"/outputs/{encoded_path}?v={revision}",
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
        if not task.scene_id:
            continue
        current = scene_task_by_scene.get(task.scene_id)
        if current is None or _scene_task_master_score(task) > _scene_task_master_score(current):
            scene_task_by_scene[task.scene_id] = task
    scene_frame_map = {item.path: item for item in scene_frames}
    rendered_clip_map = {item.path: item for item in rendered_clips}
    character_image_map = {item.path: item for item in character_images}
    scene_master_map = {}
    for scene in getattr(plan, "scenes", []):
        scene_task = scene_task_by_scene.get(scene.scene_id)
        scene_master_map[scene.scene_id] = _resolve_scene_master_artifact(
            scene=scene,
            scene_task=scene_task,
            output_root=output_root,
            scene_frame_map=scene_frame_map,
        )
    scene_request_map = {
        scene.scene_id: (
            _build_submitted_request_response(
                getattr(scene, "scene_master_request_info", {}),
            )
            or _build_derived_scene_master_request_response(
                prompt_text=str(getattr(scene, "scene_master_frame_prompt", "") or ""),
                scene_master_frame=scene_master_map.get(scene.scene_id),
                reference_images=list(getattr(scene, "scene_master_reference_images", []) or []),
                provider=str(getattr(scene_task_by_scene.get(scene.scene_id), "provider", "") or "seedream"),
            )
        )
        for scene in getattr(plan, "scenes", [])
    }
    scene_by_id: dict[str, VideoScene] = {
        scene.scene_id: scene
        for scene in getattr(plan, "scenes", [])
    }
    continuity_lookup = _build_continuity_segment_lookup(output_dir)
    planned_segments: list[PlannedSegmentArtifactResponse] = []

    for segment in segments:
        scene = scene_by_id.get(segment.scene_id)
        scene_task = scene_task_map.get(segment.segment_id)
        scene_master_task = scene_task_by_scene.get(segment.scene_id)
        clip_task = clip_map.get(segment.segment_id)
        rendered_clip = _resolve_rendered_clip_artifact(clip_task, output_root, rendered_clip_map)
        character_references = _resolve_clip_character_reference_artifacts(
            clip_task,
            output_root,
            character_image_map,
        )
        has_scene_master_url = bool(
            (scene and getattr(scene, "scene_master_frame_url", ""))
            or (scene_task and getattr(scene_task, "scene_master_frame_url", ""))
            or (scene_master_task and getattr(scene_master_task, "scene_master_frame_url", ""))
            or (clip_task and getattr(clip_task, "scene_master_url", ""))
        )
        scene_ready = bool(
            has_scene_master_url
            and _clip_character_references_ready(clip_task, character_references)
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
                scene_anchor=(scene.scene_anchor if scene else segment.scene_anchor),
                scene_bible=(
                    _scene_bible_to_dict(scene.scene_bible)
                    if scene
                    else _scene_bible_to_dict(segment.scene_bible)
                ),
                scene_transition_contract=(
                    _scene_transition_contract_to_dict(scene.scene_transition_contract)
                    if scene
                    else {}
                ),
                scene_spatial_continuity_mode=(
                    scene.scene_transition_contract.scene_spatial_continuity_mode
                    if scene
                    else "uncertain"
                ),
                scene_master_frame_status=(scene.scene_master_frame_status if scene else ""),
                scene_master_frame_error=(scene.scene_master_frame_error if scene else ""),
                covered_event_ids=(scene.covered_event_ids if scene else []),
                covered_event_summaries=(scene.covered_event_summaries if scene else []),
                title=segment.title,
                summary=segment.summary,
                chapter_number=segment.chapter_number,
                duration_seconds=segment.duration_seconds,
                scene_master_frame=scene_master_map.get(segment.scene_id),
                rendered_clip=rendered_clip,
                scene_master_frame_prompt=(
                    scene_task.scene_master_frame_prompt
                    if scene_task
                    else (scene_master_task.scene_master_frame_prompt if scene_master_task else "")
                ),
                video_prompt=clip_task.prompt if clip_task else "",
                submitted_video_prompt=clip_task.submitted_prompt if clip_task else "",
                seedance_motion_prompt=_extract_seedance_motion_prompt(
                    str((clip_task.submitted_prompt if clip_task else "") or (clip_task.prompt if clip_task else "") or ""),
                ),
                motion_plan=_build_motion_plan_response(segment),
                motion_contract=dict(getattr(clip_task, "motion_contract", {}) or {}),
                first_frame_url=getattr(clip_task, "first_frame_url", "") if clip_task else "",
                last_frame_url=getattr(clip_task, "last_frame_url", "") if clip_task else "",
                previous_clip_segment_id=getattr(clip_task, "previous_clip_segment_id", "") if clip_task else "",
                previous_clip_video_url=getattr(clip_task, "previous_clip_video_url", "") if clip_task else "",
                character_references=character_references,
                scene_master_reference_images=(
                    list(scene.scene_master_reference_images)
                    if scene
                    else list(getattr(scene_task, "reference_images", []) or [])
                ),
                diagnostics=_build_segment_diagnostics(
                    segment,
                    continuity_lookup.get(segment.segment_id),
                ),
                submitted_prompt_variant=clip_task.submit_variant if clip_task else "",
                submitted_reference_bindings=_build_prompt_reference_bindings(
                    clip_task.submitted_reference_bindings if clip_task else [],
                ),
                scene_master_frame_request=scene_request_map.get(segment.scene_id),
                video_request=(
                    _build_submitted_request_response(
                        clip_task.submitted_request_info if clip_task else {},
                    )
                ),
                scene_ready=scene_ready,
                video_ready=video_ready,
            )
        )
    return planned_segments




def _build_continuity_segment_lookup(output_dir: Path) -> dict[str, object]:
    report_path = output_dir / "continuity_report.json"
    if not report_path.exists():
        return {}
    try:
        _, _, _, segment_groups = _collect_continuity_report(
            output_dir=output_dir,
            output_root=output_dir,
        )
    except Exception:
        return {}
    return {group.segment_id: group for group in segment_groups if group.segment_id}


def _build_motion_plan_response(segment: VideoSegment) -> dict[str, str]:
    motion_plan = getattr(segment, "motion_plan", None)
    if motion_plan is None:
        return {}
    if isinstance(motion_plan, dict):
        payload = motion_plan
    elif hasattr(motion_plan, "__dict__"):
        payload = vars(motion_plan)
    else:
        payload = {
            key: getattr(motion_plan, key, "")
            for key in (
                "scene_motion",
                "beat_progression",
                "camera_path",
                "character_motion",
                "continuity_guard",
            )
        }
    return {
        key: str(payload.get(key, "") or "").strip()
        for key in (
            "scene_motion",
            "beat_progression",
            "camera_path",
            "character_motion",
            "continuity_guard",
        )
        if str(payload.get(key, "") or "").strip()
    }


def _extract_seedance_motion_prompt(prompt: str) -> str:
    lines: list[str] = []
    capture_prefixes = (
        "参考图绑定",
        "- 图片",
        "画面必须按",
        "画面推进",
        "插入镜头",
        "角色变化",
        "跨场承接",
        "视觉过桥",
        "方向：",
        "音频承接",
    )
    for raw_line in str(prompt or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in capture_prefixes):
            lines.append(line)
    return "\n".join(lines)


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


def _build_derived_scene_master_request_response(
    *,
    prompt_text: str,
    scene_master_frame: ArtifactItem | None,
    reference_images: list[str],
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
            "reference_images": reference_images,
        },
        reference_bindings=[
            PromptReferenceBindingResponse(
                label=f"图片{index}",
                kind="previous_scene_master",
                description="上一场场景母图参考，仅用于同一空间或同地点连续性。",
                url=url,
                path=url,
            )
            for index, url in enumerate(reference_images, start=1)
            if str(url or "").strip()
        ],
    )


def _clip_character_references_ready(clip_task, character_references: list[ArtifactItem] | None = None) -> bool:
    if clip_task is None:
        return False
    expected_count = len(
        [name for name in getattr(clip_task, "visible_characters", []) if str(name).strip()]
    )
    if expected_count <= 0:
        return True
    if character_references and len(character_references) >= expected_count:
        return True
    return len(
        [url for url in getattr(clip_task, "character_image_urls", []) if str(url).strip()]
    ) >= expected_count


def _scene_task_master_score(task) -> tuple[int, int, int]:
    return (
        1 if getattr(task, "scene_master_frame_url", "") else 0,
        1 if getattr(task, "scene_master_frame_path", "") else 0,
        1 if getattr(task, "scene_master_frame_status", "") not in {"", "planned"} else 0,
    )


def _resolve_scene_master_artifact(
    *,
    scene,
    scene_task,
    output_root: Path,
    scene_frame_map: dict[str, ArtifactItem],
) -> ArtifactItem | None:
    for raw_path in (
        getattr(scene, "scene_master_frame_path", ""),
        getattr(scene_task, "scene_master_frame_path", "") if scene_task is not None else "",
    ):
        artifact = _resolve_manifest_artifact(str(raw_path or ""), output_root, scene_frame_map)
        if artifact is not None:
            return artifact
    url = str(
        getattr(scene, "scene_master_frame_url", "")
        or (getattr(scene_task, "scene_master_frame_url", "") if scene_task is not None else "")
        or ""
    ).strip()
    if not url:
        return None
    path_text = str(
        getattr(scene, "scene_master_frame_path", "")
        or (getattr(scene_task, "scene_master_frame_path", "") if scene_task is not None else "")
        or ""
    ).strip()
    return ArtifactItem(
        name=Path(path_text).name if path_text else f"{getattr(scene, 'scene_id', '') or 'scene'}_master.png",
        path=path_text,
        url=url,
        kind="image",
    )


def _resolve_clip_character_reference_artifacts(
    clip_task,
    output_root: Path,
    character_image_map: dict[str, ArtifactItem],
) -> list[ArtifactItem]:
    if clip_task is None:
        return []
    artifacts: list[ArtifactItem] = []
    for raw_path in getattr(clip_task, "character_image_paths", []):
        artifact = _resolve_manifest_artifact(str(raw_path or ""), output_root, character_image_map)
        if artifact is not None:
            artifacts.append(artifact)
    return artifacts


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
        segment_id = _segment_id_from_asset_name(item.name)
        segment = segment_map.setdefault(
            segment_id,
            PlannedSegmentArtifactResponse(
                segment_id=segment_id,
                title=segment_id or item.name,
                chapter_number=0,
            ),
        )
        segment.scene_master_frame = item
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
        segment.scene_ready = segment.scene_master_frame is not None
        segment.video_ready = segment.rendered_clip is not None
        segment.diagnostics = _build_inferred_segment_diagnostics(segment)
    return sorted(segment_map.values(), key=lambda item: item.segment_id)


def _segment_id_from_asset_name(name: str) -> str:
    return name.rsplit(".", 1)[0].removesuffix("_master")
