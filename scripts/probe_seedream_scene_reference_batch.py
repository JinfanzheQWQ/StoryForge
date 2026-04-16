#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from probe_seedream_scene_reference_quality import (  # noqa: E402
    continuity_anchor_url,
    load_dotenv,
    probe_scene_frame_reference_quality,
    read_json,
)

ROOT = SCRIPT_DIR.parents[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects-root", default="outputs/projects")
    parser.add_argument(
        "--batch-root",
        help="Rebuild summary.json / summary.md from an existing batch directory.",
    )
    parser.add_argument("--max-single", type=int, default=2)
    parser.add_argument("--max-dual", type=int, default=2)
    return parser.parse_args()


def story_label(scene_manifest_path: Path) -> str:
    return scene_manifest_path.parent.name


def count_generated_character_urls(character_manifest_path: Path) -> int:
    payload = read_json(character_manifest_path)
    return sum(1 for item in payload if item.get("generated_url"))


def discover_candidates(
    projects_root: Path,
    *,
    max_single: int,
    max_dual: int,
) -> list[dict[str, Any]]:
    manifests = sorted(
        projects_root.glob("**/scene_image_manifest.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    candidates: list[dict[str, Any]] = []
    single_count = 0
    dual_count = 0
    used_keys: set[tuple[str, str, str]] = set()

    for scene_manifest_path in manifests:
        character_manifest_path = scene_manifest_path.with_name("character_image_manifest.json")
        if not character_manifest_path.exists():
            continue
        if count_generated_character_urls(character_manifest_path) < 2:
            continue
        story = story_label(scene_manifest_path)
        payload = read_json(scene_manifest_path)
        for item in payload:
            segment_id = str(item.get("segment_id", "") or "")
            if not segment_id:
                continue
            for frame_kind in ("end", "mid", "start"):
                active_names = list(item.get(f"{frame_kind}_frame_characters", []))
                if not active_names:
                    continue
                temporal_anchor = continuity_anchor_url(item, frame_kind)
                if len(active_names) == 1:
                    if single_count >= max_single:
                        continue
                    if not temporal_anchor:
                        continue
                    key = (str(scene_manifest_path), segment_id, frame_kind)
                    if key in used_keys:
                        continue
                    used_keys.add(key)
                    candidates.append(
                        {
                            "mode": "single",
                            "story": story,
                            "scene_manifest": scene_manifest_path,
                            "character_manifest": character_manifest_path,
                            "segment_id": segment_id,
                            "frame_kind": frame_kind,
                            "active_characters": active_names,
                            "recommended_variant": "3refs_temporal_scene_active",
                        }
                    )
                    single_count += 1
                    break
                if len(active_names) == 2:
                    if dual_count >= max_dual:
                        continue
                    if not temporal_anchor:
                        continue
                    key = (str(scene_manifest_path), segment_id, frame_kind)
                    if key in used_keys:
                        continue
                    used_keys.add(key)
                    candidates.append(
                        {
                            "mode": "dual",
                            "story": story,
                            "scene_manifest": scene_manifest_path,
                            "character_manifest": character_manifest_path,
                            "segment_id": segment_id,
                            "frame_kind": frame_kind,
                            "active_characters": active_names,
                            "recommended_variant": "4refs_temporal_scene_dual_cast",
                        }
                    )
                    dual_count += 1
                    break
            if single_count >= max_single and dual_count >= max_dual:
                return candidates
        if single_count >= max_single and dual_count >= max_dual:
            return candidates
    return candidates


def sanitize(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def to_repo_relative(path: Path | str) -> str:
    resolved = Path(path)
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def recommended_variant_for(active_characters: list[str]) -> str:
    if len(active_characters) >= 2:
        return "4refs_temporal_scene_dual_cast"
    return "3refs_temporal_scene_active"


def build_probe_summary(
    *,
    story: str,
    mode: str,
    segment_id: str,
    frame_kind: str,
    active_characters: list[str],
    report_path: Path,
    report: dict[str, Any],
    scene_manifest_path: Path | None = None,
    character_manifest_path: Path | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": mode,
        "story": story,
        "segment_id": segment_id,
        "frame_kind": frame_kind,
        "active_characters": active_characters,
        "recommended_variant": recommended_variant_for(active_characters),
        "report_path": to_repo_relative(report_path),
        "scene_anchor_url": report.get("scene_anchor_url", ""),
        "variants": report.get("variants", []),
    }
    if scene_manifest_path is not None:
        summary["scene_manifest"] = to_repo_relative(scene_manifest_path)
    if character_manifest_path is not None:
        summary["character_manifest"] = to_repo_relative(character_manifest_path)
    return summary


def summary_from_report(report_path: Path) -> dict[str, Any]:
    report = read_json(report_path)
    active_characters = list(report.get("active_characters", []))
    scene_manifest = Path(str(report.get("scene_manifest", "")))
    character_manifest = Path(str(report.get("character_manifest", "")))
    story = story_label(scene_manifest) if str(scene_manifest) else report_path.parent.name
    mode = "dual" if len(active_characters) >= 2 else "single"
    return build_probe_summary(
        story=story,
        mode=mode,
        segment_id=str(report.get("segment_id", "")),
        frame_kind=str(report.get("frame_kind", "")),
        active_characters=active_characters,
        report_path=report_path,
        report=report,
        scene_manifest_path=scene_manifest if str(scene_manifest) else None,
        character_manifest_path=character_manifest if str(character_manifest) else None,
    )


def write_batch_summary(
    *,
    batch_root: Path,
    summaries: list[dict[str, Any]],
    timestamp: str,
    projects_root: Path,
) -> Path:
    summary_payload = {
        "generated_at": timestamp,
        "projects_root": to_repo_relative(projects_root),
        "probe_count": len(summaries),
        "probes": summaries,
    }
    summary_json_path = batch_root / "summary.json"
    summary_json_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    markdown_parts = [
        "# Seedream Scene Reference Batch",
        "",
        f"- generated_at: `{timestamp}`",
        f"- probe_count: `{len(summaries)}`",
        "",
    ]
    for probe_summary in summaries:
        markdown_parts.append(markdown_for_probe(batch_root, probe_summary))
    summary_md_path = batch_root / "summary.md"
    summary_md_path.write_text("\n".join(markdown_parts), encoding="utf-8")
    return summary_json_path


def markdown_for_probe(batch_root: Path, probe_summary: dict[str, Any]) -> str:
    lines = [
        f"### {probe_summary['story']} / {probe_summary['segment_id']} / {probe_summary['frame_kind']}",
        "",
        f"- 模式：`{probe_summary['mode']}`",
        f"- 当前帧角色：`{', '.join(probe_summary['active_characters'])}`",
        f"- 推荐默认版本：`{probe_summary['recommended_variant']}`",
        f"- 结果目录：[open]({probe_summary['report_path']})",
        "",
        "| Variant | Output | Notes |",
        "| --- | --- | --- |",
    ]
    for variant in probe_summary["variants"]:
        image_path = variant.get("downloaded_image_path", "")
        image_link = f"[image]({image_path})" if image_path else "-"
        lines.append(
            f"| `{variant['label']}` | {image_link} | 待人工评分：角色一致 / 场景稳定 / 构图污染 |"
        )
    lines.append("")
    return "\n".join(lines)


def run() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")

    projects_root = ROOT / args.projects_root
    if args.batch_root:
        batch_root = (ROOT / args.batch_root).resolve()
        reports = sorted(
            path
            for path in batch_root.glob("*/report.json")
            if path.is_file()
        )
        if not reports:
            raise RuntimeError(f"No report.json files found under: {batch_root}")
        summaries = [summary_from_report(report_path) for report_path in reports]
        timestamp = batch_root.name
        summary_json_path = write_batch_summary(
            batch_root=batch_root,
            summaries=summaries,
            timestamp=timestamp,
            projects_root=projects_root,
        )
        print(str(summary_json_path))
        return 0

    candidates = discover_candidates(
        projects_root,
        max_single=args.max_single,
        max_dual=args.max_dual,
    )
    if not candidates:
        raise RuntimeError("No suitable scene-frame candidates were discovered.")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_root = ROOT / "outputs" / "debug" / "seedream_scene_reference_batch" / timestamp
    batch_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    for candidate in candidates:
        probe_dir = batch_root / sanitize(
            f"{candidate['mode']}_{candidate['story']}_{candidate['segment_id']}_{candidate['frame_kind']}"
        )
        report_path = probe_scene_frame_reference_quality(
            scene_manifest_path=candidate["scene_manifest"],
            character_manifest_path=candidate["character_manifest"],
            segment_id=candidate["segment_id"],
            frame_kind=candidate["frame_kind"],
            output_dir=probe_dir,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        summaries.append(
            build_probe_summary(
                story=str(candidate["story"]),
                mode=str(candidate["mode"]),
                segment_id=str(candidate["segment_id"]),
                frame_kind=str(candidate["frame_kind"]),
                active_characters=list(candidate["active_characters"]),
                report_path=report_path,
                report=report,
                scene_manifest_path=candidate["scene_manifest"],
                character_manifest_path=candidate["character_manifest"],
            )
        )

    summary_json_path = write_batch_summary(
        batch_root=batch_root,
        summaries=summaries,
        timestamp=timestamp,
        projects_root=projects_root,
    )

    print(str(summary_json_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
