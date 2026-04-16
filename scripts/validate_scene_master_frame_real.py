#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import AppConfig  # noqa: E402
from storyforge.core.io import write_json  # noqa: E402
from storyforge.domains.video.contracts import (  # noqa: E402
    VideoProjectPackage,
)
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from storyforge.integrations.seedream import SeedreamClient  # noqa: E402
from storyforge.pipelines.video_planning import load_video_planning_artifacts  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/storyforge.example.toml")
    parser.add_argument("--source-output-dir", required=True)
    parser.add_argument("--segment-id", required=True)
    parser.add_argument("--output-dir")
    return parser.parse_args()


def build_validation_package(
    *,
    service: NovelToVideoService,
    source_output_dir: Path,
    target_output_dir: Path,
    segment_id: str,
) -> VideoProjectPackage:
    planning = load_video_planning_artifacts(source_output_dir)
    segment_map = {item.segment_id: item for item in planning.project_package.segments}
    target_segment = segment_map.get(segment_id)
    if target_segment is None:
        raise RuntimeError(f"segment_id not found: {segment_id}")

    selected_scene_id = target_segment.scene_id
    if not selected_scene_id:
        raise RuntimeError(f"segment_id has no scene_id: {segment_id}")

    selected_scene = next(
        (item for item in planning.project_package.scenes if item.scene_id == selected_scene_id),
        None,
    )
    if selected_scene is None:
        raise RuntimeError(f"scene not found for segment: {segment_id}")

    involved_names = set(target_segment.involved_characters)
    for names in (
        target_segment.start_frame_characters,
        target_segment.mid_frame_characters,
        target_segment.end_frame_characters,
    ):
        involved_names.update(names)

    character_profiles = [
        item
        for item in planning.project_package.character_profiles
        if item.name in involved_names
    ]
    if not character_profiles:
        raise RuntimeError(f"no character profiles found for segment: {segment_id}")

    character_images = service._build_character_image_tasks(
        character_profiles,
        str(target_output_dir),
    )
    profile_map = {item.name: item for item in character_profiles}

    selected_scene.segments = [target_segment]
    scenes = service._prepare_scene_master_frames([selected_scene], str(target_output_dir))
    scene_images = service._build_scene_image_tasks(
        scenes,
        [target_segment],
        character_images,
        profile_map,
        str(target_output_dir),
    )

    return VideoProjectPackage(
        title=planning.project_package.title,
        character_profiles=character_profiles,
        character_images=character_images,
        scenes=scenes,
        segments=[target_segment],
        scene_images=scene_images,
        seedance_manifest=planning.project_package.seedance_manifest,
        workflow_trace={
            "validation_source_output_dir": str(source_output_dir),
            "validation_segment_id": segment_id,
        },
    )


def run() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")

    config = AppConfig.load(ROOT / args.config)
    source_output_dir = (ROOT / args.source_output_dir).resolve()
    if not source_output_dir.exists():
        raise RuntimeError(f"source output dir not found: {source_output_dir}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_output_dir = (
        (ROOT / args.output_dir).resolve()
        if args.output_dir
        else ROOT
        / "outputs"
        / "debug"
        / "scene_master_frame_validation"
        / f"{timestamp}_{args.segment_id}"
    )
    target_output_dir.mkdir(parents=True, exist_ok=True)

    service = NovelToVideoService(
        segment_duration_seconds=config.video.segment_duration_seconds,
        aspect_ratio=config.video.aspect_ratio,
        fps=config.video.fps,
        character_image_provider=config.video.character_image_provider,
        scene_image_provider=config.video.scene_image_provider,
        seedance_config=config.seedance,
    )
    package = build_validation_package(
        service=service,
        source_output_dir=source_output_dir,
        target_output_dir=target_output_dir,
        segment_id=args.segment_id,
    )

    prompt_preview = {
        "segment_id": args.segment_id,
        "source_output_dir": str(source_output_dir),
        "target_output_dir": str(target_output_dir),
        "scene_master_frame_prompt": package.scenes[0].scene_master_frame_prompt,
        "scene_master_frame_path": package.scenes[0].scene_master_frame_path,
        "start_frame_prompt": package.scene_images[0].start_frame_prompt,
        "mid_frame_prompt": package.scene_images[0].mid_frame_prompt,
        "end_frame_prompt": package.scene_images[0].end_frame_prompt,
        "start_frame_characters": package.scene_images[0].start_frame_characters,
        "mid_frame_characters": package.scene_images[0].mid_frame_characters,
        "end_frame_characters": package.scene_images[0].end_frame_characters,
    }
    write_json(target_output_dir / "prompt_preview.json", prompt_preview)

    seedream_client = SeedreamClient(config.seedream)
    character_execution = seedream_client.generate_character_images(package, force_submit=True)
    scene_execution = seedream_client.generate_scene_images(
        package,
        force_submit=True,
        segment_ids={args.segment_id},
    )

    write_json(target_output_dir / "character_visual_bible.json", package.character_profiles)
    write_json(target_output_dir / "character_image_manifest.json", package.character_images)
    write_json(target_output_dir / "scene_plan.json", {"scenes": package.scenes})
    write_json(target_output_dir / "segment_plan.json", package.segments)
    write_json(target_output_dir / "scene_image_manifest.json", package.scene_images)
    write_json(target_output_dir / "seedream_character_execution.json", character_execution)
    write_json(target_output_dir / "seedream_scene_execution.json", scene_execution)

    print(str(target_output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
