from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from storyforge.application.tasks import utc_now
from storyforge.core.io import read_json, write_json


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


class ProjectStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._projects: dict[str, ProjectRecord] = {}
        self._load()

    def create(self, brief: dict[str, Any]) -> ProjectRecord:
        now = utc_now()
        record = ProjectRecord(
            project_id=str(uuid4()),
            title_hint=str(brief.get("title_hint", "未命名故事")),
            brief=dict(brief),
            created_at=now,
            updated_at=now,
        )
        self._projects[record.project_id] = record
        self._save()
        return record

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._projects.get(project_id)

    def delete(self, project_id: str) -> bool:
        if project_id not in self._projects:
            return False
        del self._projects[project_id]
        self._save()
        return True

    def list(self) -> list[ProjectRecord]:
        return sorted(
            self._projects.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    def attach_task(
        self,
        project_id: str,
        task_id: str,
        brief: dict[str, Any],
    ) -> ProjectRecord:
        record = self._projects[project_id]
        if task_id not in record.task_ids:
            record.task_ids.append(task_id)
        record.latest_task_id = task_id
        record.updated_at = utc_now()
        if brief:
            record.brief = dict(brief)
            record.title_hint = str(brief.get("title_hint", record.title_hint))
        self._save()
        return record

    def mark_task_result(
        self,
        project_id: str,
        task_id: str,
        result: dict[str, Any],
    ) -> None:
        record = self._projects[project_id]
        record.latest_task_id = task_id
        record.updated_at = utc_now()
        if result.get("story_title"):
            record.story_title = str(result["story_title"])
        if result.get("output_dir"):
            record.last_output_dir = str(result["output_dir"])
        self._save()

    def _load(self) -> None:
        if not self._path.exists():
            return

        raw = read_json(self._path)
        if not isinstance(raw, list):
            return

        self._projects = {
            item["project_id"]: ProjectRecord.from_dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("project_id")
        }

    def _save(self) -> None:
        write_json(self._path, list(self._projects.values()))
