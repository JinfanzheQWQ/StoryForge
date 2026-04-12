from __future__ import annotations

from pathlib import Path

from storyforge.domains.video.contracts import SeedanceManifest
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
) -> bool:
    if not seedance_execution.submitted:
        return False
    if seedance_execution.failed_count > 0 or seedance_execution.pending_count > 0:
        return False
    if not manifest.clips:
        return False

    clip_paths = [Path(clip.downloaded_path or clip.output_path) for clip in manifest.clips]
    return all(path.exists() for path in clip_paths)


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


def validate_manifest_ready_for_video(manifest: SeedanceManifest) -> None:
    missing_segments = [
        clip.segment_id
        for clip in manifest.clips
        if not clip.start_frame_url or not clip.end_frame_url
    ]
    if missing_segments:
        raise ValueError(
            "Scene frames are not ready for video generation. Generate scene images first. "
            f"Missing segments: {', '.join(missing_segments)}"
        )
