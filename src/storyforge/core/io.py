from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
import json
import re
import tomllib

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - optional dependency at import time
    BaseModel = object  # type: ignore[assignment]


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if hasattr(value, "model_dump") and isinstance(value, BaseModel):
        return to_jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def slugify(value: str, fallback: str = "storyforge-run") -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[\\/:*?\"<>|]+", "-", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = normalized.strip("-._")
    return normalized or fallback
