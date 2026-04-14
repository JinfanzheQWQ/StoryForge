from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storyforge.application.persistence.mysql_tasks import MySQLTaskStore  # noqa: E402


class MySQLTaskStoreTestCase(unittest.TestCase):
    def test_recover_running_tasks_requeues_instead_of_failing(self) -> None:
        cursor = _Cursor()
        connection = _Connection(cursor)
        backend = Mock()
        backend.connect.return_value = connection
        store = MySQLTaskStore(backend)

        store.recover_running_tasks()

        sql, params = cursor.executed[0]
        self.assertIn("UPDATE tasks", sql)
        self.assertIn("status = 'queued'", sql)
        self.assertIn("started_at = NULL", sql)
        self.assertIn("finished_at = NULL", sql)
        self.assertIn("error_text = NULL", sql)
        self.assertIsNone(params)

    def test_update_result_merges_under_row_lock(self) -> None:
        cursor = _Cursor(
            fetchone_results=[{"result_json": '{"pipeline_stage":"story_completed","count":1}'}]
        )
        connection = _Connection(cursor)
        backend = Mock()
        backend.connect.return_value = connection
        store = MySQLTaskStore(backend)

        store.update_result("task-1", {"segment_plan_path": "/tmp/segment_plan.json", "count": 2})

        self.assertTrue(connection.begin_called)
        self.assertTrue(connection.commit_called)
        self.assertFalse(connection.rollback_called)
        self.assertEqual(cursor.executed[0][1], ("task-1",))
        self.assertIn("FOR UPDATE", cursor.executed[0][0])
        update_sql, update_params = cursor.executed[1]
        self.assertIn("UPDATE tasks", update_sql)
        self.assertIn('"pipeline_stage": "story_completed"', update_params[0])
        self.assertIn('"segment_plan_path": "/tmp/segment_plan.json"', update_params[0])
        self.assertIn('"count": 2', update_params[0])

    def test_list_grouped_fetches_all_requested_projects_once(self) -> None:
        cursor = _Cursor(
            fetchall_results=[
                [
                    {
                        "task_id": "task-a",
                        "project_id": "project-1",
                        "task_type": "project.story",
                        "status": "completed",
                        "payload_json": "{}",
                        "created_at": "2026-04-12T00:00:00+00:00",
                        "started_at": None,
                        "finished_at": None,
                        "result_json": "{}",
                        "error_text": None,
                    },
                    {
                        "task_id": "task-b",
                        "project_id": "project-2",
                        "task_type": "project.story",
                        "status": "queued",
                        "payload_json": "{}",
                        "created_at": "2026-04-11T00:00:00+00:00",
                        "started_at": None,
                        "finished_at": None,
                        "result_json": None,
                        "error_text": None,
                    },
                ]
            ]
        )
        connection = _Connection(cursor)
        backend = Mock()
        backend.connect.return_value = connection
        store = MySQLTaskStore(backend)

        grouped = store.list_grouped(["project-1", "project-2"])

        self.assertEqual(set(grouped), {"project-1", "project-2"})
        self.assertEqual([item.task_id for item in grouped["project-1"]], ["task-a"])
        self.assertEqual([item.task_id for item in grouped["project-2"]], ["task-b"])
        self.assertEqual(cursor.executed[0][1], ("project-1", "project-2"))


class _Connection:
    def __init__(self, cursor: "_Cursor") -> None:
        self._cursor = cursor
        self.begin_called = False
        self.commit_called = False
        self.rollback_called = False

    def cursor(self) -> "_Cursor":
        return self._cursor

    def begin(self) -> None:
        self.begin_called = True

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        return None


class _Cursor:
    def __init__(
        self,
        fetchone_results: list[dict[str, object] | None] | None = None,
        fetchall_results: list[list[dict[str, object]]] | None = None,
    ) -> None:
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._fetchone_results.pop(0) if self._fetchone_results else None

    def fetchall(self) -> list[dict[str, object]]:
        return self._fetchall_results.pop(0) if self._fetchall_results else []
