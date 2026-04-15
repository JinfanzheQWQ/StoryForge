from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    title_hint: str
    brief: dict[str, Any]
    created_at: str
    updated_at: str
    task_ids: list[str] = field(default_factory=list)
    latest_task_id: str | None = None
    story_title: str | None = None
    last_output_dir: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProjectRecord":
        return cls(
            project_id=str(raw["project_id"]),
            title_hint=str(raw.get("title_hint", "未命名故事")),
            brief=dict(raw.get("brief", {})),
            created_at=str(raw["created_at"]),
            updated_at=str(raw.get("updated_at", raw["created_at"])),
            task_ids=[str(item) for item in raw.get("task_ids", [])],
            latest_task_id=str(raw["latest_task_id"]) if raw.get("latest_task_id") else None,
            story_title=str(raw["story_title"]) if raw.get("story_title") else None,
            last_output_dir=str(raw["last_output_dir"]) if raw.get("last_output_dir") else None,
        )


class ProjectStore(ABC):
    @abstractmethod
    def create(self, brief: dict[str, Any]) -> ProjectRecord:
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str) -> ProjectRecord | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, project_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[ProjectRecord]:
        raise NotImplementedError

    @abstractmethod
    def attach_task(
        self,
        project_id: str,
        task_id: str,
        brief: dict[str, Any],
    ) -> ProjectRecord:
        raise NotImplementedError

    @abstractmethod
    def mark_task_result(
        self,
        project_id: str,
        task_id: str,
        result: dict[str, Any],
    ) -> None:
        raise NotImplementedError
