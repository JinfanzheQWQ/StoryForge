from __future__ import annotations

from pathlib import Path

from storyforge.domains.video.contracts import SeedanceClipTask, SeedanceManifest
from storyforge.integrations.seedance import SeedanceExecutionReport
from storyforge.integrations.seedream import SeedreamExecutionReport


def read_seedream_execution_report(path: Path) -> SeedreamExecutionReport:
    from storyforge.core.io import read_json

    if not path.exists():
        return SeedreamExecutionReport(
            submitted=False,
            generated_count=0,
            failed_count=0,
            note="Seedream character stage has not been executed yet.",
        )
    raw = read_json(path)
    return SeedreamExecutionReport(**raw)


def merge_seedream_execution_reports(
    character_execution: SeedreamExecutionReport,
    scene_execution: SeedreamExecutionReport,
) -> SeedreamExecutionReport:
    return SeedreamExecutionReport(
        submitted=character_execution.submitted or scene_execution.submitted,
        generated_count=character_execution.generated_count + scene_execution.generated_count,
        failed_count=character_execution.failed_count + scene_execution.failed_count,
        note=f"characters: {character_execution.note} | scenes: {scene_execution.note}",
    )


def should_concat_rendered_clips(
    manifest: SeedanceManifest,
    seedance_execution: SeedanceExecutionReport,
    segment_ids: set[str] | None = None,
) -> bool:
    if segment_ids:
        return False
    if not seedance_execution.submitted:
        return False
    if seedance_execution.failed_count > 0 or seedance_execution.pending_count > 0:
        return False
    clip_tasks = resolve_selected_manifest_clips(manifest, segment_ids)
    if not clip_tasks:
        return False

    clip_paths = [Path(clip.downloaded_path or clip.output_path) for clip in clip_tasks]
    return all(path.exists() for path in clip_paths)


def resolve_rendered_manifest_clips(manifest: SeedanceManifest) -> list[SeedanceClipTask]:
    return [
        clip
        for clip in manifest.clips
        if Path(clip.downloaded_path or clip.output_path).exists()
    ]


def should_skip_seedance_after_seedream(
    submit_seedance: bool,
    seedream_execution: SeedreamExecutionReport | None,
) -> bool:
    if not submit_seedance:
        return False
    if seedream_execution is None:
        return True
    if not seedream_execution.submitted:
        return True
    return seedream_execution.failed_count > 0


def validate_manifest_ready_for_video(
    manifest: SeedanceManifest,
    segment_ids: set[str] | None = None,
) -> None:
    clip_tasks = resolve_selected_manifest_clips(manifest, segment_ids)
    missing_scene_segments = [clip.segment_id for clip in clip_tasks if not clip.scene_master_url]
    missing_character_segments = [
        clip.segment_id
        for clip in clip_tasks
        if clip.scene_master_url and not _clip_character_references_ready(clip)
    ]
    if missing_scene_segments or missing_character_segments:
        details: list[str] = []
        if missing_scene_segments:
            details.append("missing scene master: " + ", ".join(missing_scene_segments))
        if missing_character_segments:
            details.append("missing character references: " + ", ".join(missing_character_segments))
        raise ValueError(
            "Video references are not ready for video generation. "
            "Generate scene master and character images first. "
            + "; ".join(details)
        )


def _clip_has_v2_video_references(clip: SeedanceClipTask) -> bool:
    if not clip.scene_master_url:
        return False
    return _clip_character_references_ready(clip)


def _clip_character_references_ready(clip: SeedanceClipTask) -> bool:
    expected_character_count = len([name for name in clip.visible_characters if str(name).strip()])
    if expected_character_count <= 0:
        return True
    return len([url for url in clip.character_image_urls if str(url).strip()]) >= expected_character_count


def resolve_selected_manifest_clips(
    manifest: SeedanceManifest,
    segment_ids: set[str] | None = None,
) -> list[SeedanceClipTask]:
    if not segment_ids:
        return list(manifest.clips)
    selected_clips = [clip for clip in manifest.clips if clip.segment_id in segment_ids]
    missing_segments = sorted(segment_ids - {clip.segment_id for clip in selected_clips})
    if missing_segments:
        raise ValueError(
            "Requested video segments are not present in seedance_manifest.json: "
            + ", ".join(missing_segments)
        )
    return selected_clips
