#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.core.config import SeedreamConfig  # noqa: E402
from storyforge.integrations.seedream import SeedreamClient  # noqa: E402


DEFAULT_PUBLIC_REFERENCE_URLS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Example.jpg/640px-Example.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Fronalpstock_big.jpg/640px-Fronalpstock_big.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/640px-PNG_transparency_demonstration_1.png",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/50/Vd-Orig.png/640px-Vd-Orig.png",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def is_unexpired_tos_url(url: str) -> bool:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    date_value = params.get("X-Tos-Date", [""])[0]
    expires_value = params.get("X-Tos-Expires", [""])[0]
    if not date_value or not expires_value:
        return True
    try:
        request_ts = datetime_utc_from_tos(date_value)
        expires_seconds = int(expires_value)
    except ValueError:
        return True
    return datetime.now(timezone.utc).timestamp() <= request_ts + expires_seconds


def datetime_utc_from_tos(value: str) -> float:
    if len(value) != 16 or not value.endswith("Z"):
        raise ValueError(f"Unexpected X-Tos-Date value: {value}")
    year = int(value[0:4])
    month = int(value[4:6])
    day = int(value[6:8])
    hour = int(value[9:11])
    minute = int(value[11:13])
    second = int(value[13:15])
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp()


def discover_reference_urls(limit: int = 4) -> list[str]:
    manifests = sorted(
        ROOT.glob("outputs/**/*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    urls: list[str] = []
    for manifest in manifests:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        for url in collect_urls(payload):
            if "doubao-seedream-4-5" not in url:
                continue
            if not is_unexpired_tos_url(url):
                continue
            if url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                return urls
    return urls


def collect_urls(payload: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            urls.extend(collect_urls(value))
        return urls
    if isinstance(payload, list):
        for item in payload:
            urls.extend(collect_urls(item))
        return urls
    if isinstance(payload, str) and payload.startswith("https://"):
        return [payload]
    return urls


def build_variants(reference_urls: list[str]) -> list[dict[str, Any]]:
    single_ref = reference_urls[:1]
    multi_refs = reference_urls[:4]
    variants: list[dict[str, Any]] = [
        {
            "label": "text_only",
            "payload_extra": {},
        },
    ]
    if single_ref:
        variants.extend(
            [
                {
                    "label": "single_image_string",
                    "payload_extra": {"image": single_ref[0]},
                },
                {
                    "label": "single_reference_images_string",
                    "payload_extra": {"reference_images": single_ref[0]},
                },
                {
                    "label": "single_reference_images_list",
                    "payload_extra": {"reference_images": single_ref},
                },
            ]
        )
    if len(multi_refs) >= 2:
        variants.extend(
            [
                {
                    "label": f"multi_image_list_{len(multi_refs)}refs",
                    "payload_extra": {"image": multi_refs},
                },
                {
                    "label": f"multi_reference_images_list_{len(multi_refs)}refs",
                    "payload_extra": {"reference_images": multi_refs},
                },
                {
                    "label": f"multi_reference_images_objects_{len(multi_refs)}refs",
                    "payload_extra": {
                        "reference_images": [{"url": url} for url in multi_refs],
                    },
                },
            ]
        )
        if len(multi_refs) >= 4:
            variants.extend(
                [
                    {
                        "label": "multi_image_list_3refs",
                        "payload_extra": {"image": multi_refs[:3]},
                    },
                    {
                        "label": "multi_reference_images_list_3refs",
                        "payload_extra": {"reference_images": multi_refs[:3]},
                    },
                    {
                        "label": "multi_image_list_2refs",
                        "payload_extra": {"image": multi_refs[:2]},
                    },
                    {
                        "label": "multi_reference_images_list_2refs",
                        "payload_extra": {"reference_images": multi_refs[:2]},
                    },
                ]
            )
    return variants


def truncate_text(text: str, limit: int = 1200) -> str:
    return text[:limit] if len(text) <= limit else text[:limit] + "...<truncated>"


def sanitize_label(label: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in label)


def run_probe() -> int:
    load_dotenv(ROOT / ".env")
    config = SeedreamConfig(
        enabled=True,
        auto_submit=True,
        download_outputs=False,
    )
    client = SeedreamClient(config)
    if not client.api_key:
        raise RuntimeError("SEEDREAM_API_KEY is missing.")

    reference_urls = discover_reference_urls(limit=4) or DEFAULT_PUBLIC_REFERENCE_URLS[:4]
    output_dir = ROOT / "outputs" / "debug" / "seedream_payload_probe"
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        "A clean cinematic scene of two young people standing in a quiet campus garden at sunset, "
        "natural body proportions, soft light, realistic details."
    )
    base_payload = client._base_payload(prompt)
    endpoints = client._candidate_endpoints()
    variants = build_variants(reference_urls)

    report: dict[str, Any] = {
        "endpoint_candidates": endpoints,
        "model": config.model,
        "reference_urls": reference_urls,
        "variants": [],
    }

    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=180) as http_client:
        endpoint = endpoints[0]
        for variant in variants:
            payload = dict(base_payload)
            payload.update(variant["payload_extra"])
            result: dict[str, Any] = {
                "label": variant["label"],
                "endpoint": endpoint,
                "payload_keys": sorted(payload.keys()),
                "reference_count": len(reference_urls_for_payload(payload)),
                "status": "failed",
            }
            try:
                response = http_client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                response_payload = response.json()
                image_url = client._extract_image_url(response_payload)
                result["status"] = "completed"
                result["image_url"] = image_url
                result["response_excerpt"] = truncate_text(json.dumps(response_payload, ensure_ascii=False))
                image_path = output_dir / f"{sanitize_label(variant['label'])}.jpg"
                download_image(http_client, image_url, image_path)
                result["downloaded_image_path"] = str(image_path.relative_to(ROOT))
            except httpx.HTTPStatusError as exc:
                result["http_status"] = exc.response.status_code
                result["error"] = truncate_text(exc.response.text or str(exc))
            except Exception as exc:
                result["error"] = truncate_text(str(exc))
            report["variants"].append(result)

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    return 0


def reference_urls_for_payload(payload: dict[str, Any]) -> list[str]:
    image_value = payload.get("image")
    if isinstance(image_value, str):
        return [image_value]
    if isinstance(image_value, list):
        return [item for item in image_value if isinstance(item, str)]

    reference_value = payload.get("reference_images")
    if isinstance(reference_value, str):
        return [reference_value]
    if isinstance(reference_value, list):
        urls: list[str] = []
        for item in reference_value:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and isinstance(item.get("url"), str):
                urls.append(item["url"])
        return urls
    return []


def download_image(client: httpx.Client, image_url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    response = client.get(image_url)
    response.raise_for_status()
    target_path.write_bytes(response.content)


if __name__ == "__main__":
    raise SystemExit(run_probe())
