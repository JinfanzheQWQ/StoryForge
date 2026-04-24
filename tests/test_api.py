from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from fastapi.testclient import TestClient  # noqa: E402

from storyforge.api.main import create_app  # noqa: E402
from storyforge.application.container import AppContainer  # noqa: E402
from storyforge.application.projects import ProjectRecord, ProjectStore  # noqa: E402
from storyforge.application.task_runtime import TaskExecutionContext, build_task_handler  # noqa: E402
from storyforge.application.tasks import AsyncTaskQueue, QueuedTask, TaskRecord, TaskStore, utc_now  # noqa: E402
from storyforge.domains.video.errors import VideoStructuredGenerationError  # noqa: E402
from storyforge.domains.video.service import NovelToVideoService  # noqa: E402
from _deterministic_backends import (  # noqa: E402
    DeterministicStoryBackend,
    DeterministicVideoBackend,
)


class InMemoryProjectStore(ProjectStore):
    def __init__(self) -> None:
        self._projects: dict[str, ProjectRecord] = {}

    def create(self, brief: dict[str, object]) -> ProjectRecord:
        now = utc_now()
        record = ProjectRecord(
            project_id=str(uuid4()),
            title_hint=str(brief.get("title_hint", "未命名故事")),
            brief=dict(brief),
            created_at=now,
            updated_at=now,
        )
        self._projects[record.project_id] = record
        return record

    def get(self, project_id: str) -> ProjectRecord | None:
        return self._projects.get(project_id)

    def delete(self, project_id: str) -> bool:
        if project_id not in self._projects:
            return False
        del self._projects[project_id]
        return True

    def list(self) -> list[ProjectRecord]:
        return sorted(self._projects.values(), key=lambda item: item.updated_at, reverse=True)

    def attach_task(self, project_id: str, task_id: str, brief: dict[str, object]) -> ProjectRecord:
        record = self._projects[project_id]
        if task_id not in record.task_ids:
            record.task_ids.append(task_id)
        record.latest_task_id = task_id
        record.updated_at = utc_now()
        if brief:
            record.brief = dict(brief)
            record.title_hint = str(brief.get("title_hint", record.title_hint))
        return record

    def mark_task_result(self, project_id: str, task_id: str, result: dict[str, object]) -> None:
        record = self._projects[project_id]
        record.latest_task_id = task_id
        record.updated_at = utc_now()
        if result.get("story_title"):
            record.story_title = str(result["story_title"])
        if result.get("output_dir"):
            record.last_output_dir = str(result["output_dir"])


class InMemoryTaskStore(TaskStore):
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}

    def create(self, project_id: str, task_type: str, payload: dict[str, object]) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid4()),
            project_id=project_id,
            task_type=task_type,
            status="queued",
            payload=payload,
            created_at=utc_now(),
        )
        self._tasks[record.task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def get_many(self, task_ids) -> dict[str, TaskRecord]:
        unique_ids = {str(task_id) for task_id in task_ids if task_id}
        return {task_id: self._tasks[task_id] for task_id in unique_ids if task_id in self._tasks}

    def list(self, project_id: str | None = None) -> list[TaskRecord]:
        values = self._tasks.values()
        if project_id is not None:
            values = [item for item in values if item.project_id == project_id]
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def delete_project_tasks(self, project_id: str) -> int:
        task_ids = [task_id for task_id, task in self._tasks.items() if task.project_id == project_id]
        for task_id in task_ids:
            del self._tasks[task_id]
        return len(task_ids)

    def list_grouped(self, project_ids) -> dict[str, list[TaskRecord]]:
        project_id_set = {str(project_id) for project_id in project_ids if project_id}
        grouped = {project_id: [] for project_id in project_id_set}
        for item in sorted(self._tasks.values(), key=lambda record: record.created_at, reverse=True):
            if item.project_id not in project_id_set:
                continue
            grouped.setdefault(item.project_id, []).append(item)
        return grouped

    def queued_tasks(self) -> list[QueuedTask]:
        return [
            QueuedTask(
                task_id=item.task_id,
                project_id=item.project_id,
                task_type=item.task_type,
                payload=item.payload,
            )
            for item in sorted(self._tasks.values(), key=lambda record: record.created_at)
            if item.status == "queued"
        ]

    def recover_running_tasks(self) -> None:
        for record in self._tasks.values():
            if record.status != "running":
                continue
            record.status = "queued"
            record.started_at = None
            record.finished_at = None
            record.error = None

    def mark_running(self, task_id: str) -> None:
        record = self._tasks[task_id]
        record.status = "running"
        record.started_at = utc_now()
        record.finished_at = None
        record.error = None

    def mark_completed(self, task_id: str, result: dict[str, object]) -> None:
        record = self._tasks[task_id]
        record.status = "completed"
        record.result = result
        record.finished_at = utc_now()

    def update_result(self, task_id: str, result: dict[str, object]) -> None:
        record = self._tasks[task_id]
        merged = dict(record.result or {})
        merged.update(result)
        record.result = merged

    def mark_failed(self, task_id: str, error: str, result: dict[str, object] | None = None) -> None:
        record = self._tasks[task_id]
        record.status = "failed"
        record.error = error
        if result is not None:
            record.result = result
        record.finished_at = utc_now()


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        class ContinuityBackend:
            def generate(self, request):  # pragma: no cover - protocol stub
                raise NotImplementedError

            def generate_structured(self, request, schema):
                return schema()

        self._container_patcher = patch(
            "storyforge.api.main.build_container",
            side_effect=self._build_test_container,
        )
        self._story_backend_patcher = patch(
            "storyforge.pipelines.story_pipeline.build_agent_backend",
            return_value=DeterministicStoryBackend(),
        )
        self._video_backend_patcher = patch(
            "storyforge.pipelines.video_planning.build_agent_backend",
            return_value=DeterministicVideoBackend(),
        )
        self._continuity_backend_patcher = patch(
            "storyforge.pipelines.continuity.build_agent_backend",
            return_value=ContinuityBackend(),
        )
        self._container_patcher.start()
        self._story_backend_patcher.start()
        self._video_backend_patcher.start()
        self._continuity_backend_patcher.start()
        self.addCleanup(self._container_patcher.stop)
        self.addCleanup(self._story_backend_patcher.stop)
        self.addCleanup(self._video_backend_patcher.stop)
        self.addCleanup(self._continuity_backend_patcher.stop)

    def _build_test_container(self, project_root: Path, config) -> AppContainer:
        project_store = InMemoryProjectStore()
        task_store = InMemoryTaskStore()
        context = TaskExecutionContext(
            project_root=project_root,
            config=config,
            project_store=project_store,
            task_store=task_store,
        )
        task_queue = AsyncTaskQueue(
            concurrency=config.queue.concurrency,
            handler=build_task_handler(context),
            store=task_store,
        )
        return AppContainer(
            project_root=project_root,
            config=config,
            project_store=project_store,
            task_queue=task_queue,
        )

    def _create_test_config(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        output_dir = root / "outputs"
        prompt_dir = root / "prompts"
        config_path = root / "storyforge.test.toml"
        config_path.write_text(
            textwrap.dedent(
                f"""
                [llm]
                enabled = true
                provider = "deepseek"
                model = "deepseek-chat"
                temperature = 0.7
                max_tokens = 8192
                api_key_env = "DEEPSEEK_API_KEY"
                base_url = "https://api.deepseek.com/v1"
                timeout_seconds = 120

                [novel]
                default_chapter_count = 8
                default_chapter_word_target = 2500
                chapter_scene_count = 3

                [video]
                segment_duration_seconds = 5
                aspect_ratio = "16:9"
                fps = 24
                character_image_provider = "seedream-4.5"
                scene_image_provider = "seedream-4.5"
                submit_seedance = false

                [seedream]
                enabled = true
                base_url = ""
                api_key_env = "SEEDREAM_API_KEY"
                model = "doubao-seedream-4-5-251128"
                auto_submit = false
                image_size = "2K"
                response_format = "url"
                watermark = false
                download_outputs = true

                [seedance]
                enabled = true
                base_url = ""
                api_key_env = "SEEDANCE_API_KEY"
                model = "doubao-seedance-2-0-260128"
                auto_submit = false
                with_audio = true
                subtitle_mode = "burned_in"
                subtitle_style = "底部居中中文硬字幕，白字黑边，电影感，无额外花字"
                watermark = false
                download_outputs = true
                poll_interval_seconds = 5.0
                max_wait_seconds = 900

                [database]
                host = "127.0.0.1"
                port = 3306
                user = "root"
                password = ""
                password_env = "STORYFORGE_DB_PASSWORD"
                database = "storyforge"
                charset = "utf8mb4"
                connect_timeout_seconds = 5
                auto_create_schema = true

                [queue]
                concurrency = 2
                poll_interval_seconds = 0.2

                [paths]
                output_dir = "{output_dir}"
                prompt_dir = "{prompt_dir}"
                """
            ).strip(),
            encoding="utf-8",
        )
        return config_path

    def _wait_for_completion(self, client: TestClient, task_id: str) -> dict[str, object]:
        payload: dict[str, object] = {}
        for _ in range(60):
            task_response = client.get(f"/v1/tasks/{task_id}")
            self.assertEqual(task_response.status_code, 200)
            payload = task_response.json()
            if payload["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        return payload

    def _run_structuring_pipeline(
        self,
        client: TestClient,
        *,
        project_id: str,
        source_task_id: str,
        continuity_review_mode: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        scene_payload: dict[str, object] = {
            "project_id": project_id,
            "source_task_id": source_task_id,
            "use_llm": True,
        }
        if continuity_review_mode is not None:
            scene_payload["continuity_review_mode"] = continuity_review_mode
        scene_response = client.post("/v1/projects/scene-structure", json=scene_payload)
        self.assertEqual(scene_response.status_code, 202)
        scene_task = self._wait_for_completion(client, scene_response.json()["task_id"])
        self.assertEqual(scene_task["status"], "completed")

        segment_payload: dict[str, object] = {
            "project_id": project_id,
            "source_task_id": source_task_id,
            "use_llm": True,
        }
        if continuity_review_mode is not None:
            segment_payload["continuity_review_mode"] = continuity_review_mode
        segment_response = client.post("/v1/projects/segment-contracts", json=segment_payload)
        self.assertEqual(segment_response.status_code, 202)
        segment_task = self._wait_for_completion(client, segment_response.json()["task_id"])
        self.assertEqual(segment_task["status"], "completed")
        return scene_task, segment_task

    def test_web_console_bootstrap(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("StoryForge Studio", response.text)

            static_js = client.get("/static/app.js")
            self.assertEqual(static_js.status_code, 200)
            self.assertIn('import { initApp } from "./app/main.js";', static_js.text)
            self.assertEqual(
                static_js.headers.get("cache-control"),
                "no-store, no-cache, must-revalidate",
            )

            static_main_js = client.get("/static/app/main.js")
            self.assertEqual(static_main_js.status_code, 200)
            self.assertIn("refreshTasks", static_main_js.text)
            self.assertEqual(
                static_main_js.headers.get("cache-control"),
                "no-store, no-cache, must-revalidate",
            )

            bootstrap = client.get("/v1/ui/bootstrap")
            self.assertEqual(bootstrap.status_code, 200)
            payload = bootstrap.json()
            self.assertIn("default_brief", payload)
            self.assertIn("llm_provider", payload)
            self.assertIn("llm_model", payload)
            self.assertIn("continuity_review_mode", payload)
            self.assertIn("available_llm_options", payload)
            self.assertIn("seedream_model", payload)
            self.assertIn("seedance_model", payload)
            self.assertIn("seedream_watermark", payload)
            self.assertIn("seedance_watermark", payload)
            self.assertFalse(payload["seedream_watermark"])
            self.assertFalse(payload["seedance_watermark"])
            self.assertTrue(
                any(
                    item["provider"] == "openai" and item["model"] == "gpt-5.4"
                    for item in payload["available_llm_options"]
                )
            )

    def test_submit_complete_job_and_keep_project_history_within_process(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "测试故事",
                        "idea": "一名调查员在暴雨夜追查失踪列车。",
                        "genre": "悬疑",
                        "tone": "压迫、电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 3,
                        "total_word_target": 9000,
                        "must_include": ["失踪列车"],
                        "style_keywords": ["暴雨", "车站", "霓虹"],
                    },
                    "use_llm": True,
                    "llm_provider": "openai",
                    "llm_model": "gpt-5.4",
                    "continuity_review_mode": "on",
                    "seedream_watermark": True,
                    "seedance_watermark": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            project_id = response.json()["project_id"]
            source_task_id = response.json()["task_id"]
            payload = self._wait_for_completion(client, source_task_id)

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["project_id"], project_id)
            self.assertEqual(payload["payload"]["llm_provider"], "openai")
            self.assertEqual(payload["payload"]["llm_model"], "gpt-5.4")
            self.assertEqual(payload["payload"]["continuity_review_mode"], "on")
            self.assertTrue(payload["payload"]["seedream_watermark"])
            self.assertTrue(payload["payload"]["seedance_watermark"])
            self.assertTrue(payload["result"]["seedream_watermark"])
            self.assertTrue(payload["result"]["seedance_watermark"])
            self.assertEqual(payload["result"]["pipeline_stage"], "story_source_completed")

            _, segment_task = self._run_structuring_pipeline(
                client,
                project_id=project_id,
                source_task_id=source_task_id,
                continuity_review_mode="on",
            )

            artifacts_response = client.get(f"/v1/tasks/{source_task_id}/artifacts")
            self.assertEqual(artifacts_response.status_code, 200)
            artifacts = artifacts_response.json()
            self.assertTrue(artifacts["available"])
            self.assertTrue(artifacts["documents"])
            self.assertNotIn("chapters", artifacts)
            self.assertIn("planned_segments", artifacts)
            self.assertTrue(artifacts["planned_segments"])
            document_names = {item["name"] for item in artifacts["documents"]}
            self.assertIn("story_source.json", document_names)
            self.assertIn("novel_package.json", document_names)
            self.assertIn("novel_audit.json", document_names)
            self.assertIn("scene_plan.json", document_names)
            self.assertIn("continuity_report.json", document_names)
            self.assertIn("scene_id", artifacts["planned_segments"][0])
            self.assertIn("continuity_report", artifacts)
            self.assertTrue(artifacts["continuity_report"])
            self.assertIn("continuity_summary", artifacts)
            self.assertTrue(artifacts["continuity_summary"])
            self.assertIn("status", artifacts["continuity_summary"])
            self.assertIn("issue_count", artifacts["continuity_summary"])
            self.assertIn("review_mode_requested", artifacts["continuity_summary"])
            self.assertIn("v2_review_status", artifacts["continuity_summary"])
            self.assertIn("continuity_scene_groups", artifacts)
            self.assertIn("continuity_segment_groups", artifacts)
            self.assertIsInstance(artifacts["continuity_scene_groups"], list)
            self.assertIsInstance(artifacts["continuity_segment_groups"], list)

            first_planned_segment = artifacts["planned_segments"][0]
            self.assertIn("scene_master_frame_prompt", first_planned_segment)
            self.assertIn("start_frame_prompt", first_planned_segment)
            self.assertIn("end_frame_prompt", first_planned_segment)
            self.assertIn("video_prompt", first_planned_segment)
            self.assertIn("submitted_video_prompt", first_planned_segment)
            self.assertIn("seedance_motion_prompt", first_planned_segment)
            self.assertIn("motion_plan", first_planned_segment)
            self.assertIn("submitted_prompt_variant", first_planned_segment)
            self.assertIn("submitted_reference_bindings", first_planned_segment)
            self.assertIn("scene_master_frame_request", first_planned_segment)
            self.assertIn("start_frame_request", first_planned_segment)
            self.assertIn("mid_frame_request", first_planned_segment)
            self.assertIn("end_frame_request", first_planned_segment)
            self.assertIn("video_request", first_planned_segment)
            self.assertTrue(first_planned_segment["scene_master_frame_request"])
            self.assertTrue(first_planned_segment["start_frame_request"])
            self.assertTrue(first_planned_segment["video_request"])
            if not first_planned_segment["requires_mid_frame"]:
                self.assertFalse(first_planned_segment["mid_frame"])
                self.assertEqual(first_planned_segment["mid_frame_prompt"], "")
                self.assertIsNone(first_planned_segment["mid_frame_request"])
            continuity_report_path = Path(segment_task["result"]["output_dir"]) / "continuity_report.json"
            continuity_payload = json.loads(continuity_report_path.read_text(encoding="utf-8"))
            continuity_payload["status"] = "critical"
            continuity_payload["review_mode_requested"] = "on"
            continuity_payload["review_mode_effective"] = "on"
            continuity_payload["summary"].update(
                {
                    "issue_count": 2,
                    "high_risk_count": 1,
                    "medium_risk_count": 1,
                    "low_risk_count": 0,
                    "scene_issue_count": 1,
                    "segment_issue_count": 1,
                }
            )
            continuity_payload["recommended_actions"] = [
                {
                    "action": "regenerate_scene_master_frame",
                    "label": "重生成场景母图",
                    "count": 1,
                },
                {
                    "action": "regenerate_video",
                    "label": "重生成片段视频",
                    "count": 1,
                },
            ]
            continuity_payload["scene_issues"] = [
                {
                    "scope": "scene",
                    "severity": "medium",
                    "code": "scene_master_frame_missing_output",
                    "message": "场景母图缺失，需要重新生成场景母图。",
                    "scene_id": first_planned_segment["scene_id"],
                    "segment_id": "",
                    "recommended_action": "regenerate_scene_master_frame",
                    "recommended_action_label": "重生成场景母图",
                    "details": {"scene_master_frame_path": "missing.png"},
                }
            ]
            continuity_payload["segment_issues"] = [
                {
                    "scope": "segment",
                    "severity": "high",
                    "code": "video_generation_failed",
                    "message": "片段视频生成失败，需要重新生成视频。",
                    "scene_id": first_planned_segment["scene_id"],
                    "segment_id": first_planned_segment["segment_id"],
                    "recommended_action": "regenerate_video",
                    "recommended_action_label": "重生成片段视频",
                    "details": {"error": "video failed"},
                }
            ]
            continuity_payload["v2_llm_review"] = {
                "status": "completed",
                "triggered": True,
                "mode_requested": "on",
                "mode_effective": "on",
                "reviewer_provider": "openai",
                "reviewer_model": "gpt-5.4",
                "note": "用户强制开启 LLM 软审校。",
                "summary": {
                    "issue_count": 1,
                    "high_risk_count": 1,
                    "medium_risk_count": 0,
                    "low_risk_count": 0,
                    "scene_issue_count": 0,
                    "segment_issue_count": 1,
                },
                "recommended_actions": [
                    {
                        "action": "regenerate_video",
                        "label": "重生成片段视频",
                        "count": 1,
                    }
                ],
                "scene_issues": [],
                "segment_issues": [
                    {
                        "scope": "segment",
                        "severity": "high",
                        "code": "llm_dialogue_delivery_risk",
                        "message": "对白密度偏高，观感上仍可能说不完。",
                        "scene_id": first_planned_segment["scene_id"],
                        "segment_id": first_planned_segment["segment_id"],
                        "recommended_action": "regenerate_video",
                        "recommended_action_label": "重生成片段视频",
                        "details": {"evidence": "timed_beats 节奏过密"},
                    }
                ],
            }
            continuity_report_path.write_text(
                json.dumps(continuity_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            artifacts_response = client.get(f"/v1/tasks/{source_task_id}/artifacts")
            self.assertEqual(artifacts_response.status_code, 200)
            artifacts = artifacts_response.json()
            scene_group = next(
                item
                for item in artifacts["continuity_scene_groups"]
                if item["scene_id"] == first_planned_segment["scene_id"]
            )
            segment_group = next(
                item
                for item in artifacts["continuity_segment_groups"]
                if item["segment_id"] == first_planned_segment["segment_id"]
            )
            self.assertEqual(scene_group["scope"], "scene")
            self.assertEqual(scene_group["issue_count"], 1)
            self.assertEqual(scene_group["issues"][0]["code"], "scene_master_frame_missing_output")
            self.assertEqual(segment_group["scope"], "segment")
            self.assertEqual(segment_group["high_risk_count"], 1)
            self.assertEqual(segment_group["issues"][0]["code"], "video_generation_failed")
            self.assertEqual(artifacts["continuity_summary"]["review_mode_requested"], "on")
            self.assertEqual(artifacts["continuity_summary"]["v2_review_status"], "completed")

            story_source_item = next(
                item for item in artifacts["documents"] if item["name"] == "story_source.json"
            )
            story_source_response = client.get(story_source_item["url"])
            self.assertEqual(story_source_response.status_code, 200)
            self.assertIn("chapters", story_source_response.text)

            projects_response = client.get("/v1/projects")
            self.assertEqual(projects_response.status_code, 200)
            projects = projects_response.json()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["project_id"], project_id)
            self.assertEqual(projects[0]["run_count"], 1)

            project_detail_response = client.get(f"/v1/projects/{project_id}")
            self.assertEqual(project_detail_response.status_code, 200)
            project_detail = project_detail_response.json()
            self.assertEqual(project_detail["project_id"], project_id)
            self.assertEqual(project_detail["tasks"][0]["task_id"], segment_task["task_id"])
            self.assertEqual(project_detail["tasks"][0]["project_id"], project_id)
            self.assertEqual(project_detail["latest_task_id"], segment_task["task_id"])
            self.assertEqual(
                {item["task_id"] for item in project_detail["tasks"]},
                {
                    source_task_id,
                    segment_task["task_id"],
                    next(
                        item["task_id"]
                        for item in project_detail["tasks"]
                        if item["task_type"] == "project.scene_structure"
                    ),
                },
            )

    def test_story_job_accepts_openai_selection(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "双模型测试",
                        "idea": "毕业前夜，两个人在空教室里交换一封一直没有寄出的信。",
                        "genre": "青春 / 情感",
                        "tone": "克制、温柔、电影感",
                        "target_audience": "青年读者",
                        "chapter_count": 1,
                        "total_word_target": 1200,
                        "must_include": ["空教室", "信件"],
                        "style_keywords": ["夕光", "安静", "毕业季"],
                    },
                    "use_llm": True,
                    "llm_provider": "openai",
                    "llm_model": "gpt-5.4",
                    "continuity_review_mode": "off",
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            payload = self._wait_for_completion(client, task_id)

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["payload"]["llm_provider"], "openai")
            self.assertEqual(payload["payload"]["llm_model"], "gpt-5.4")
            self.assertEqual(payload["payload"]["continuity_review_mode"], "off")
            self.assertEqual(payload["result"]["pipeline_stage"], "story_source_completed")

    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    def test_stage_jobs_accept_segment_id_and_run_single_segment(
        self,
        mock_run_scene_image_pipeline,
        mock_run_video_render_pipeline,
    ) -> None:
        def fake_scene_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            return SimpleNamespace(
                project_package=SimpleNamespace(title="单片段测试"),
                output_dir=output_dir,
                character_bible_path=output_dir / "character_visual_bible.json",
                character_images_path=output_dir / "character_image_manifest.json",
                scene_plan_path=output_dir / "scene_plan.json",
                segment_plan_path=output_dir / "segment_plan.json",
                scene_images_path=output_dir / "scene_image_manifest.json",
                manifest_path=output_dir / "seedance_manifest.json",
                seedream_execution_path=output_dir / "seedream_scene_execution.json",
                character_seedream_execution_path=output_dir / "seedream_character_execution.json",
                scene_seedream_execution_path=output_dir / "seedream_scene_execution.json",
                seedream_execution=SimpleNamespace(
                    submitted=True,
                    generated_count=2,
                    failed_count=0,
                    note="ok",
                ),
            )

        def fake_video_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            return SimpleNamespace(
                output_dir=output_dir,
                manifest_path=output_dir / "seedance_manifest.json",
                seedance_execution_path=output_dir / "seedance_execution.json",
                rendered_clip_paths=[],
                full_story_path=None,
                seedance_execution=SimpleNamespace(
                    submitted=True,
                    completed_count=1,
                    failed_count=0,
                    pending_count=0,
                    note="ok",
                ),
            )

        mock_run_scene_image_pipeline.side_effect = fake_scene_pipeline
        mock_run_video_render_pipeline.side_effect = fake_video_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "片段任务测试",
                        "idea": "一名调查员和搭档在夜雨站台追查失踪列车。",
                        "genre": "悬疑",
                        "tone": "电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1200,
                        "must_include": ["站台", "搭档"],
                        "style_keywords": ["暴雨", "列车"],
                    },
                    "use_llm": True,
                    "seedream_watermark": True,
                    "seedance_watermark": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")
            source_task = self._wait_for_completion(client, source_task_id)
            self.assertTrue(source_task["result"]["seedream_watermark"])
            self.assertTrue(source_task["result"]["seedance_watermark"])

            scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(scene_structure_response.status_code, 202)
            scene_structure_task_id = scene_structure_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, scene_structure_task_id)["status"], "completed")

            segment_contracts_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(segment_contracts_response.status_code, 202)
            segment_contracts_task_id = segment_contracts_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, segment_contracts_task_id)["status"], "completed")

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            segment_id = artifacts["planned_segments"][0]["segment_id"]

            scene_response = client.post(
                "/v1/projects/scenes",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "segment_id": segment_id,
                },
            )
            self.assertEqual(scene_response.status_code, 202)
            scene_task_id = scene_response.json()["task_id"]
            scene_task = self._wait_for_completion(client, scene_task_id)
            self.assertEqual(scene_task["status"], "completed")
            self.assertEqual(scene_task["payload"]["segment_id"], segment_id)
            self.assertEqual(scene_task["result"]["segment_id"], segment_id)
            self.assertEqual(mock_run_scene_image_pipeline.call_args.kwargs["segment_id"], segment_id)
            self.assertTrue(mock_run_scene_image_pipeline.call_args.kwargs["config"].seedream.watermark)
            self.assertTrue(mock_run_scene_image_pipeline.call_args.kwargs["config"].seedance.watermark)

            video_response = client.post(
                "/v1/projects/videos",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "segment_id": segment_id,
                },
            )
            self.assertEqual(video_response.status_code, 202)
            video_task_id = video_response.json()["task_id"]
            video_task = self._wait_for_completion(client, video_task_id)
            self.assertEqual(video_task["status"], "completed")
            self.assertEqual(video_task["payload"]["segment_id"], segment_id)
            self.assertEqual(video_task["result"]["segment_id"], segment_id)
            self.assertEqual(mock_run_video_render_pipeline.call_args.kwargs["segment_id"], segment_id)
            self.assertTrue(mock_run_video_render_pipeline.call_args.kwargs["config"].seedream.watermark)
            self.assertTrue(mock_run_video_render_pipeline.call_args.kwargs["config"].seedance.watermark)

    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    def test_scene_stage_job_accepts_scene_id_master_only(
        self,
        mock_run_scene_image_pipeline,
    ) -> None:
        def fake_scene_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            return SimpleNamespace(
                project_package=SimpleNamespace(title="场景母图测试"),
                output_dir=output_dir,
                character_bible_path=output_dir / "character_visual_bible.json",
                character_images_path=output_dir / "character_image_manifest.json",
                scene_plan_path=output_dir / "scene_plan.json",
                segment_plan_path=output_dir / "segment_plan.json",
                scene_images_path=output_dir / "scene_image_manifest.json",
                manifest_path=output_dir / "seedance_manifest.json",
                seedream_execution_path=output_dir / "seedream_scene_execution.json",
                character_seedream_execution_path=output_dir / "seedream_character_execution.json",
                scene_seedream_execution_path=output_dir / "seedream_scene_execution.json",
                seedream_execution=SimpleNamespace(
                    submitted=True,
                    generated_count=1,
                    failed_count=0,
                    note="ok",
                ),
            )

        mock_run_scene_image_pipeline.side_effect = fake_scene_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "场景母图测试",
                        "idea": "雨夜车站里，两人隔着检票口对视。",
                        "genre": "情感",
                        "tone": "电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1200,
                        "must_include": ["车站"],
                        "style_keywords": ["夜雨", "检票口"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(scene_structure_response.status_code, 202)
            scene_structure_task_id = scene_structure_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, scene_structure_task_id)["status"], "completed")

            segment_contracts_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(segment_contracts_response.status_code, 202)
            segment_contracts_task_id = segment_contracts_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, segment_contracts_task_id)["status"], "completed")

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            scene_id = artifacts["planned_segments"][0]["scene_id"]

            response = client.post(
                "/v1/projects/scenes",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "scene_id": scene_id,
                    "master_only": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            task = self._wait_for_completion(client, task_id)
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["payload"]["scene_id"], scene_id)
            self.assertTrue(task["payload"]["master_only"])
            self.assertEqual(task["result"]["scene_id"], scene_id)
            self.assertTrue(task["result"]["master_only"])
            self.assertEqual(mock_run_scene_image_pipeline.call_args.kwargs["scene_id"], scene_id)
            self.assertTrue(mock_run_scene_image_pipeline.call_args.kwargs["master_only"])

    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    def test_stage_jobs_accept_scene_id_and_run_single_scene(
        self,
        mock_run_scene_image_pipeline,
        mock_run_video_render_pipeline,
    ) -> None:
        def fake_scene_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            return SimpleNamespace(
                project_package=SimpleNamespace(title="单场景测试"),
                output_dir=output_dir,
                character_bible_path=output_dir / "character_visual_bible.json",
                character_images_path=output_dir / "character_image_manifest.json",
                scene_plan_path=output_dir / "scene_plan.json",
                segment_plan_path=output_dir / "segment_plan.json",
                scene_images_path=output_dir / "scene_image_manifest.json",
                manifest_path=output_dir / "seedance_manifest.json",
                seedream_execution_path=output_dir / "seedream_scene_execution.json",
                character_seedream_execution_path=output_dir / "seedream_character_execution.json",
                scene_seedream_execution_path=output_dir / "seedream_scene_execution.json",
                seedream_execution=SimpleNamespace(
                    submitted=True,
                    generated_count=2,
                    failed_count=0,
                    note="ok",
                ),
            )

        def fake_video_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            return SimpleNamespace(
                output_dir=output_dir,
                manifest_path=output_dir / "seedance_manifest.json",
                seedance_execution_path=output_dir / "seedance_execution.json",
                rendered_clip_paths=[],
                full_story_path=None,
                seedance_execution=SimpleNamespace(
                    submitted=True,
                    completed_count=1,
                    failed_count=0,
                    pending_count=0,
                    note="ok",
                ),
            )

        mock_run_scene_image_pipeline.side_effect = fake_scene_pipeline
        mock_run_video_render_pipeline.side_effect = fake_video_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "单场景任务测试",
                        "idea": "凌晨的便利店门口，两人靠着自动贩卖机沉默告别。",
                        "genre": "情感",
                        "tone": "电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1200,
                        "must_include": ["便利店"],
                        "style_keywords": ["凌晨", "路灯"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(scene_structure_response.status_code, 202)
            scene_structure_task_id = scene_structure_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, scene_structure_task_id)["status"], "completed")

            segment_contracts_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(segment_contracts_response.status_code, 202)
            segment_contracts_task_id = segment_contracts_response.json()["task_id"]
            self.assertEqual(self._wait_for_completion(client, segment_contracts_task_id)["status"], "completed")

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            scene_id = artifacts["planned_segments"][0]["scene_id"]

            scene_response = client.post(
                "/v1/projects/scenes",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "scene_id": scene_id,
                },
            )
            self.assertEqual(scene_response.status_code, 202)
            scene_task_id = scene_response.json()["task_id"]
            scene_task = self._wait_for_completion(client, scene_task_id)
            self.assertEqual(scene_task["status"], "completed")
            self.assertEqual(scene_task["payload"]["scene_id"], scene_id)
            self.assertEqual(scene_task["result"]["scene_id"], scene_id)
            self.assertEqual(mock_run_scene_image_pipeline.call_args.kwargs["scene_id"], scene_id)
            self.assertFalse(mock_run_scene_image_pipeline.call_args.kwargs.get("master_only", False))

            video_response = client.post(
                "/v1/projects/videos",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "scene_id": scene_id,
                },
            )
            self.assertEqual(video_response.status_code, 202)
            video_task_id = video_response.json()["task_id"]
            video_task = self._wait_for_completion(client, video_task_id)
            self.assertEqual(video_task["status"], "completed")
            self.assertEqual(video_task["payload"]["scene_id"], scene_id)
            self.assertEqual(video_task["result"]["scene_id"], scene_id)
            self.assertEqual(mock_run_video_render_pipeline.call_args.kwargs["scene_id"], scene_id)

    @patch("storyforge.application.task_handlers.run_segment_continuity_repair_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    def test_continuity_repair_job_rewrites_single_segment_without_rerunning_media(
        self,
        mock_run_video_render_pipeline,
        mock_run_scene_image_pipeline,
        mock_run_segment_continuity_repair_pipeline,
    ) -> None:
        def fake_repair_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            segment_id = kwargs["segment_id"]
            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=output_dir / "character_visual_bible.json",
                character_images_path=output_dir / "character_image_manifest.json",
                scene_plan_path=output_dir / "scene_plan.json",
                segment_plan_path=output_dir / "segment_plan.json",
                scene_images_path=output_dir / "scene_image_manifest.json",
                manifest_path=output_dir / "seedance_manifest.json",
                continuity_report_path=output_dir / "continuity_report.json",
                repair_report_path=output_dir / f"continuity_repair_{segment_id}.json",
                project_package=SimpleNamespace(title="连续性修复测试"),
                manifest=SimpleNamespace(clips=[]),
                segment_id=segment_id,
                repair_summary="已根据连续性问题重写片段，等待人工决定是否重跑媒体阶段。",
                repair_action="rewrite_segment_contract",
            )

        mock_run_segment_continuity_repair_pipeline.side_effect = fake_repair_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "连续性修复任务测试",
                        "idea": "毕业前夜，两人在旧教学楼走廊里交换那封一直没有寄出的信。",
                        "genre": "情感",
                        "tone": "克制、电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1400,
                        "must_include": ["旧教学楼", "信件"],
                        "style_keywords": ["夜色", "走廊", "毕业季"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            self._run_structuring_pipeline(
                client,
                project_id=project_id,
                source_task_id=source_task_id,
            )

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            segment_id = artifacts["planned_segments"][0]["segment_id"]

            response = client.post(
                "/v1/projects/continuity-repair",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "segment_id": segment_id,
                    "use_llm": True,
                    "continuity_review_mode": "on",
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            task = self._wait_for_completion(client, task_id)

            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["payload"]["segment_id"], segment_id)
            self.assertEqual(task["payload"]["pipeline_root_task_id"], source_task_id)
            self.assertEqual(task["payload"]["continuity_review_mode"], "on")
            self.assertEqual(task["result"]["segment_id"], segment_id)
            self.assertEqual(task["result"]["pipeline_stage"], "continuity_repair_plan_completed")
            self.assertEqual(task["result"]["repair_execution_mode"], "plan_only")
            self.assertTrue(task["result"]["media_regeneration_required"])
            self.assertEqual(
                task["result"]["pending_media_actions"],
                ["regenerate_scene_images", "regenerate_video"],
            )
            self.assertEqual(
                task["result"]["repair_summary"],
                "已根据连续性问题重写片段，等待人工决定是否重跑媒体阶段。",
            )
            self.assertEqual(
                mock_run_segment_continuity_repair_pipeline.call_args.kwargs["segment_id"],
                segment_id,
            )
            mock_run_scene_image_pipeline.assert_not_called()
            mock_run_video_render_pipeline.assert_not_called()

    @patch("storyforge.application.task_handlers.run_scene_continuity_repair_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    def test_continuity_repair_job_plans_single_scene_fix_without_rerunning_media(
        self,
        mock_run_video_render_pipeline,
        mock_run_scene_image_pipeline,
        mock_run_scene_continuity_repair_pipeline,
    ) -> None:
        def fake_scene_repair_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            scene_id = kwargs["scene_id"]
            affected_segment_ids = ("localized-seg-1",)
            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=output_dir / "character_visual_bible.json",
                character_images_path=output_dir / "character_image_manifest.json",
                scene_plan_path=output_dir / "scene_plan.json",
                segment_plan_path=output_dir / "segment_plan.json",
                scene_images_path=output_dir / "scene_image_manifest.json",
                manifest_path=output_dir / "seedance_manifest.json",
                continuity_report_path=output_dir / "continuity_report.json",
                repair_report_path=output_dir / f"continuity_repair_{scene_id}.json",
                project_package=SimpleNamespace(title="场景智能修复测试"),
                manifest=SimpleNamespace(clips=[]),
                segment_id="",
                scene_id=scene_id,
                repair_summary="已识别 scene 级连续性问题，并完成修复规划。当前只更新修复方案，不会自动重生成场景母图或重跑受影响片段，后续需要人工决定是否执行。",
                repair_action="regenerate_scene_master_frame",
                selection_mode="localized_segments",
                affected_segment_ids=affected_segment_ids,
            )

        mock_run_scene_continuity_repair_pipeline.side_effect = fake_scene_repair_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "场景智能修复任务测试",
                        "idea": "雨夜的旧剧场后台，一张海报被风吹得不断拍打墙面。",
                        "genre": "情感",
                        "tone": "冷静、电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1400,
                        "must_include": ["旧剧场", "海报"],
                        "style_keywords": ["雨夜", "后台", "风声"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            self._run_structuring_pipeline(
                client,
                project_id=project_id,
                source_task_id=source_task_id,
            )

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            scene_id = artifacts["planned_segments"][0]["scene_id"]

            response = client.post(
                "/v1/projects/continuity-repair",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "scene_id": scene_id,
                    "use_llm": True,
                    "continuity_review_mode": "on",
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            task = self._wait_for_completion(client, task_id)

            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["payload"]["scene_id"], scene_id)
            self.assertEqual(task["payload"]["pipeline_root_task_id"], source_task_id)
            self.assertEqual(task["result"]["scene_id"], scene_id)
            self.assertEqual(task["result"]["pipeline_stage"], "continuity_repair_plan_completed")
            self.assertEqual(task["result"]["repair_execution_mode"], "plan_only")
            self.assertTrue(task["result"]["media_regeneration_required"])
            self.assertEqual(
                task["result"]["pending_media_actions"],
                [
                    "regenerate_scene_master_frame",
                    "regenerate_scene_images",
                    "regenerate_video",
                ],
            )
            self.assertEqual(task["result"]["selection_mode"], "localized_segments")
            self.assertEqual(task["result"]["affected_segment_ids"], ["localized-seg-1"])
            self.assertEqual(
                mock_run_scene_continuity_repair_pipeline.call_args.kwargs["scene_id"],
                scene_id,
            )
            mock_run_scene_image_pipeline.assert_not_called()
            mock_run_video_render_pipeline.assert_not_called()

    @patch("storyforge.application.task_handlers.run_segment_continuity_repair_pipeline")
    def test_continuity_repair_job_returns_completed_noop_when_segment_has_no_issues(
        self,
        mock_run_segment_continuity_repair_pipeline,
    ) -> None:
        mock_run_segment_continuity_repair_pipeline.side_effect = ValueError(
            "Segment ch01-sc01-seg01 has no continuity issues to repair."
        )

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "连续性无问题 noop 测试",
                        "idea": "两人在毕业季的校园花园里平静散步。",
                        "genre": "情感",
                        "tone": "温柔",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1000,
                        "must_include": ["花园"],
                        "style_keywords": ["毕业季"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            self._run_structuring_pipeline(
                client,
                project_id=project_id,
                source_task_id=source_task_id,
            )

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            segment_id = artifacts["planned_segments"][0]["segment_id"]

            response = client.post(
                "/v1/projects/continuity-repair",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "segment_id": segment_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            task = self._wait_for_completion(client, task_id)

            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["result"]["repair_execution_mode"], "noop")
            self.assertFalse(task["result"]["media_regeneration_required"])
            self.assertEqual(task["result"]["pending_media_actions"], [])
            self.assertEqual(task["result"]["segment_id"], segment_id)
            self.assertIn("当前没有需要修复的连续性问题", task["result"]["repair_summary"])

    @patch("storyforge.application.task_handlers.run_scene_continuity_repair_pipeline")
    def test_continuity_repair_job_returns_completed_noop_when_scene_has_no_issues(
        self,
        mock_run_scene_continuity_repair_pipeline,
    ) -> None:
        mock_run_scene_continuity_repair_pipeline.side_effect = ValueError(
            "Scene ch01-sc01 has no continuity issues to repair."
        )

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "scene noop 测试",
                        "idea": "两人在校园傍晚平静道别。",
                        "genre": "情感",
                        "tone": "克制",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 1000,
                        "must_include": ["校园"],
                        "style_keywords": ["傍晚"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            source_task_id = story_response.json()["task_id"]
            project_id = story_response.json()["project_id"]
            self.assertEqual(self._wait_for_completion(client, source_task_id)["status"], "completed")

            self._run_structuring_pipeline(
                client,
                project_id=project_id,
                source_task_id=source_task_id,
            )

            artifacts = client.get(f"/v1/tasks/{source_task_id}/artifacts").json()
            scene_id = artifacts["planned_segments"][0]["scene_id"]

            response = client.post(
                "/v1/projects/continuity-repair",
                json={
                    "project_id": project_id,
                    "source_task_id": source_task_id,
                    "scene_id": scene_id,
                    "use_llm": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]
            task = self._wait_for_completion(client, task_id)

            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["result"]["repair_execution_mode"], "noop")
            self.assertFalse(task["result"]["media_regeneration_required"])
            self.assertEqual(task["result"]["pending_media_actions"], [])
            self.assertEqual(task["result"]["scene_id"], scene_id)
            self.assertIn("当前没有需要修复的连续性问题", task["result"]["repair_summary"])

    @patch("storyforge.application.task_handlers.run_segment_continuity_repair_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_continuity_repair_pipeline")
    def test_continuity_repair_batch_job_repairs_scene_and_segment_contracts(
        self,
        mock_run_scene_continuity_repair_pipeline,
        mock_run_segment_continuity_repair_pipeline,
    ) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            container = app.state.container
            brief = {
                "title_hint": "批量合同修复测试",
                "idea": "两人在毕业季校园里反复错过，直到镜湖边告白。",
                "genre": "情感",
                "tone": "温柔",
                "target_audience": "成年读者",
                "chapter_count": 1,
                "total_word_target": 1200,
                "must_include": ["镜湖"],
                "style_keywords": ["校园", "傍晚"],
            }
            project = container.project_store.create(brief)
            project_id = project.project_id

            with tempfile.TemporaryDirectory() as temp_dir:
                output_dir = Path(temp_dir)
                scene_id = "ch01-sc01"
                segment_id = "ch01-sc01-seg01"
                for filename, payload in (
                    ("character_visual_bible.json", {}),
                    ("character_image_manifest.json", []),
                    ("scene_plan.json", {"scenes": []}),
                    ("segment_plan.json", []),
                    ("scene_image_manifest.json", []),
                    ("seedance_manifest.json", {"clips": []}),
                ):
                    (output_dir / filename).write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                report_path = output_dir / "continuity_report.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "scene_issues": [
                                {
                                    "scope": "scene",
                                    "severity": "high",
                                    "code": "scene_baseline_weak",
                                    "message": "场景基线太弱。",
                                    "scene_id": scene_id,
                                    "segment_id": "",
                                    "recommended_action": "regenerate_scene_master_frame",
                                    "recommended_action_label": "重生成场景母图",
                                    "details": {},
                                }
                            ],
                            "segment_issues": [
                                {
                                    "scope": "segment",
                                    "severity": "medium",
                                    "code": "opening_match_weak",
                                    "message": "开场承接偏弱。",
                                    "scene_id": scene_id,
                                    "segment_id": segment_id,
                                    "recommended_action": "regenerate_scene_images",
                                    "recommended_action_label": "重生成片段场景图",
                                    "details": {},
                                }
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                source_record = container.task_queue.store.create(
                    project_id=project_id,
                    task_type="project.story",
                    payload={
                        "project_id": project_id,
                        "brief": brief,
                        "use_llm": True,
                    },
                )
                source_result = {
                    "project_id": project_id,
                    "story_title": "批量合同修复测试",
                    "output_dir": str(output_dir),
                    "story_source_path": str(output_dir / "story_source.json"),
                    "story_source_revision": utc_now(),
                    "pipeline_stage": "segment_contracts_completed",
                    "task_stage": "story",
                    "pipeline_root_task_id": source_record.task_id,
                    "source_task_id": source_record.task_id,
                    "artifact_revision": utc_now(),
                    "continuity_review_mode": "auto",
                }
                container.task_queue.store.mark_completed(source_record.task_id, source_result)
                container.project_store.attach_task(project_id, source_record.task_id, brief)
                container.project_store.mark_task_result(project_id, source_record.task_id, source_result)

                def remove_scene_issue(*, output_root, scene_id, **kwargs):
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    payload["scene_issues"] = [
                        item for item in payload.get("scene_issues", [])
                        if str(item.get("scene_id", "")) != str(scene_id)
                    ]
                    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    return SimpleNamespace(
                        character_bible_path=output_dir / "character_visual_bible.json",
                        character_images_path=output_dir / "character_image_manifest.json",
                        scene_plan_path=output_dir / "scene_plan.json",
                        segment_plan_path=output_dir / "segment_plan.json",
                        scene_images_path=output_dir / "scene_image_manifest.json",
                        manifest_path=output_dir / "seedance_manifest.json",
                        continuity_report_path=report_path,
                        repair_action="regenerate_scene_master_frame",
                    )

                def remove_segment_issue(*, output_root, segment_id, **kwargs):
                    payload = json.loads(report_path.read_text(encoding="utf-8"))
                    payload["segment_issues"] = [
                        item for item in payload.get("segment_issues", [])
                        if str(item.get("segment_id", "")) != str(segment_id)
                    ]
                    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    return SimpleNamespace(
                        character_bible_path=output_dir / "character_visual_bible.json",
                        character_images_path=output_dir / "character_image_manifest.json",
                        scene_plan_path=output_dir / "scene_plan.json",
                        segment_plan_path=output_dir / "segment_plan.json",
                        scene_images_path=output_dir / "scene_image_manifest.json",
                        manifest_path=output_dir / "seedance_manifest.json",
                        continuity_report_path=report_path,
                        repair_action="rewrite_segment_contract",
                    )

                mock_run_scene_continuity_repair_pipeline.side_effect = remove_scene_issue
                mock_run_segment_continuity_repair_pipeline.side_effect = remove_segment_issue

                response = client.post(
                    "/v1/projects/continuity-repair-batch",
                    json={
                        "project_id": project_id,
                        "source_task_id": source_record.task_id,
                        "max_units_per_batch": 2,
                    },
                )
                self.assertEqual(response.status_code, 202)
                task_id = response.json()["task_id"]
                task = self._wait_for_completion(client, task_id)

                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["task_type"], "project.continuity_repair_batch")
                self.assertEqual(task["result"]["repair_execution_mode"], "plan_only")
                self.assertEqual(task["result"]["processed_unit_count"], 2)
                self.assertEqual(task["result"]["repaired_unit_count"], 2)
                self.assertEqual(task["result"]["repaired_scene_ids"], [scene_id])
                self.assertEqual(task["result"]["repaired_segment_ids"], [segment_id])
                self.assertFalse(task["result"]["has_more_batches"])
                self.assertEqual(task["result"]["remaining_repairable_count"], 0)
                self.assertEqual(
                    task["result"]["pending_media_actions"],
                    [
                        "regenerate_scene_master_frame",
                        "regenerate_scene_images",
                        "regenerate_video",
                    ],
                )

    def test_scene_stage_job_rejects_invalid_master_only_scope(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/scenes",
                json={
                    "project_id": "demo-project",
                    "source_task_id": "demo-task",
                    "segment_id": "seg-01",
                    "scene_id": "scene-01",
                    "master_only": True,
                },
            )
            self.assertEqual(response.status_code, 422)

    def test_continuity_repair_job_rejects_invalid_scope(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/continuity-repair",
                json={
                    "project_id": "demo-project",
                    "source_task_id": "demo-task",
                    "segment_id": "seg-01",
                    "scene_id": "scene-01",
                },
            )
            self.assertEqual(response.status_code, 422)

    def test_video_merge_job_rejects_scope_arguments(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/videos",
                json={
                    "project_id": "demo-project",
                    "source_task_id": "demo-task",
                    "scene_id": "scene-01",
                    "merge_only": True,
                },
            )
            self.assertEqual(response.status_code, 422)

    def test_submit_short_story_word_target_is_accepted(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "极短篇测试",
                        "idea": "暴雨夜里，一班末班车带来一位不该出现的乘客。",
                        "genre": "悬疑",
                        "tone": "克制、阴冷",
                        "target_audience": "成年读者",
                        "chapter_count": 1,
                        "total_word_target": 500,
                        "must_include": ["末班车"],
                        "style_keywords": ["夜雨", "空车厢"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(response.status_code, 202)

    def test_delete_project_removes_project_and_task_records(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "待删除故事",
                        "idea": "一个测试项目会被删除。",
                        "genre": "测试",
                        "tone": "清晰",
                        "target_audience": "开发者",
                        "chapter_count": 1,
                        "total_word_target": 500,
                        "must_include": ["删除"],
                        "style_keywords": ["测试"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            project_id = response.json()["project_id"]
            task_id = response.json()["task_id"]

            payload = self._wait_for_completion(client, task_id)
            self.assertEqual(payload["status"], "completed")
            output_dir = Path(str(payload["result"]["output_dir"]))
            self.assertTrue(output_dir.exists())

            delete_response = client.delete(f"/v1/projects/{project_id}")
            self.assertEqual(delete_response.status_code, 200)
            delete_payload = delete_response.json()
            self.assertEqual(delete_payload["project_id"], project_id)
            self.assertTrue(delete_payload["deleted"])
            self.assertEqual(delete_payload["deleted_task_count"], 1)
            self.assertEqual(delete_payload["deleted_output_count"], 1)
            self.assertIn(str(output_dir.resolve()), delete_payload["deleted_output_paths"])
            self.assertFalse(output_dir.exists())

            self.assertEqual(client.get(f"/v1/projects/{project_id}").status_code, 404)
            self.assertEqual(client.get(f"/v1/tasks/{task_id}").status_code, 404)
            projects_response = client.get("/v1/projects")
            self.assertEqual(projects_response.status_code, 200)
            self.assertEqual(projects_response.json(), [])

    def test_delete_missing_project_returns_404(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.delete("/v1/projects/not-found")
            self.assertEqual(response.status_code, 404)

    @patch("storyforge.application.task_handlers.run_story_generation_pipeline")
    def test_delete_running_project_returns_409(self, mock_run_story_generation_pipeline) -> None:
        def fake_run_story_generation_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"] / "slow-story"
            output_dir.mkdir(parents=True, exist_ok=True)
            story_source_path = output_dir / "story_source.json"
            story_source_path.write_text("{}", encoding="utf-8")
            time.sleep(0.3)
            return SimpleNamespace(
                output_dir=output_dir,
                story_source_path=story_source_path,
                story_source=SimpleNamespace(title="运行中故事"),
            )

        mock_run_story_generation_pipeline.side_effect = fake_run_story_generation_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "运行中故事",
                        "idea": "一个正在生成的项目不允许删除。",
                        "genre": "测试",
                        "tone": "清晰",
                        "target_audience": "开发者",
                        "chapter_count": 1,
                        "total_word_target": 500,
                        "must_include": ["运行中"],
                        "style_keywords": ["测试"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(response.status_code, 202)
            project_id = response.json()["project_id"]
            task_id = response.json()["task_id"]

            for _ in range(40):
                task_response = client.get(f"/v1/tasks/{task_id}")
                self.assertEqual(task_response.status_code, 200)
                if task_response.json()["status"] == "running":
                    break
                time.sleep(0.02)

            delete_response = client.delete(f"/v1/projects/{project_id}")
            self.assertEqual(delete_response.status_code, 409)
            self.assertIn("queued or running tasks", delete_response.json()["detail"])

            payload = self._wait_for_completion(client, task_id)
            self.assertEqual(payload["status"], "completed")

    @patch("storyforge.application.task_handlers.run_video_merge_pipeline")
    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    @patch("storyforge.application.task_handlers.run_character_image_pipeline")
    def test_submit_manual_staged_jobs_share_one_logical_run(
        self,
        mock_run_character_image_pipeline,
        mock_run_scene_image_pipeline,
        mock_run_video_render_pipeline,
        mock_run_video_merge_pipeline,
    ) -> None:
        def fake_run_character_image_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            assets_dir = output_dir / "assets"
            characters_dir = assets_dir / "characters"
            frames_dir = assets_dir / "frames"
            characters_dir.mkdir(parents=True, exist_ok=True)
            frames_dir.mkdir(parents=True, exist_ok=True)

            character_bible_path = output_dir / "character_visual_bible.json"
            character_images_path = output_dir / "character_image_manifest.json"
            scene_plan_path = output_dir / "scene_plan.json"
            segment_plan_path = output_dir / "segment_plan.json"
            scene_images_path = output_dir / "scene_image_manifest.json"
            manifest_path = output_dir / "seedance_manifest.json"
            seedream_execution_path = output_dir / "seedream_character_execution.json"

            for path in (
                character_bible_path,
                character_images_path,
                scene_plan_path,
                segment_plan_path,
                scene_images_path,
                manifest_path,
                seedream_execution_path,
            ):
                path.write_text("{}", encoding="utf-8")
            (characters_dir / "hero.png").write_bytes(b"fake image")

            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=character_bible_path,
                character_images_path=character_images_path,
                scene_plan_path=scene_plan_path,
                segment_plan_path=segment_plan_path,
                scene_images_path=scene_images_path,
                manifest_path=manifest_path,
                seedream_execution_path=seedream_execution_path,
                character_seedream_execution_path=seedream_execution_path,
                project_package=SimpleNamespace(title="阶段化测试故事"),
                manifest=SimpleNamespace(title="阶段化测试故事"),
                seedream_execution=SimpleNamespace(submitted=True, failed_count=0),
            )

        def fake_run_scene_image_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            assets_dir = output_dir / "assets"
            frames_dir = assets_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)

            character_bible_path = output_dir / "character_visual_bible.json"
            character_images_path = output_dir / "character_image_manifest.json"
            scene_plan_path = output_dir / "scene_plan.json"
            segment_plan_path = output_dir / "segment_plan.json"
            scene_images_path = output_dir / "scene_image_manifest.json"
            manifest_path = output_dir / "seedance_manifest.json"
            character_seedream_execution_path = output_dir / "seedream_character_execution.json"
            scene_seedream_execution_path = output_dir / "seedream_scene_execution.json"

            for path in (
                character_bible_path,
                character_images_path,
                scene_plan_path,
                segment_plan_path,
                scene_images_path,
                manifest_path,
                character_seedream_execution_path,
                scene_seedream_execution_path,
            ):
                path.write_text("{}", encoding="utf-8")
            (frames_dir / "segment-01_start.png").write_bytes(b"fake image")
            (frames_dir / "segment-01_end.png").write_bytes(b"fake image")

            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=character_bible_path,
                character_images_path=character_images_path,
                scene_plan_path=scene_plan_path,
                segment_plan_path=segment_plan_path,
                scene_images_path=scene_images_path,
                manifest_path=manifest_path,
                seedream_execution_path=scene_seedream_execution_path,
                character_seedream_execution_path=character_seedream_execution_path,
                scene_seedream_execution_path=scene_seedream_execution_path,
                project_package=SimpleNamespace(title="阶段化测试故事"),
                manifest=SimpleNamespace(title="阶段化测试故事"),
                seedream_execution=SimpleNamespace(submitted=True, failed_count=0),
            )

        def fake_run_video_render_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            rendered_dir = output_dir / "rendered"
            rendered_dir.mkdir(parents=True, exist_ok=True)

            manifest_path = output_dir / "seedance_manifest.json"
            seedance_execution_path = output_dir / "seedance_execution.json"
            clip_path = rendered_dir / "segment-01.mp4"

            manifest_path.write_text("{}", encoding="utf-8")
            seedance_execution_path.write_text("{}", encoding="utf-8")
            clip_path.write_bytes(b"fake mp4 bytes")

            return SimpleNamespace(
                output_dir=output_dir,
                manifest_path=manifest_path,
                seedance_execution_path=seedance_execution_path,
                rendered_clip_paths=[clip_path],
                full_story_path=None,
                manifest=SimpleNamespace(title="阶段化测试故事"),
                seedance_execution=SimpleNamespace(submitted=True, failed_count=0, pending_count=0),
            )

        def fake_run_video_merge_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            rendered_dir = output_dir / "rendered"
            rendered_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = output_dir / "seedance_manifest.json"
            full_story_path = rendered_dir / "full_story.mp4"

            manifest_path.write_text("{}", encoding="utf-8")
            full_story_path.write_bytes(b"merged mp4 bytes")

            clip_paths = sorted(rendered_dir.glob("*.mp4"))
            return SimpleNamespace(
                output_dir=output_dir,
                manifest_path=manifest_path,
                rendered_clip_paths=[path for path in clip_paths if path.name != "full_story.mp4"],
                full_story_path=full_story_path,
                manifest=SimpleNamespace(title="阶段化测试故事"),
                merged_clip_count=len([path for path in clip_paths if path.name != "full_story.mp4"]),
                skipped_clip_count=0,
            )

        mock_run_character_image_pipeline.side_effect = fake_run_character_image_pipeline
        mock_run_scene_image_pipeline.side_effect = fake_run_scene_image_pipeline
        mock_run_video_render_pipeline.side_effect = fake_run_video_render_pipeline
        mock_run_video_merge_pipeline.side_effect = fake_run_video_merge_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "阶段化测试故事",
                        "idea": "一个人先写完故事，再逐步生成图片和视频。",
                        "genre": "测试",
                        "tone": "清晰",
                        "target_audience": "开发者",
                        "chapter_count": 1,
                        "total_word_target": 800,
                        "must_include": ["阶段化"],
                        "style_keywords": ["测试"],
                    },
                    "use_llm": True,
                },
            )
            self.assertEqual(story_response.status_code, 202)
            project_id = story_response.json()["project_id"]
            story_task_id = story_response.json()["task_id"]

            story_payload = self._wait_for_completion(client, story_task_id)
            self.assertEqual(story_payload["status"], "completed")
            self.assertEqual(story_payload["result"]["task_stage"], "story")
            self.assertIn("story_source_path", story_payload["result"])

            story_source_response = client.get(
                f"/v1/projects/{project_id}/story-source/{story_task_id}",
            )
            self.assertEqual(story_source_response.status_code, 200)
            story_source_payload = story_source_response.json()
            self.assertTrue(story_source_payload["chapters"])

            scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(scene_structure_response.status_code, 202)
            scene_structure_task_id = scene_structure_response.json()["task_id"]

            scene_structure_payload = self._wait_for_completion(client, scene_structure_task_id)
            self.assertEqual(scene_structure_payload["status"], "completed")
            self.assertEqual(scene_structure_payload["result"]["task_stage"], "scene_structure")
            self.assertIn("novel_package_path", scene_structure_payload["result"])
            self.assertIn("novel_audit_path", scene_structure_payload["result"])
            self.assertIn("character_bible_path", scene_structure_payload["result"])
            self.assertIn("scene_plan_path", scene_structure_payload["result"])
            self.assertIsNone(scene_structure_payload["result"].get("segment_plan_path"))
            self.assertIsNone(scene_structure_payload["result"].get("scene_images_path"))
            self.assertIsNone(scene_structure_payload["result"].get("seedance_manifest_path"))

            duplicate_scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(duplicate_scene_structure_response.status_code, 202)
            self.assertEqual(
                duplicate_scene_structure_response.json()["task_id"],
                scene_structure_task_id,
            )
            self.assertEqual(duplicate_scene_structure_response.json()["status"], "completed")

            segment_contracts_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(segment_contracts_response.status_code, 202)
            segment_contracts_task_id = segment_contracts_response.json()["task_id"]

            segment_contracts_payload = self._wait_for_completion(client, segment_contracts_task_id)
            self.assertEqual(segment_contracts_payload["status"], "completed")
            self.assertEqual(segment_contracts_payload["result"]["task_stage"], "segment_contracts")
            self.assertIn("character_images_path", segment_contracts_payload["result"])
            self.assertIn("scene_plan_path", segment_contracts_payload["result"])
            self.assertIn("segment_plan_path", segment_contracts_payload["result"])
            self.assertIn("scene_images_path", segment_contracts_payload["result"])
            self.assertIn("seedance_manifest_path", segment_contracts_payload["result"])

            duplicate_segment_contracts_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(duplicate_segment_contracts_response.status_code, 202)
            self.assertEqual(
                duplicate_segment_contracts_response.json()["task_id"],
                segment_contracts_task_id,
            )
            self.assertEqual(duplicate_segment_contracts_response.json()["status"], "completed")

            character_response = client.post(
                "/v1/projects/characters",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(character_response.status_code, 202)
            character_task_id = character_response.json()["task_id"]

            character_payload = self._wait_for_completion(client, character_task_id)
            self.assertEqual(character_payload["status"], "completed")
            self.assertEqual(character_payload["result"]["task_stage"], "characters")

            propagated_story_after_characters = client.get(f"/v1/tasks/{story_task_id}").json()
            self.assertEqual(
                propagated_story_after_characters["result"]["pipeline_root_task_id"],
                story_task_id,
            )
            self.assertIn("seedance_manifest_path", propagated_story_after_characters["result"])
            self.assertIn("character_seedream_execution_path", propagated_story_after_characters["result"])

            scene_response = client.post(
                "/v1/projects/scenes",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(scene_response.status_code, 202)
            scene_task_id = scene_response.json()["task_id"]

            scene_payload = self._wait_for_completion(client, scene_task_id)
            self.assertEqual(scene_payload["status"], "completed")
            self.assertEqual(scene_payload["result"]["task_stage"], "scenes")

            video_response = client.post(
                "/v1/projects/videos",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(video_response.status_code, 202)
            video_task_id = video_response.json()["task_id"]

            video_payload = self._wait_for_completion(client, video_task_id)
            self.assertEqual(video_payload["status"], "completed")
            self.assertEqual(video_payload["result"]["task_stage"], "videos")
            self.assertTrue(video_payload["result"]["rendered_clips"])
            self.assertIsNone(video_payload["result"]["full_story_path"])

            propagated_story_after_videos = client.get(f"/v1/tasks/{story_task_id}").json()
            self.assertIn("seedance_execution_path", propagated_story_after_videos["result"])
            self.assertIsNone(propagated_story_after_videos["result"].get("full_story_path"))

            merge_response = client.post(
                "/v1/projects/videos",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                    "merge_only": True,
                },
            )
            self.assertEqual(merge_response.status_code, 202)
            merge_task_id = merge_response.json()["task_id"]

            merge_payload = self._wait_for_completion(client, merge_task_id)
            self.assertEqual(merge_payload["status"], "completed")
            self.assertEqual(merge_payload["result"]["task_stage"], "video_merge")
            self.assertTrue(merge_payload["result"]["merge_only"])
            self.assertIsNotNone(merge_payload["result"]["full_story_path"])

            root_artifacts = client.get(f"/v1/tasks/{story_task_id}/artifacts")
            self.assertEqual(root_artifacts.status_code, 200)
            root_artifact_payload = root_artifacts.json()
            self.assertEqual(len(root_artifact_payload["character_images"]), 1)
            self.assertEqual(len(root_artifact_payload["scene_frames"]), 2)
            self.assertEqual(len(root_artifact_payload["rendered_clips"]), 1)
            self.assertIsNotNone(root_artifact_payload["full_story"])

            projects_response = client.get("/v1/projects")
            self.assertEqual(projects_response.status_code, 200)
            projects = projects_response.json()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["run_count"], 1)
            self.assertEqual(projects[0]["completed_run_count"], 1)
            self.assertEqual(projects[0]["full_story_count"], 1)

            detail_response = client.get(f"/v1/projects/{project_id}")
            self.assertEqual(detail_response.status_code, 200)
            detail = detail_response.json()
            self.assertEqual(len(detail["tasks"]), 7)
            self.assertEqual(
                {task["task_type"] for task in detail["tasks"]},
                {
                    "project.story",
                    "project.scene_structure",
                    "project.segment_contracts",
                    "project.characters",
                    "project.scenes",
                    "project.videos",
                },
            )
            self.assertEqual(
                {task["result"]["pipeline_root_task_id"] for task in detail["tasks"] if task["result"]},
                {story_task_id},
            )

    def test_segment_contracts_failure_returns_progress_and_resume_job_succeeds(self) -> None:
        config_path = self._create_test_config()

        with TestClient(create_app(config_path=config_path)) as client:
            story_response = client.post(
                "/v1/projects/novel",
                json={
                    "brief": {
                        "title_hint": "断点续跑接口测试",
                        "idea": "一个调查员分三章逐步逼近真相。",
                        "genre": "悬疑",
                        "tone": "清晰克制",
                        "chapter_count": 3,
                        "total_word_target": 1800,
                        "must_include": ["调查推进"],
                        "style_keywords": ["连续推进"],
                    }
                },
            )
            self.assertEqual(story_response.status_code, 202)
            story_task_id = story_response.json()["task_id"]
            story_payload = self._wait_for_completion(client, story_task_id)
            self.assertEqual(story_payload["status"], "completed")
            project_id = story_payload["project_id"]

            scene_structure_response = client.post(
                "/v1/projects/scene-structure",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                },
            )
            self.assertEqual(scene_structure_response.status_code, 202)
            scene_structure_task_id = scene_structure_response.json()["task_id"]
            scene_structure_payload = self._wait_for_completion(client, scene_structure_task_id)
            self.assertEqual(
                scene_structure_payload["status"],
                "completed",
            )
            output_dir = Path(scene_structure_payload["result"]["output_dir"])
            scene_plan_path = output_dir / "scene_plan.json"
            scene_plan_payload = json.loads(scene_plan_path.read_text(encoding="utf-8"))
            scene_entries = list(scene_plan_payload.get("scenes", []))
            scene_two_inserted = False
            for index, scene in enumerate(list(scene_entries)):
                if int(scene.get("chapter_number", 0) or 0) != 2:
                    continue
                duplicate_scene = dict(scene)
                duplicate_scene["scene_id"] = "ch02-sc02"
                duplicate_scene["title"] = f'{scene.get("title", "场景")} / 后续'
                duplicate_scene["summary"] = f'{scene.get("summary", "场景推进")} 后续推进。'
                duplicate_scene["segments"] = []
                scene_entries.insert(index + 1, duplicate_scene)
                scene_two_inserted = True
                break
            self.assertTrue(scene_two_inserted)
            scene_plan_path.write_text(
                json.dumps({"scenes": scene_entries}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            chapter_two_scene_ids = [
                item["scene_id"]
                for item in scene_entries
                if int(item.get("chapter_number", 0) or 0) == 2
            ]
            failed_scene_id = chapter_two_scene_ids[1]
            original_chunk_builder = NovelToVideoService._build_scene_chunk_contract_batch
            failed_chunk_id = f"{failed_scene_id}-chunk01"

            def fail_on_second_scene_of_second_chapter(
                service,
                *,
                novel_package,
                story_memory,
                chapter_number,
                scene,
                chunk,
                previous_chunk_exit_state,
                previous_tail_segment,
            ):
                if chapter_number == 2 and scene.scene_id == failed_scene_id:
                    raise VideoStructuredGenerationError(
                        task="video-scene-segment-planner",
                        schema_name="SceneSegmentContractBatchSchema",
                        attempts=3,
                        cause=RuntimeError("scene failed"),
                        metadata={
                            "chapter_number": 2,
                            "scene_id": failed_scene_id,
                            "chunk_id": failed_chunk_id,
                        },
                    )
                return original_chunk_builder(
                    service,
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter_number,
                    scene=scene,
                    chunk=chunk,
                    previous_chunk_exit_state=previous_chunk_exit_state,
                    previous_tail_segment=previous_tail_segment,
                )

            with patch.object(
                NovelToVideoService,
                "_build_scene_chunk_contract_batch",
                autospec=True,
                side_effect=fail_on_second_scene_of_second_chapter,
            ):
                segment_contracts_response = client.post(
                    "/v1/projects/segment-contracts",
                    json={
                        "project_id": project_id,
                        "source_task_id": story_task_id,
                    },
                )
                self.assertEqual(segment_contracts_response.status_code, 202)
                failed_task_id = segment_contracts_response.json()["task_id"]
                failed_payload = self._wait_for_completion(client, failed_task_id)

            self.assertEqual(failed_payload["status"], "failed")
            self.assertIn("chapter=2", failed_payload["error"])
            self.assertIn(f"scene_id={failed_scene_id}", failed_payload["error"])
            self.assertEqual(
                failed_payload["result"]["pipeline_stage"],
                "segment_contracts_failed",
            )
            progress = failed_payload["result"]["segment_contract_progress"]
            self.assertIsNotNone(progress)
            self.assertEqual(progress["status"], "failed")
            self.assertEqual(progress["completed_chapters"], 1)
            self.assertEqual(progress["failed_chapter_number"], 2)
            self.assertEqual(progress["failed_scene_id"], failed_scene_id)
            self.assertEqual(progress["failed_chunk_id"], failed_chunk_id)
            self.assertTrue(progress["resume_ready"])
            self.assertTrue(Path(failed_payload["result"]["segment_contract_progress_path"]).exists())

            resume_response = client.post(
                "/v1/projects/segment-contracts",
                json={
                    "project_id": project_id,
                    "source_task_id": story_task_id,
                    "resume_from_progress": True,
                },
            )
            self.assertEqual(resume_response.status_code, 202)
            resume_task_id = resume_response.json()["task_id"]
            resume_task = client.app.state.container.task_queue.store.get(resume_task_id)
            self.assertIsNotNone(resume_task)
            self.assertTrue(resume_task.payload["resume_from_progress"])

            resumed_payload = self._wait_for_completion(client, resume_task_id)
            self.assertEqual(resumed_payload["status"], "completed")
            resumed_progress = resumed_payload["result"]["segment_contract_progress"]
            self.assertEqual(resumed_progress["status"], "completed")
            self.assertEqual(
                resumed_progress["completed_chapters"],
                resumed_progress["total_chapters"],
            )
            self.assertFalse(resumed_progress["resume_ready"])


if __name__ == "__main__":
    unittest.main()
