from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil

from storyforge.application.tasks import TaskRecord


@dataclass(slots=True)
class ProjectOutputDeletionReport:
    deleted_paths: list[str] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_paths)


def delete_project_output_dirs(
    *,
    project_root: Path,
    output_dir: str,
    tasks: list[TaskRecord],
) -> ProjectOutputDeletionReport:
    """Delete task output directories that are safely inside the configured output root."""

    report = ProjectOutputDeletionReport()
    output_root = (project_root / output_dir).resolve()
    seen: set[Path] = set()

    for task in tasks:
        raw_output_dir = _task_output_dir(task)
        if not raw_output_dir:
            continue

        candidate_path = _absolute_path(project_root, raw_output_dir)
        resolved_candidate = candidate_path.resolve(strict=False)
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)

        if resolved_candidate == output_root:
            report.skipped_paths.append(f"{resolved_candidate} (refused to delete output root)")
            continue
        if not _is_relative_to(resolved_candidate, output_root):
            report.skipped_paths.append(f"{resolved_candidate} (outside output root)")
            continue
        if not candidate_path.exists():
            report.skipped_paths.append(f"{resolved_candidate} (already missing)")
            continue

        try:
            if candidate_path.is_symlink() or candidate_path.is_file():
                candidate_path.unlink()
            elif candidate_path.is_dir():
                shutil.rmtree(candidate_path)
            else:
                report.skipped_paths.append(f"{resolved_candidate} (unsupported file type)")
                continue
        except OSError as exc:
            report.errors.append(f"{resolved_candidate}: {exc}")
            continue

        report.deleted_paths.append(str(resolved_candidate))

    return report


def _task_output_dir(task: TaskRecord) -> str | None:
    if not isinstance(task.result, dict):
        return None
    raw_output_dir = task.result.get("output_dir")
    return str(raw_output_dir) if raw_output_dir else None


def _absolute_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
