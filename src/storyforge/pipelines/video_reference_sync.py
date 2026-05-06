from __future__ import annotations

from pathlib import Path

from storyforge.domains.video.contracts import SceneImageTask, SeedanceClipTask, SeedanceManifest


def resolve_selected_segment_ids(
    project_package,
    *,
    segment_id: str | None = None,
    scene_id: str | None = None,
    segment_ids: set[str] | None = None,
) -> set[str] | None:
    resolved_segment_id = str(segment_id or "").strip()
    resolved_scene_id = str(scene_id or "").strip()
    resolved_segment_ids = {
        str(item).strip()
        for item in (segment_ids or set())
        if str(item).strip()
    }
    if resolved_segment_id and resolved_scene_id:
        raise ValueError("segment_id and scene_id cannot be used together.")
    if resolved_segment_id and resolved_segment_ids:
        raise ValueError("segment_id and segment_ids cannot be used together.")
    if resolved_segment_id:
        return {resolved_segment_id}
    if resolved_segment_ids and not resolved_scene_id:
        known_segment_ids = {
            str(segment.segment_id)
            for segment in project_package.segments
            if str(segment.segment_id).strip()
        }
        unknown_segment_ids = sorted(resolved_segment_ids - known_segment_ids)
        if unknown_segment_ids:
            raise ValueError(
                "Requested segment_ids are not present in segment_plan.json: "
                + ", ".join(unknown_segment_ids)
            )
        return resolved_segment_ids
    if not resolved_scene_id:
        return None

    target_scene = next(
        (scene for scene in project_package.scenes if scene.scene_id == resolved_scene_id),
        None,
    )
    if target_scene is None:
        raise ValueError(
            f"Requested scene is not present in scene_plan.json: {resolved_scene_id}"
        )
    selected_segment_ids = {
        str(segment.segment_id)
        for segment in target_scene.segments
        if str(segment.segment_id).strip()
    }
    if not selected_segment_ids:
        raise ValueError(
            f"Requested scene has no executable segments in scene_plan.json: {resolved_scene_id}"
        )
    if not resolved_segment_ids:
        return selected_segment_ids
    unknown_segment_ids = sorted(resolved_segment_ids - selected_segment_ids)
    if unknown_segment_ids:
        raise ValueError(
            "Requested segment_ids do not belong to the selected scene: "
            + ", ".join(unknown_segment_ids)
        )
    return resolved_segment_ids


def sync_v2_seedance_references(manifest: SeedanceManifest, project_package: object) -> None:
    scene_images = list(getattr(project_package, "scene_images", []) or [])
    sync_cross_scene_reused_master_frames(
        list(getattr(project_package, "scenes", []) or []),
        scene_images,
    )
    sync_scene_master_references(scene_images, manifest)
    scene_by_segment = {item.segment_id: item for item in scene_images}
    scene_by_id = _best_scene_master_task_by_scene(scene_images)
    scene_contract_by_id = {
        getattr(scene, "scene_id", ""): scene
        for scene in getattr(project_package, "scenes", []) or []
        if getattr(scene, "scene_id", "")
    }
    character_url_by_path = {
        item.output_path: item.generated_url
        for item in getattr(project_package, "character_images", [])
        if getattr(item, "output_path", "") and getattr(item, "generated_url", "")
    }
    character_url_by_name = {
        item.character_name: item.generated_url
        for item in getattr(project_package, "character_images", [])
        if getattr(item, "character_name", "") and getattr(item, "generated_url", "")
    }
    for clip in manifest.clips:
        scene_task = scene_by_segment.get(clip.segment_id) or scene_by_id.get(clip.scene_id)
        if scene_task is not None:
            clip.scene_master_url = clip.scene_master_url or scene_task.scene_master_frame_url
            clip.scene_master_path = clip.scene_master_path or scene_task.scene_master_frame_path
        scene_contract = scene_contract_by_id.get(clip.scene_id)
        if scene_contract is not None:
            clip.scene_master_url = clip.scene_master_url or getattr(scene_contract, "scene_master_frame_url", "")
            clip.scene_master_path = clip.scene_master_path or getattr(scene_contract, "scene_master_frame_path", "")
        resolved_character_urls = [
            character_url_by_path.get(path, "")
            for path in clip.character_image_paths
        ]
        if not any(resolved_character_urls):
            resolved_character_urls = [
                character_url_by_name.get(name, "")
                for name in clip.visible_characters
            ]
        resolved_character_urls = [url for url in resolved_character_urls if url]
        if resolved_character_urls:
            clip.character_image_urls = resolved_character_urls


def sync_cross_scene_reused_master_frames(
    scenes: list[object],
    scene_images: list[SceneImageTask],
) -> None:
    scene_by_id = {
        getattr(scene, "scene_id", ""): scene
        for scene in scenes
        if getattr(scene, "scene_id", "")
    }
    for task in scene_images:
        scene = scene_by_id.get(task.scene_id)
        if scene is None:
            continue
        task.scene_master_frame_url = task.scene_master_frame_url or getattr(scene, "scene_master_frame_url", "")
        task.scene_master_frame_path = task.scene_master_frame_path or getattr(scene, "scene_master_frame_path", "")
        task.scene_master_frame_status = _prefer_nondefault_status(
            task.scene_master_frame_status,
            getattr(scene, "scene_master_frame_status", ""),
        )
        if getattr(scene, "scene_master_frame_url", ""):
            task.status = _prefer_nondefault_status(task.status, "completed")


def apply_previous_scene_master_reference(
    scene: object,
    previous_scene: object | None,
) -> None:
    if previous_scene is None:
        return
    if not _scene_allows_previous_master_reference(scene):
        return
    existing_references = [
        str(item or "").strip()
        for item in list(getattr(scene, "scene_master_reference_images", []) or [])
        if str(item or "").strip()
    ]
    if existing_references:
        scene.scene_master_reference_images = existing_references[:1]
        return
    previous_url = str(getattr(previous_scene, "scene_master_frame_url", "") or "").strip()
    if previous_url:
        scene.scene_master_reference_images = [previous_url]


def reset_copied_previous_scene_master(
    scene: object,
    previous_scene: object | None,
) -> None:
    if previous_scene is None:
        return
    if not _scene_allows_previous_master_reference(scene):
        return
    previous_url = str(getattr(previous_scene, "scene_master_frame_url", "") or "").strip()
    current_url = str(getattr(scene, "scene_master_frame_url", "") or "").strip()
    if previous_url and current_url == previous_url:
        scene.scene_master_frame_url = ""
        scene.scene_master_frame_status = "planned"
        scene.scene_master_frame_error = ""
        scene.scene_master_request_info = {}
    previous_path = str(getattr(previous_scene, "scene_master_frame_path", "") or "").strip()
    current_path = str(getattr(scene, "scene_master_frame_path", "") or "").strip()
    if previous_path and (not current_path or current_path == previous_path):
        scene.scene_master_frame_path = _derive_scene_master_path(
            scene_id=str(getattr(scene, "scene_id", "") or "").strip(),
            source_path=previous_path,
        )


def sync_scene_master_references(
    scene_images: list[SceneImageTask],
    manifest: SeedanceManifest | None = None,
) -> None:
    scene_master_by_scene = _best_scene_master_task_by_scene(scene_images)
    for task in scene_images:
        scene_master = scene_master_by_scene.get(task.scene_id)
        if scene_master is None or scene_master is task:
            continue
        task.scene_master_frame_url = task.scene_master_frame_url or scene_master.scene_master_frame_url
        task.scene_master_frame_path = task.scene_master_frame_path or scene_master.scene_master_frame_path
        task.scene_master_frame_status = _prefer_nondefault_status(
            task.scene_master_frame_status,
            scene_master.scene_master_frame_status,
        )
        task.status = _prefer_nondefault_status(task.status, scene_master.status)
    if manifest is None:
        return
    task_by_segment = {task.segment_id: task for task in scene_images}
    for clip in manifest.clips:
        scene_task = task_by_segment.get(clip.segment_id) or scene_master_by_scene.get(clip.scene_id)
        if scene_task is None:
            continue
        clip.scene_master_url = clip.scene_master_url or scene_task.scene_master_frame_url
        clip.scene_master_path = clip.scene_master_path or scene_task.scene_master_frame_path


def sync_seedance_tail_frame_handoffs(
    manifest: SeedanceManifest,
    scenes: list[object] | None = None,
) -> None:
    previous_by_scene: dict[str, SeedanceClipTask] = {}
    scene_by_id = {
        getattr(scene, "scene_id", ""): scene
        for scene in (scenes or [])
        if getattr(scene, "scene_id", "")
    }
    previous_timeline_clip: SeedanceClipTask | None = None
    for clip in manifest.clips:
        scene_id = str(clip.scene_id or "").strip()
        previous_clip: SeedanceClipTask | None = None
        if clip.previous_clip_segment_id:
            previous_clip = next(
                (item for item in manifest.clips if item.segment_id == clip.previous_clip_segment_id),
                None,
            )
        elif scene_id:
            previous_clip = previous_by_scene.get(scene_id)
            if previous_clip is None and _scene_allows_previous_tail_frame(scene_by_id.get(scene_id)):
                previous_clip = previous_timeline_clip
        if previous_clip is not None:
            if previous_clip.segment_id and not clip.previous_clip_segment_id:
                clip.previous_clip_segment_id = previous_clip.segment_id
            if previous_clip.video_url and not clip.previous_clip_video_url:
                clip.previous_clip_video_url = previous_clip.video_url
            if previous_clip.last_frame_url and not clip.first_frame_url:
                clip.first_frame_url = previous_clip.last_frame_url
        if scene_id:
            previous_by_scene[scene_id] = clip
        previous_timeline_clip = clip


def _scene_allows_previous_master_reference(scene: object) -> bool:
    contract = getattr(scene, "scene_transition_contract", None)
    mode = str(getattr(contract, "scene_spatial_continuity_mode", "") or "").strip().lower()
    if mode in {
        "same_space_progression",
        "same_location_new_angle",
        "time_jump_same_location",
    }:
        return True
    return False


def _derive_scene_master_path(*, scene_id: str, source_path: str) -> str:
    if not scene_id:
        return source_path
    path = Path(source_path)
    suffix = path.suffix or ".png"
    return str(path.with_name(f"{scene_id}_master{suffix}"))


def _best_scene_master_task_by_scene(
    scene_images: list[SceneImageTask],
) -> dict[str, SceneImageTask]:
    best_by_scene: dict[str, SceneImageTask] = {}
    for task in scene_images:
        scene_id = str(task.scene_id or "").strip()
        if not scene_id:
            continue
        current = best_by_scene.get(scene_id)
        if current is None or _scene_master_task_score(task) > _scene_master_task_score(current):
            best_by_scene[scene_id] = task
    return best_by_scene


def _scene_master_task_score(task: SceneImageTask) -> tuple[int, int, int]:
    return (
        1 if task.scene_master_frame_url else 0,
        1 if task.scene_master_frame_path else 0,
        1 if task.scene_master_frame_status not in {"", "planned"} else 0,
    )


def _scene_allows_previous_tail_frame(scene: object | None) -> bool:
    if scene is None:
        return False
    contract = getattr(scene, "scene_transition_contract", None)
    mode = str(getattr(contract, "scene_spatial_continuity_mode", "") or "").strip().lower()
    if mode in {
        "same_space_progression",
        "same_location_new_angle",
        "time_jump_same_location",
    }:
        return True
    return False


def _prefer_nondefault_status(preferred: object, fallback: object) -> str:
    preferred_value = str(preferred or "planned")
    fallback_value = str(fallback or "planned")
    if preferred_value != "planned":
        return preferred_value
    return fallback_value
