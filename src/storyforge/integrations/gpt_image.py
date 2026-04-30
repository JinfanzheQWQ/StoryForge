from __future__ import annotations

from dataclasses import dataclass
import base64
import copy
import io
import json
import os
from pathlib import Path
import time
from typing import Any

import httpx

from storyforge.core.config import GPTImageConfig


KIE_GPT_IMAGE_ASPECT_RATIOS_BY_RESOLUTION: dict[str, tuple[str, ...]] = {
    "AUTO": ("auto",),
    "1K": ("auto", "1:1", "9:16", "16:9", "4:3", "3:4"),
    "2K": ("1:1", "9:16", "16:9", "4:3", "3:4"),
    "4K": ("9:16", "16:9", "4:3", "3:4"),
}

OPENAI_GPT_IMAGE_SIZE_BY_RESOLUTION_AND_RATIO: dict[str, dict[str, str]] = {
    "AUTO": {
        "AUTO": "auto",
    },
    "1K": {
        "1:1": "1024x1024",
        "2:3": "1024x1536",
        "3:2": "1536x1024",
    },
}


@dataclass(slots=True)
class GPTImageResult:
    submitted: bool
    image_url: str
    output_path: str
    request_info: dict[str, Any]
    note: str


class GPTImageClient:
    def __init__(self, config: GPTImageConfig) -> None:
        self.config = config
        self.provider = self._normalize_provider(config.provider)
        self._last_request_info: dict[str, Any] = {}

    def generate_single_image(
        self,
        *,
        mode: str,
        prompt: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str = "",
        output_size: str = "",
        output_path: Path | None = None,
    ) -> GPTImageResult:
        if not self.config.enabled:
            raise RuntimeError("GPT Image 2 is disabled in [gpt_image].")
        normalized_references = self._normalize_reference_images(reference_images or [])
        if mode == "image_to_image" and not normalized_references:
            raise ValueError("图生图必须至少提交一张参考图 URL。")

        with httpx.Client(timeout=120) as client:
            self._last_request_info = {}
            image_url = self._generate_with_provider(
                client,
                mode=mode,
                prompt=prompt,
                reference_images=normalized_references,
                aspect_ratio=aspect_ratio,
                output_size=output_size,
                output_path=output_path,
            )
            if self.config.download_outputs and output_path is not None and image_url:
                self._download_image(client, image_url, output_path)

        return GPTImageResult(
            submitted=True,
            image_url=image_url,
            output_path=str(output_path or ""),
            request_info=self._snapshot_request_info(normalized_references),
            note=f"GPT Image 2 generation completed via {self.provider}.",
        )

    def _generate_with_provider(
        self,
        client: httpx.Client,
        *,
        mode: str,
        prompt: str,
        reference_images: list[str],
        aspect_ratio: str,
        output_size: str,
        output_path: Path | None,
    ) -> str:
        if self.provider == "kie":
            return self._generate_with_kie(
                client,
                mode=mode,
                prompt=prompt,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                output_size=output_size,
            )
        if self.provider == "openai":
            return self._generate_with_openai(
                client,
                mode=mode,
                prompt=prompt,
                reference_images=reference_images,
                aspect_ratio=aspect_ratio,
                output_size=output_size,
                output_path=output_path,
            )
        raise ValueError("gpt_image.provider 只能是 kie 或 openai。")

    def _generate_with_kie(
        self,
        client: httpx.Client,
        *,
        mode: str,
        prompt: str,
        reference_images: list[str],
        aspect_ratio: str,
        output_size: str,
    ) -> str:
        api_key = self._required_env(self.config.kie_api_key_env, "KIE")
        model = (
            self.config.kie_image_to_image_model
            if mode == "image_to_image"
            else self.config.kie_text_to_image_model
        )
        resolution, resolved_aspect_ratio = self._resolve_kie_resolution_and_ratio(output_size, aspect_ratio)
        input_payload: dict[str, Any] = {"prompt": prompt}
        input_payload["resolution"] = resolution
        input_payload["aspect_ratio"] = resolved_aspect_ratio
        if reference_images:
            input_payload["input_urls"] = reference_images
        payload = {
            "model": model,
            "input": input_payload,
        }
        endpoint = f"{self._kie_base_url()}/api/v1/jobs/createTask"
        response = client.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        create_payload = response.json()
        task_id = self._extract_kie_task_id(create_payload)
        self._last_request_info = {
            "provider": "kie",
            "endpoint": endpoint,
            "model": model,
            "payload": copy.deepcopy(payload),
            "task_id": task_id,
            "create_response": create_payload,
        }
        return self._poll_kie_result(client, api_key, task_id)

    def _poll_kie_result(self, client: httpx.Client, api_key: str, task_id: str) -> str:
        endpoint = f"{self._kie_base_url()}/api/v1/jobs/recordInfo"
        deadline = time.monotonic() + self.config.max_wait_seconds
        last_payload: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = client.get(
                endpoint,
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
            last_payload = payload
            state = str(self._extract_nested(payload, "data", "state") or "").lower()
            if state in {"success", "completed", "finish", "finished"}:
                self._last_request_info["record_endpoint"] = endpoint
                self._last_request_info["record_response"] = payload
                return self._extract_kie_result_url(payload)
            if state in {"fail", "failed", "error"}:
                raise RuntimeError(f"KIE GPT Image 2 task failed: {payload}")
            time.sleep(self.config.poll_interval_seconds)
        raise RuntimeError(f"KIE GPT Image 2 task timed out: task_id={task_id}, last={last_payload}")

    def _generate_with_openai(
        self,
        client: httpx.Client,
        *,
        mode: str,
        prompt: str,
        reference_images: list[str],
        aspect_ratio: str,
        output_size: str,
        output_path: Path | None,
    ) -> str:
        api_key = self._required_env(self.config.openai_api_key_env, "OpenAI")
        size = self._resolve_openai_size(output_size, aspect_ratio)
        if mode == "image_to_image":
            return self._create_openai_edit(
                client,
                api_key=api_key,
                prompt=prompt,
                reference_images=reference_images,
                size=size,
                output_path=output_path,
            )
        return self._create_openai_generation(
            client,
            api_key=api_key,
            prompt=prompt,
            size=size,
            output_path=output_path,
        )

    def _create_openai_generation(
        self,
        client: httpx.Client,
        *,
        api_key: str,
        prompt: str,
        size: str,
        output_path: Path | None,
    ) -> str:
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "size": size,
            "quality": self.config.quality,
            "output_format": self.config.output_format,
        }
        endpoint = f"{self._openai_base_url()}/images/generations"
        response = client.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        response_payload = response.json()
        self._last_request_info = {
            "provider": "openai",
            "endpoint": endpoint,
            "payload": copy.deepcopy(payload),
            "response": self._redact_large_image_payload(response_payload),
        }
        return self._write_openai_image(response_payload, output_path)

    def _create_openai_edit(
        self,
        client: httpx.Client,
        *,
        api_key: str,
        prompt: str,
        reference_images: list[str],
        size: str,
        output_path: Path | None,
    ) -> str:
        data = {
            "model": self.config.model,
            "prompt": prompt,
            "size": size,
            "quality": self.config.quality,
        }
        files = self._download_reference_files(client, reference_images)
        endpoint = f"{self._openai_base_url()}/images/edits"
        response = client.post(
            endpoint,
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        response_payload = response.json()
        self._last_request_info = {
            "provider": "openai",
            "endpoint": endpoint,
            "payload": copy.deepcopy(data),
            "response": self._redact_large_image_payload(response_payload),
        }
        return self._write_openai_image(response_payload, output_path)

    def _download_reference_files(
        self,
        client: httpx.Client,
        reference_images: list[str],
    ) -> list[tuple[str, tuple[str, Any, str]]]:
        files: list[tuple[str, tuple[str, Any, str]]] = []
        for index, url in enumerate(reference_images, start=1):
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type") or "image/png"
            suffix = self._suffix_for_content_type(content_type)
            files.append(
                (
                    "image[]",
                    (
                        f"reference-{index}{suffix}",
                        io.BytesIO(response.content),
                        content_type,
                    ),
                )
            )
        return files

    def _write_openai_image(self, payload: dict[str, Any], output_path: Path | None) -> str:
        b64_json = self._extract_openai_b64(payload)
        if output_path is None:
            return f"data:image/{self.config.output_format};base64,{b64_json}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(b64_json))
        return ""

    def _extract_openai_b64(self, payload: dict[str, Any]) -> str:
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            value = data[0].get("b64_json")
            if value:
                return str(value)
            url = data[0].get("url")
            if url:
                raise RuntimeError("OpenAI returned URL output; configure this client to use b64_json output.")
        raise RuntimeError(f"Unable to extract OpenAI image data: {payload}")

    def _extract_kie_task_id(self, payload: dict[str, Any]) -> str:
        for path in (("data", "taskId"), ("data", "task_id"), ("taskId",), ("task_id",)):
            value = self._extract_nested(payload, *path)
            if value:
                return str(value)
        raise RuntimeError(f"Unable to extract KIE task id: {payload}")

    def _extract_kie_result_url(self, payload: dict[str, Any]) -> str:
        result_json = self._extract_nested(payload, "data", "resultJson")
        if isinstance(result_json, str) and result_json.strip():
            try:
                parsed = json.loads(result_json)
            except json.JSONDecodeError:
                parsed = {}
            url = self._extract_first_url(parsed)
            if url:
                return url
        url = self._extract_first_url(payload)
        if url:
            return url
        raise RuntimeError(f"Unable to extract KIE result URL: {payload}")

    def _extract_first_url(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload if payload.startswith(("http://", "https://")) else ""
        if isinstance(payload, list):
            for item in payload:
                url = self._extract_first_url(item)
                if url:
                    return url
            return ""
        if isinstance(payload, dict):
            for key in ("resultUrls", "urls", "images", "image_urls"):
                url = self._extract_first_url(payload.get(key))
                if url:
                    return url
            for key in ("url", "imageUrl", "image_url"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    def _resolve_kie_resolution_and_ratio(self, output_size: str, aspect_ratio: str) -> tuple[str, str]:
        raw_resolution = str(output_size or "").strip().upper() or "1K"
        raw_ratio = str(aspect_ratio or "").strip().lower() or "auto"
        resolution = "1K" if raw_resolution == "AUTO" else raw_resolution
        supported_ratios = KIE_GPT_IMAGE_ASPECT_RATIOS_BY_RESOLUTION.get(raw_resolution)
        if supported_ratios is None:
            supported = ", ".join(KIE_GPT_IMAGE_ASPECT_RATIOS_BY_RESOLUTION)
            raise ValueError(f"KIE GPT Image 2 分辨率只支持 {supported}。")
        if raw_ratio not in supported_ratios:
            supported = ", ".join(supported_ratios)
            raise ValueError(f"KIE GPT Image 2 的 {raw_resolution} 分辨率只支持这些比例：{supported}。")
        return resolution, raw_ratio

    def _resolve_openai_size(self, output_size: str, aspect_ratio: str) -> str:
        resolution = str(output_size or "").strip().upper() or "AUTO"
        if resolution == "AUTO":
            ratio = "AUTO"
        else:
            ratio = str(aspect_ratio or "").strip().upper() or "1:1"
        supported_ratios = OPENAI_GPT_IMAGE_SIZE_BY_RESOLUTION_AND_RATIO.get(resolution)
        if supported_ratios is None:
            supported = ", ".join(OPENAI_GPT_IMAGE_SIZE_BY_RESOLUTION_AND_RATIO)
            raise ValueError(f"GPT Image 2 当前只支持 {supported} 分辨率档位。")
        size = supported_ratios.get(ratio)
        if size is None:
            supported = ", ".join(supported_ratios)
            raise ValueError(f"GPT Image 2 的 {resolution} 分辨率只支持这些比例：{supported}。")
        return size

    def _download_image(self, client: httpx.Client, image_url: str, output_path: Path) -> None:
        if image_url.startswith("data:image/"):
            _, encoded = image_url.split(",", 1)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(base64.b64decode(encoded))
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = client.get(image_url)
        response.raise_for_status()
        output_path.write_bytes(response.content)

    def _snapshot_request_info(self, reference_images: list[str]) -> dict[str, Any]:
        snapshot = copy.deepcopy(self._last_request_info)
        snapshot["model"] = self.config.model
        snapshot["reference_bindings"] = self._reference_bindings(reference_images)
        return snapshot

    def _reference_bindings(self, reference_images: list[str]) -> list[dict[str, str]]:
        bindings: list[dict[str, str]] = []
        for index, url in enumerate(reference_images, start=1):
            bindings.append(
                {
                    "label": f"图片{index}",
                    "kind": "source_image",
                    "description": "GPT Image 2 图生图参考图。",
                    "url": url,
                }
            )
        return bindings

    def _normalize_reference_images(self, reference_images: list[str]) -> list[str]:
        normalized: list[str] = []
        for url in reference_images:
            value = str(url or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _required_env(self, env_name: str, provider_name: str) -> str:
        value = os.getenv(env_name, "").strip()
        if not value:
            raise RuntimeError(f"{provider_name} API key is missing: set {env_name}.")
        return value

    def _kie_base_url(self) -> str:
        return (os.getenv("KIE_BASE_URL") or self.config.kie_base_url).rstrip("/")

    def _openai_base_url(self) -> str:
        return (os.getenv("OPENAI_BASE_URL") or self.config.openai_base_url).rstrip("/")

    def _normalize_provider(self, provider: str) -> str:
        normalized = str(provider or "").strip().lower()
        if normalized in {"kie", "openai"}:
            return normalized
        raise ValueError("gpt_image.provider 只能是 kie 或 openai。")

    def _extract_nested(self, payload: dict[str, Any], *path: str) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _redact_large_image_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        redacted = copy.deepcopy(payload)
        data = redacted.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("b64_json"):
                    item["b64_json"] = "[base64 image omitted]"
        return redacted

    def _suffix_for_content_type(self, content_type: str) -> str:
        normalized = content_type.lower()
        if "jpeg" in normalized or "jpg" in normalized:
            return ".jpg"
        if "webp" in normalized:
            return ".webp"
        return ".png"
