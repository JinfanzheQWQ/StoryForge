#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import SeedreamConfig  # noqa: E402
from storyforge.integrations.seedream import SeedreamClient  # noqa: E402


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
    parser.add_argument("--scene-manifest", required=True)
    parser.add_argument("--character-manifest", required=True)
    parser.add_argument("--segment-id", required=True)
    parser.add_argument("--frame-kind", choices=("start", "mid", "end"), required=True)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def select_segment(scene_manifest_path: Path, segment_id: str) -> dict[str, Any]:
    for item in read_json(scene_manifest_path):
        if item.get("segment_id") == segment_id:
            return item
    raise RuntimeError(f"segment_id not found: {segment_id}")


def character_url_map(character_manifest_path: Path) -> dict[str, str]:
    payload = read_json(character_manifest_path)
    return {
        item["character_name"]: item["generated_url"]
        for item in payload
        if item.get("character_name") and item.get("generated_url")
    }


def continuity_anchor_url(item: dict[str, Any], frame_kind: str) -> str:
    if frame_kind == "mid":
        return str(item.get("start_frame_url", "") or "")
    if frame_kind == "end":
        return str(item.get("mid_frame_url", "") or item.get("start_frame_url", "") or "")
    return str(item.get("scene_master_frame_url", "") or "")


def sanitize_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def download_image(client: httpx.Client, image_url: str, target_path: Path) -> None:
    response = client.get(image_url)
    response.raise_for_status()
    target_path.write_bytes(response.content)


def probe_scene_frame_reference_quality(
    *,
    scene_manifest_path: Path,
    character_manifest_path: Path,
    segment_id: str,
    frame_kind: str,
    output_dir: Path | None = None,
) -> Path:
    config = SeedreamConfig(enabled=True, auto_submit=True, download_outputs=False)
    client = SeedreamClient(config)
    if not client.api_key:
        raise RuntimeError("SEEDREAM_API_KEY is missing.")

    item = select_segment(scene_manifest_path, segment_id)
    url_map = character_url_map(character_manifest_path)

    prompt = str(item[f"{frame_kind}_frame_prompt"])
    active_names = list(item.get(f"{frame_kind}_frame_characters", []))
    if not active_names:
        raise RuntimeError("This probe expects at least one active character.")

    active_urls: list[str] = []
    for active_name in active_names:
        active_url = url_map.get(active_name, "")
        if not active_url:
            raise RuntimeError(f"Missing generated_url for active character: {active_name}")
        active_urls.append(active_url)
    offframe_urls = [
        url
        for name, url in url_map.items()
        if name not in active_names
    ]

    scene_master_url = str(item.get("scene_master_frame_url", "") or "")
    temporal_anchor = continuity_anchor_url(item, frame_kind)
    output_dir = output_dir or (
        ROOT
        / "outputs"
        / "debug"
        / "seedream_scene_reference_quality"
        / f"{segment_id}_{frame_kind}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    if not scene_master_url:
        surrogate_scene_prompt = str(item.get("scene_master_frame_prompt", "")).strip()
        if not surrogate_scene_prompt:
            raise RuntimeError("scene_master_frame_url is missing and no scene_master_frame_prompt is available.")
        with httpx.Client(timeout=180) as http_client:
            scene_master_url = client._create_image(
                http_client,
                prompt=surrogate_scene_prompt,
            )
            surrogate_scene_path = output_dir / "surrogate_scene_anchor.jpg"
            download_image(http_client, scene_master_url, surrogate_scene_path)

    variants: list[dict[str, Any]] = []
    if len(active_urls) == 1:
        variants.append(
            {
                "label": "2refs_scene_active",
                "reference_images": [scene_master_url, active_urls[0]],
            }
        )
        if temporal_anchor:
            variants.append(
                {
                    "label": "3refs_temporal_scene_active",
                    "reference_images": [temporal_anchor, scene_master_url, active_urls[0]],
                }
            )
        if temporal_anchor and offframe_urls:
            variants.append(
                {
                    "label": "4refs_temporal_scene_active_offframe",
                    "reference_images": [temporal_anchor, scene_master_url, active_urls[0], offframe_urls[0]],
                }
            )
    else:
        if not temporal_anchor:
            raise RuntimeError(
                "Dual-character comparison requires a temporal anchor; choose mid/end frame with existing anchor."
            )
        variants.extend(
            [
                {
                    "label": "2refs_temporal_scene",
                    "reference_images": [temporal_anchor, scene_master_url],
                },
                {
                    "label": "3refs_temporal_scene_primary",
                    "reference_images": [temporal_anchor, scene_master_url, active_urls[0]],
                },
                {
                    "label": "4refs_temporal_scene_dual_cast",
                    "reference_images": [temporal_anchor, scene_master_url, active_urls[0], active_urls[1]],
                },
            ]
        )

    base_payload = client._base_payload(prompt)
    endpoint = client._candidate_endpoints()[0]
    report: dict[str, Any] = {
        "scene_manifest": str(scene_manifest_path),
        "character_manifest": str(character_manifest_path),
        "segment_id": segment_id,
        "frame_kind": frame_kind,
        "active_characters": active_names,
        "endpoint": endpoint,
        "scene_anchor_url": scene_master_url,
        "variants": [],
    }

    with httpx.Client(timeout=180) as http_client:
        for variant in variants:
            payload = dict(base_payload)
            payload["image"] = variant["reference_images"]
            item_report: dict[str, Any] = {
                "label": variant["label"],
                "reference_images": list(variant["reference_images"]),
                "status": "failed",
            }
            try:
                response = http_client.post(
                    endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {client.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                response_payload = response.json()
                image_url = client._extract_image_url(response_payload)
                target_path = output_dir / f"{sanitize_filename(variant['label'])}.jpg"
                download_image(http_client, image_url, target_path)
                item_report["status"] = "completed"
                item_report["image_url"] = image_url
                item_report["downloaded_image_path"] = str(target_path.relative_to(ROOT))
            except httpx.HTTPStatusError as exc:
                item_report["http_status"] = exc.response.status_code
                item_report["error"] = exc.response.text or str(exc)
            except Exception as exc:
                item_report["error"] = str(exc)
            report["variants"].append(item_report)

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def run() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env")
    report_path = probe_scene_frame_reference_quality(
        scene_manifest_path=Path(args.scene_manifest),
        character_manifest_path=Path(args.character_manifest),
        segment_id=args.segment_id,
        frame_kind=args.frame_kind,
    )
    print(str(report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
