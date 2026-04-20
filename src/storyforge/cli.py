from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import os

from storyforge.core.config import AppConfig
from storyforge.core.env import load_env_file


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="storyforge", description="StoryForge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api_parser = subparsers.add_parser("api", help="Run FastAPI server")
    api_subparsers = api_parser.add_subparsers(dest="api_command", required=True)

    api_serve_parser = api_subparsers.add_parser("serve", help="Serve StoryForge API with uvicorn")
    api_serve_parser.add_argument("--config", default="configs/storyforge.example.toml")
    api_serve_parser.add_argument("--host", default="127.0.0.1")
    api_serve_parser.add_argument("--port", type=int, default=8000)
    api_serve_parser.add_argument("--reload", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch(args)


def dispatch(args: Namespace) -> int:
    project_root = resolve_project_root()
    load_env_file(project_root / ".env", override=True)
    config = AppConfig.load(project_root / getattr(args, "config", "configs/storyforge.example.toml"))
    config.ensure_directories(project_root)

    if args.command == "api" and args.api_command == "serve":
        import uvicorn

        os.environ["STORYFORGE_CONFIG_PATH"] = str(
            (project_root / args.config).resolve()
        )
        uvicorn.run(
            "storyforge.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    raise ValueError(f"Unsupported arguments: {args}")


def resolve_project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd
    return Path(__file__).resolve().parents[2]
