from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from storyforge.api.routers.health import router as health_router
from storyforge.api.routers.projects import router as projects_router
from storyforge.api.routers.tasks import router as tasks_router
from storyforge.api.routers.ui import router as ui_router
from storyforge.application.container import AppContainer, build_container
from storyforge.core.config import AppConfig
from storyforge.core.env import load_env_file


CONFIG_PATH_ENV = "STORYFORGE_CONFIG_PATH"


def resolve_project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd
    return Path(__file__).resolve().parents[3]


def create_app(project_root: Path | None = None, config_path: Path | None = None) -> FastAPI:
    root = project_root or resolve_project_root()
    load_env_file(root / ".env", override=True)
    resolved_config_path = config_path or _resolve_config_path_from_env(root)
    config = AppConfig.load(resolved_config_path)
    config.ensure_directories(root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container: AppContainer = build_container(project_root=root, config=config)
        await container.task_queue.start()
        app.state.container = container
        yield
        await container.task_queue.stop()

    app = FastAPI(
        title="StoryForge API",
        version="0.1.0",
        description=(
            "Async novel-to-video task API backed by FastAPI, persisted projects, "
            "and JSON/MySQL-backed metadata storage."
        ),
        lifespan=lifespan,
    )
    static_dir = root / "src" / "storyforge" / "api" / "static"
    output_dir = root / config.paths.output_dir
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/outputs", StaticFiles(directory=output_dir), name="outputs")
    app.include_router(ui_router)
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    return app


def _resolve_config_path_from_env(project_root: Path) -> Path:
    raw_path = os.getenv(CONFIG_PATH_ENV)
    if not raw_path:
        return project_root / "configs/storyforge.example.toml"
    path = Path(raw_path)
    return path if path.is_absolute() else project_root / path


app = create_app()
