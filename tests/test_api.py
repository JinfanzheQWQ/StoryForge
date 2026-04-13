from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient  # noqa: E402

from storyforge.api.main import create_app  # noqa: E402
from storyforge.agents.base import DryRunAgentBackend  # noqa: E402


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._story_backend_patcher = patch(
            "storyforge.pipelines.story_pipeline.build_agent_backend",
            return_value=DryRunAgentBackend(),
        )
        self._video_backend_patcher = patch(
            "storyforge.pipelines.video_planning.build_agent_backend",
            return_value=DryRunAgentBackend(),
        )
        self._story_backend_patcher.start()
        self._video_backend_patcher.start()
        self.addCleanup(self._story_backend_patcher.stop)
        self.addCleanup(self._video_backend_patcher.stop)

    def _create_test_config(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        output_dir = root / "outputs"
        workspace_dir = root / "workspace"
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
                api_key_env = "DEEPSEEK_API_KEY"
                base_url = "https://api.deepseek.com/v1"
                timeout_seconds = 120

                [novel]
                default_chapter_count = 8
                default_chapter_word_target = 2500
                chapter_scene_count = 3
                major_character_count = 3
                review_passes = 1

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
                enabled = false
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
                workspace_dir = "{workspace_dir}"
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

            static_main_js = client.get("/static/app/main.js")
            self.assertEqual(static_main_js.status_code, 200)
            self.assertIn("refreshTasks", static_main_js.text)

            bootstrap = client.get("/v1/ui/bootstrap")
            self.assertEqual(bootstrap.status_code, 200)
            payload = bootstrap.json()
            self.assertIn("default_brief", payload)
            self.assertIn("llm_model", payload)
            self.assertIn("seedream_model", payload)
            self.assertIn("seedance_model", payload)

    def test_submit_complete_job_and_persist_project_history(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel-to-video",
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
                    "submit_seedance": False,
                },
            )
            self.assertEqual(response.status_code, 202)
            project_id = response.json()["project_id"]
            task_id = response.json()["task_id"]
            payload = self._wait_for_completion(client, task_id)

            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["project_id"], project_id)
            self.assertIn("seedance_manifest_path", payload["result"])
            self.assertIn("seedance_execution_path", payload["result"])
            self.assertIn("rendered_clips", payload["result"])

            artifacts_response = client.get(f"/v1/tasks/{task_id}/artifacts")
            self.assertEqual(artifacts_response.status_code, 200)
            artifacts = artifacts_response.json()
            self.assertTrue(artifacts["available"])
            self.assertTrue(artifacts["documents"])
            self.assertTrue(artifacts["chapters"])

            chapter_url = artifacts["chapters"][0]["url"]
            chapter_response = client.get(chapter_url)
            self.assertEqual(chapter_response.status_code, 200)
            self.assertTrue(chapter_response.text.strip())

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
            self.assertEqual(project_detail["tasks"][0]["task_id"], task_id)
            self.assertEqual(project_detail["tasks"][0]["project_id"], project_id)

        reopened_app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(reopened_app) as reopened_client:
            persisted_project = reopened_client.get(f"/v1/projects/{project_id}")
            self.assertEqual(persisted_project.status_code, 200)
            persisted_payload = persisted_project.json()
            self.assertEqual(persisted_payload["project_id"], project_id)
            self.assertEqual(persisted_payload["tasks"][0]["task_id"], task_id)

            persisted_task = reopened_client.get(f"/v1/tasks/{task_id}")
            self.assertEqual(persisted_task.status_code, 200)
            self.assertEqual(persisted_task.json()["project_id"], project_id)

    @patch("storyforge.application.task_handlers.run_video_pipeline")
    def test_story_artifacts_are_available_while_task_is_still_running(self, mock_run_video_pipeline) -> None:
        def fake_run_video_pipeline(*args, **kwargs):
            output_dir = kwargs["output_root"]
            segment_plan_path = output_dir / "segment_plan.json"
            seedream_execution_path = output_dir / "seedream_execution.json"
            manifest_path = output_dir / "seedance_manifest.json"
            seedance_execution_path = output_dir / "seedance_execution.json"
            time.sleep(0.3)
            segment_plan_path.write_text("{}", encoding="utf-8")
            seedream_execution_path.write_text("{}", encoding="utf-8")
            manifest_path.write_text("{}", encoding="utf-8")
            seedance_execution_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                seedream_execution_path=seedream_execution_path,
                manifest_path=manifest_path,
                seedance_execution_path=seedance_execution_path,
                segment_plan_path=segment_plan_path,
                rendered_clip_paths=[],
                full_story_path=None,
                seedance_execution=SimpleNamespace(submitted=False),
                seedream_execution=None,
            )

        mock_run_video_pipeline.side_effect = fake_run_video_pipeline

        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel-to-video",
                json={
                    "brief": {
                        "title_hint": "实时展示测试",
                        "idea": "一名调查员在夜雨中追查失踪列车。",
                        "genre": "悬疑",
                        "tone": "压迫、电影感",
                        "target_audience": "成年读者",
                        "chapter_count": 2,
                        "total_word_target": 3000,
                        "must_include": ["失踪列车"],
                        "style_keywords": ["暴雨", "站台"],
                    },
                    "use_llm": True,
                    "submit_seedance": False,
                },
            )
            self.assertEqual(response.status_code, 202)
            task_id = response.json()["task_id"]

            running_payload: dict[str, object] | None = None
            for _ in range(40):
                task_response = client.get(f"/v1/tasks/{task_id}")
                self.assertEqual(task_response.status_code, 200)
                payload = task_response.json()
                if (
                    payload["status"] == "running"
                    and isinstance(payload.get("result"), dict)
                    and payload["result"].get("pipeline_stage") == "story_completed"
                ):
                    running_payload = payload
                    break
                time.sleep(0.02)

            self.assertIsNotNone(running_payload)
            artifacts_response = client.get(f"/v1/tasks/{task_id}/artifacts")
            self.assertEqual(artifacts_response.status_code, 200)
            artifacts = artifacts_response.json()
            self.assertTrue(artifacts["available"])
            self.assertTrue(artifacts["documents"])
            self.assertTrue(artifacts["chapters"])

            final_payload = self._wait_for_completion(client, task_id)
            self.assertEqual(final_payload["status"], "completed")

    def test_submit_short_story_word_target_is_accepted(self) -> None:
        config_path = self._create_test_config()
        app = create_app(project_root=ROOT, config_path=config_path)
        with TestClient(app) as client:
            response = client.post(
                "/v1/projects/novel-to-video",
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
                    "submit_seedance": False,
                },
            )
            self.assertEqual(response.status_code, 202)

    @patch("storyforge.application.task_handlers.run_video_render_pipeline")
    @patch("storyforge.application.task_handlers.run_scene_image_pipeline")
    @patch("storyforge.application.task_handlers.run_character_image_pipeline")
    def test_submit_manual_staged_jobs_share_one_logical_run(
        self,
        mock_run_character_image_pipeline,
        mock_run_scene_image_pipeline,
        mock_run_video_render_pipeline,
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
            segment_plan_path = output_dir / "segment_plan.json"
            scene_images_path = output_dir / "scene_image_manifest.json"
            manifest_path = output_dir / "seedance_manifest.json"
            seedream_execution_path = output_dir / "seedream_execution.json"
            concat_script_path = output_dir / "ffmpeg_concat.sh"
            concat_list_path = output_dir / "concat_list.txt"
            workflow_trace_path = output_dir / "video_workflow_trace.json"

            for path in (
                character_bible_path,
                character_images_path,
                segment_plan_path,
                scene_images_path,
                manifest_path,
                seedream_execution_path,
                workflow_trace_path,
            ):
                path.write_text("{}", encoding="utf-8")
            concat_script_path.write_text("#!/bin/sh\n", encoding="utf-8")
            concat_list_path.write_text("", encoding="utf-8")
            (characters_dir / "hero.png").write_bytes(b"fake image")

            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=character_bible_path,
                character_images_path=character_images_path,
                segment_plan_path=segment_plan_path,
                scene_images_path=scene_images_path,
                manifest_path=manifest_path,
                seedream_execution_path=seedream_execution_path,
                character_seedream_execution_path=seedream_execution_path,
                concat_script_path=concat_script_path,
                concat_list_path=concat_list_path,
                workflow_trace_path=workflow_trace_path,
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
            segment_plan_path = output_dir / "segment_plan.json"
            scene_images_path = output_dir / "scene_image_manifest.json"
            manifest_path = output_dir / "seedance_manifest.json"
            aggregate_seedream_execution_path = output_dir / "seedream_execution.json"
            character_seedream_execution_path = output_dir / "seedream_character_execution.json"
            scene_seedream_execution_path = output_dir / "seedream_scene_execution.json"
            concat_script_path = output_dir / "ffmpeg_concat.sh"
            concat_list_path = output_dir / "concat_list.txt"
            workflow_trace_path = output_dir / "video_workflow_trace.json"

            for path in (
                character_bible_path,
                character_images_path,
                segment_plan_path,
                scene_images_path,
                manifest_path,
                aggregate_seedream_execution_path,
                character_seedream_execution_path,
                scene_seedream_execution_path,
                workflow_trace_path,
            ):
                path.write_text("{}", encoding="utf-8")
            concat_script_path.write_text("#!/bin/sh\n", encoding="utf-8")
            concat_list_path.write_text("", encoding="utf-8")
            (frames_dir / "segment-01_start.png").write_bytes(b"fake image")
            (frames_dir / "segment-01_end.png").write_bytes(b"fake image")

            return SimpleNamespace(
                output_dir=output_dir,
                character_bible_path=character_bible_path,
                character_images_path=character_images_path,
                segment_plan_path=segment_plan_path,
                scene_images_path=scene_images_path,
                manifest_path=manifest_path,
                seedream_execution_path=aggregate_seedream_execution_path,
                character_seedream_execution_path=character_seedream_execution_path,
                scene_seedream_execution_path=scene_seedream_execution_path,
                concat_script_path=concat_script_path,
                concat_list_path=concat_list_path,
                workflow_trace_path=workflow_trace_path,
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
            concat_script_path = output_dir / "ffmpeg_concat.sh"
            concat_list_path = output_dir / "concat_list.txt"
            clip_path = rendered_dir / "segment-01.mp4"
            full_story_path = rendered_dir / "full_story.mp4"

            manifest_path.write_text("{}", encoding="utf-8")
            seedance_execution_path.write_text("{}", encoding="utf-8")
            concat_script_path.write_text("#!/bin/sh\n", encoding="utf-8")
            concat_list_path.write_text("file 'segment-01.mp4'\n", encoding="utf-8")
            clip_path.write_bytes(b"fake mp4 bytes")
            full_story_path.write_bytes(b"merged mp4 bytes")

            return SimpleNamespace(
                output_dir=output_dir,
                manifest_path=manifest_path,
                seedance_execution_path=seedance_execution_path,
                concat_script_path=concat_script_path,
                concat_list_path=concat_list_path,
                rendered_clip_paths=[clip_path],
                full_story_path=full_story_path,
                manifest=SimpleNamespace(title="阶段化测试故事"),
                seedance_execution=SimpleNamespace(submitted=True, failed_count=0, pending_count=0),
            )

        mock_run_character_image_pipeline.side_effect = fake_run_character_image_pipeline
        mock_run_scene_image_pipeline.side_effect = fake_run_scene_image_pipeline
        mock_run_video_render_pipeline.side_effect = fake_run_video_render_pipeline

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
            self.assertIsNotNone(video_payload["result"]["full_story_path"])

            propagated_story_after_videos = client.get(f"/v1/tasks/{story_task_id}").json()
            self.assertIn("seedance_execution_path", propagated_story_after_videos["result"])
            self.assertIn("full_story_path", propagated_story_after_videos["result"])

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
            self.assertEqual(len(detail["tasks"]), 4)
            self.assertEqual(
                {task["result"]["pipeline_root_task_id"] for task in detail["tasks"] if task["result"]},
                {story_task_id},
            )


if __name__ == "__main__":
    unittest.main()
