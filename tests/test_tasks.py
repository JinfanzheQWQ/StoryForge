from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.application.tasks import TaskStore  # noqa: E402


class TaskStoreTestCase(unittest.TestCase):
    def test_recover_running_tasks_requeues_local_tasks(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store_path = Path(temp_dir.name) / "tasks.json"
        store = TaskStore(store_path)

        record = store.create(
            project_id="project-1",
            task_type="project.videos",
            payload={"project_id": "project-1", "source_task_id": "source-1"},
        )
        store.mark_running(record.task_id)
        store.update_result(record.task_id, {"pipeline_stage": "video_render_started"})

        store.recover_running_tasks()

        recovered = store.get(record.task_id)
        assert recovered is not None
        self.assertEqual(recovered.status, "queued")
        self.assertIsNone(recovered.started_at)
        self.assertIsNone(recovered.finished_at)
        self.assertIsNone(recovered.error)
        self.assertEqual(recovered.result, {"pipeline_stage": "video_render_started"})

    def test_mark_running_clears_previous_error_and_finish_time(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store_path = Path(temp_dir.name) / "tasks.json"
        store = TaskStore(store_path)

        record = store.create(
            project_id="project-1",
            task_type="project.videos",
            payload={"project_id": "project-1", "source_task_id": "source-1"},
        )
        store.mark_failed(record.task_id, "old error")

        store.mark_running(record.task_id)

        running = store.get(record.task_id)
        assert running is not None
        self.assertEqual(running.status, "running")
        self.assertIsNotNone(running.started_at)
        self.assertIsNone(running.finished_at)
        self.assertIsNone(running.error)


if __name__ == "__main__":
    unittest.main()
