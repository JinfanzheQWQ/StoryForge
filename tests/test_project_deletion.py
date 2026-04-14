from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.application.project_deletion import delete_project_output_dirs  # noqa: E402
from storyforge.application.tasks import TaskRecord  # noqa: E402


class ProjectDeletionTestCase(unittest.TestCase):
    def test_delete_project_output_dirs_only_deletes_safe_output_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            output_root = project_root / "outputs"
            safe_dir = output_root / "story-run"
            unsafe_dir = project_root / "outside-story"
            safe_dir.mkdir(parents=True)
            unsafe_dir.mkdir()
            (safe_dir / "story_source.json").write_text("{}", encoding="utf-8")
            (unsafe_dir / "keep.json").write_text("{}", encoding="utf-8")

            tasks = [
                _task("task-safe", safe_dir),
                _task("task-duplicate", safe_dir),
                _task("task-unsafe", unsafe_dir),
                _task("task-root", output_root),
            ]

            report = delete_project_output_dirs(
                project_root=project_root,
                output_dir="outputs",
                tasks=tasks,
            )

            self.assertEqual(report.deleted_paths, [str(safe_dir.resolve())])
            self.assertFalse(safe_dir.exists())
            self.assertTrue(unsafe_dir.exists())
            self.assertTrue(output_root.exists())
            self.assertEqual(report.errors, [])
            self.assertEqual(len(report.skipped_paths), 2)
            self.assertTrue(any("outside output root" in item for item in report.skipped_paths))
            self.assertTrue(any("refused to delete output root" in item for item in report.skipped_paths))


def _task(task_id: str, output_dir: Path) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        project_id="project-1",
        task_type="project.story",
        status="completed",
        payload={},
        created_at="2026-04-15T00:00:00+00:00",
        result={"output_dir": str(output_dir)},
    )


if __name__ == "__main__":
    unittest.main()
