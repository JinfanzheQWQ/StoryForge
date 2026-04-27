from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from storyforge.core.io import read_json


def ensure_secondary_segment_execution_contract(story_result) -> None:
    segment_payload = read_json(story_result.segment_plan_path)
    if len(segment_payload) >= 2:
        return

    target_segment = deepcopy(segment_payload[0])
    target_segment_id = str(target_segment["segment_id"])
    other_segment_id = f"{target_segment_id}-alt"

    target_segment["subsegment_index"] = 1
    target_segment["subsegment_count"] = 2

    other_segment = deepcopy(target_segment)
    other_segment["segment_id"] = other_segment_id
    other_segment["title"] = f"{target_segment['title']} / 片段 2"
    other_segment["summary"] = f"{target_segment['summary']}，并延续到第二段测试片段。"
    other_segment["narration"] = other_segment["summary"]
    other_segment["subtitle_lines"] = [other_segment["summary"]]
    other_segment["timed_beats"] = [f"0-6秒：{other_segment['summary']}"]
    other_segment["source_segment_id"] = other_segment_id
    other_segment["subsegment_index"] = 2
    other_segment["subsegment_count"] = 2
    other_segment["motion_plan"] = {
        "scene_motion": f"承接 {target_segment['summary']} 后继续在同一场景母图空间里推进。",
        "beat_progression": f"0-6秒持续拍出：{other_segment['summary']}",
        "camera_path": "延续上一段镜头方向，保持稳定推进。",
        "character_motion": "角色动作连续承接，不跳切到未建立状态。",
        "continuity_guard": "保持同一场景母图空间、同一角色身份和同一运动方向。",
    }
    other_segment["continuity_link"] = {
        "previous_segment_id": target_segment_id,
        "transition_mode": "continue",
        "opening_match": "承接上一段尾部动作状态",
        "carry_over_elements": ["角色动作延续", "场景空间基线"],
        "allowed_changes": "只推进当前片段内部动作，不改变场景基线",
        "transition_reason": "测试夹具追加的第二段执行合同",
    }

    _write_json(story_result.segment_plan_path, [target_segment, other_segment])

    scene_plan_payload = read_json(story_result.scene_plan_path)
    for scene in scene_plan_payload["scenes"]:
        if scene["scene_id"] != target_segment["scene_id"]:
            continue
        scene["segments"] = [deepcopy(target_segment), deepcopy(other_segment)]
        break
    _write_json(story_result.scene_plan_path, scene_plan_payload)

    scene_image_payload = read_json(story_result.scene_images_path)
    if not any(item["segment_id"] == other_segment_id for item in scene_image_payload):
        target_scene_task = deepcopy(scene_image_payload[0])
        target_scene_task["segment_id"] = other_segment_id
        scene_image_payload.append(target_scene_task)
    _write_json(story_result.scene_images_path, scene_image_payload)

    manifest_payload = read_json(story_result.seedance_manifest_path)
    if not any(item["segment_id"] == other_segment_id for item in manifest_payload["clips"]):
        target_clip = deepcopy(manifest_payload["clips"][0])
        target_clip["segment_id"] = other_segment_id
        target_clip["title"] = other_segment["title"]
        target_clip["narration"] = other_segment["narration"]
        target_clip["dialogue_lines"] = list(other_segment.get("dialogue_lines", []))
        target_clip["subtitle_lines"] = list(other_segment.get("subtitle_lines", []))
        target_clip["timed_beats"] = list(other_segment.get("timed_beats", []))
        target_clip["motion_contract"] = deepcopy(other_segment.get("motion_plan", {}))
        target_clip["output_path"] = str(
            Path(target_clip["output_path"]).with_name(f"{other_segment_id}.mp4")
        )
        manifest_payload["clips"].append(target_clip)
    _write_json(story_result.seedance_manifest_path, manifest_payload)


def mark_scene_images_completed(
    story_result,
    *,
    segment_ids: set[str] | None = None,
    base_url: str = "https://example.com",
) -> list[dict[str, object]]:
    scene_image_payload = read_json(story_result.scene_images_path)
    for item in scene_image_payload:
        segment_id = str(item["segment_id"])
        if segment_ids is not None and segment_id not in segment_ids:
            continue
        item["status"] = "completed"
        item["scene_master_frame_url"] = f"{base_url}/{Path(item['scene_master_frame_path']).name}"
        item["scene_master_frame_status"] = "completed"
    _write_json(story_result.scene_images_path, scene_image_payload)
    return scene_image_payload


def mark_seedance_clips_completed(
    story_result,
    *,
    segment_ids: set[str] | None = None,
    base_url: str = "https://example.com",
    download_root: str = "/tmp",
    remote_status: str = "completed",
) -> dict[str, object]:
    manifest_payload = read_json(story_result.seedance_manifest_path)
    for clip in manifest_payload["clips"]:
        segment_id = str(clip["segment_id"])
        if segment_ids is not None and segment_id not in segment_ids:
            continue
        clip["submit_status"] = "completed"
        clip["remote_status"] = remote_status
        clip["video_url"] = f"{base_url}/{segment_id}.mp4"
        clip["downloaded_path"] = str(Path(download_root) / f"{segment_id}.mp4")
    _write_json(story_result.seedance_manifest_path, manifest_payload)
    return manifest_payload


def mark_first_scene_and_video_failed(
    story_result,
    *,
    scene_master_error: str = "boom",
    scene_error: str = "scene failed",
    video_error: str = "video failed",
) -> tuple[str, str]:
    scene_plan_payload = read_json(story_result.scene_plan_path)
    first_scene_id = str(scene_plan_payload["scenes"][0]["scene_id"])
    scene_plan_payload["scenes"][0]["scene_master_frame_status"] = "failed"
    scene_plan_payload["scenes"][0]["scene_master_frame_error"] = scene_master_error
    _write_json(story_result.scene_plan_path, scene_plan_payload)

    scene_manifest_payload = read_json(story_result.scene_images_path)
    first_segment_id = str(scene_manifest_payload[0]["segment_id"])
    scene_manifest_payload[0]["status"] = "failed"
    scene_manifest_payload[0]["error"] = scene_error
    _write_json(story_result.scene_images_path, scene_manifest_payload)

    manifest_payload = read_json(story_result.seedance_manifest_path)
    manifest_payload["clips"][0]["submit_status"] = "failed"
    manifest_payload["clips"][0]["remote_status"] = "failed"
    manifest_payload["clips"][0]["error"] = video_error
    _write_json(story_result.seedance_manifest_path, manifest_payload)
    return first_scene_id, first_segment_id


def mark_rendered_manifest_clips(
    story_result,
    *,
    clip_count: int = 2,
    remote_status: str = "succeeded",
    rendered_dir: Path | None = None,
) -> list[Path]:
    manifest_payload = read_json(story_result.seedance_manifest_path)
    target_dir = rendered_dir or (story_result.output_dir / "rendered")
    target_dir.mkdir(parents=True, exist_ok=True)

    rendered_paths: list[Path] = []
    for index, clip in enumerate(manifest_payload["clips"][:clip_count], start=1):
        clip_path = target_dir / f"clip-{index}.mp4"
        clip_path.write_bytes(b"clip")
        clip["downloaded_path"] = str(clip_path)
        clip["submit_status"] = "completed"
        clip["remote_status"] = remote_status
        rendered_paths.append(clip_path)

    _write_json(story_result.seedance_manifest_path, manifest_payload)
    return rendered_paths


def mark_runtime_character_images_completed(
    project_package,
    *,
    base_url: str = "https://example.com",
) -> None:
    for item in project_package.character_images:
        item.generated_url = f"{base_url}/{Path(item.output_path).name}"
        item.status = "completed"


def mark_runtime_scene_images_completed(
    project_package,
    *,
    segment_ids: set[str] | None = None,
    base_url: str = "https://example.com",
) -> None:
    for task in project_package.scene_images:
        if not _matches_target(task.segment_id, segment_ids):
            continue
        task.scene_master_frame_url = f"{base_url}/{Path(task.scene_master_frame_path).name}"
        task.scene_master_frame_status = "completed"
        task.status = "completed"

    for clip in project_package.seedance_manifest.clips:
        if not _matches_target(clip.segment_id, segment_ids):
            continue
        clip.scene_master_url = clip.scene_master_url or f"{base_url}/{Path(clip.scene_master_path).name}"


def mark_runtime_scene_master_frames_completed(
    project_package,
    *,
    scene_ids: set[str] | None = None,
    base_url: str = "https://example.com",
) -> None:
    for scene in project_package.scenes:
        if not _matches_target(scene.scene_id, scene_ids):
            continue
        scene.scene_master_frame_url = f"{base_url}/{Path(scene.scene_master_frame_path).name}"
        scene.scene_master_frame_status = "completed"

    for task in project_package.scene_images:
        if not _matches_target(task.scene_id, scene_ids):
            continue
        task.scene_master_frame_url = f"{base_url}/{Path(task.scene_master_frame_path).name}"
        task.scene_master_frame_status = "completed"


def mark_runtime_manifest_clips_completed(
    manifest,
    *,
    segment_ids: set[str] | None = None,
    remote_status: str = "succeeded",
    write_bytes: bytes = b"fake mp4 bytes",
) -> list[Path]:
    rendered_paths: list[Path] = []
    for clip in manifest.clips:
        if not _matches_target(clip.segment_id, segment_ids):
            continue
        clip_path = Path(clip.output_path)
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(write_bytes)
        clip.downloaded_path = str(clip_path)
        clip.submit_status = "completed"
        clip.remote_status = remote_status
        rendered_paths.append(clip_path)
    return rendered_paths


def _matches_target(identifier: str, targets: set[str] | None) -> bool:
    if targets is None:
        return True
    return str(identifier) in targets


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
