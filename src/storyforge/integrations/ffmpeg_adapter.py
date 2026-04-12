from __future__ import annotations

from pathlib import Path
import subprocess

from storyforge.domains.video.contracts import SeedanceManifest


def build_concat_script(manifest: SeedanceManifest, output_path: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "ROOT_DIR=$(cd \"$(dirname \"$0\")\" && pwd)",
        "",
        "# 等所有 Seedance 片段视频准备好以后，再统一拼接。",
        f"ffmpeg -y -f concat -safe 0 -i \"$ROOT_DIR/concat_list.txt\" -c copy \"{output_path}\"",
        "",
        f"echo \"rendered -> {output_path}\"",
    ]
    return "\n".join(lines) + "\n"


def build_concat_list(manifest: SeedanceManifest) -> str:
    return "".join(
        f"file '{clip.downloaded_path or clip.output_path}'\n"
        for clip in manifest.clips
    )


def concat_manifest_clips(
    manifest: SeedanceManifest,
    concat_list_path: Path,
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
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg concat failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    return output_path
