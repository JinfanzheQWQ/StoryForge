from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

from storyforge.domains.video.contracts import SeedanceManifest


def build_concat_list(manifest: SeedanceManifest) -> str:
    return "".join(
        f"file '{clip.downloaded_path or clip.output_path}'\n"
        for clip in manifest.clips
    )


def concat_manifest_clips(
    manifest: SeedanceManifest,
    output_path: Path,
) -> Path:
    clip_paths = [
        Path(clip.downloaded_path or clip.output_path)
        for clip in manifest.clips
    ]
    missing = [str(path) for path in clip_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot concat rendered clips because some files are missing: "
            + ", ".join(missing)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        handle.write(build_concat_list(manifest))
        concat_list_path = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
                "-c",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        concat_list_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg concat failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    return output_path
