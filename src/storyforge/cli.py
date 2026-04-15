from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import json
import os

from storyforge.agents.orchestrator import StoryForgeOrchestrator
from storyforge.core.config import AppConfig
from storyforge.core.env import load_env_file
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief
from storyforge.pipelines.video_pipeline import VideoPipelineResult


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="storyforge", description="StoryForge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create default working directories")
    init_parser.add_argument("--config", default="configs/storyforge.example.toml")

    pipeline_parser = subparsers.add_parser("pipeline", help="Run end-to-end pipelines")
    pipeline_subparsers = pipeline_parser.add_subparsers(dest="pipeline_command", required=True)

    demo_parser = pipeline_subparsers.add_parser("demo", help="Run demo brief end-to-end")
    demo_parser.add_argument("--config", default="configs/storyforge.example.toml")
    demo_parser.add_argument("--llm", action="store_true")
    demo_parser.add_argument("--submit-seedance", action="store_true")

    build_parser_cmd = pipeline_subparsers.add_parser("build", help="Build novel and video plan")
    build_parser_cmd.add_argument("--brief", required=True)
    build_parser_cmd.add_argument("--config", default="configs/storyforge.example.toml")
    build_parser_cmd.add_argument("--llm", action="store_true")
    build_parser_cmd.add_argument("--submit-seedance", action="store_true")

    video_parser = subparsers.add_parser("video", help="Generate video plan from saved novel package")
    video_subparsers = video_parser.add_subparsers(dest="video_command", required=True)

    video_plan_parser = video_subparsers.add_parser("plan", help="Create storyboard and manifest")
    video_plan_parser.add_argument("--novel-package", required=True)
    video_plan_parser.add_argument("--config", default="configs/storyforge.example.toml")
    video_plan_parser.add_argument("--llm", action="store_true")
    video_plan_parser.add_argument("--submit-seedance", action="store_true")

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
    orchestrator = StoryForgeOrchestrator(project_root, config)

    if args.command == "init":
        print(f"project directories initialized under: {project_root}")
        return 0

    if args.command == "pipeline" and args.pipeline_command == "demo":
        brief = StoryBrief.from_file(project_root / "examples/briefs/demo_story.toml")
        result = orchestrator.build_from_brief(
            brief,
            use_llm=args.llm,
            submit_seedance=args.submit_seedance,
        )
        _print_pipeline_result(result.story.output_dir, result.story.novel_package_path, result.video)
        return 0

    if args.command == "pipeline" and args.pipeline_command == "build":
        brief = StoryBrief.from_file(Path(args.brief))
        result = orchestrator.build_from_brief(
            brief,
            use_llm=args.llm,
            submit_seedance=args.submit_seedance,
        )
        _print_pipeline_result(result.story.output_dir, result.story.novel_package_path, result.video)
        return 0

    if args.command == "video" and args.video_command == "plan":
        novel_package_path = Path(args.novel_package)
        raw = json.loads(novel_package_path.read_text(encoding="utf-8"))
        novel_package = NovelPackage.from_dict(raw)
        result = orchestrator.build_video_from_package(
            novel_package,
            output_root=novel_package_path.parent,
            use_llm=args.llm,
            submit_seedance=args.submit_seedance,
        )
        print(f"video plan generated: {result.output_dir}")
        print(f"- segment plan: {result.segment_plan_path}")
        print(f"- seedance manifest: {result.manifest_path}")
        print(f"- seedance execution: {result.seedance_execution_path}")
        return 0

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


def _print_pipeline_result(
    output_dir: Path,
    novel_package_path: Path,
    video_result: VideoPipelineResult,
) -> None:
    print(f"pipeline generated under: {output_dir}")
    print(f"- novel package: {novel_package_path}")
    print(f"- video manifest: {video_result.manifest_path}")
    print(f"- seedance execution: {video_result.seedance_execution_path}")
    if video_result.full_story_path is not None:
        print(f"- full story video: {video_result.full_story_path}")


def resolve_project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists():
        return cwd
    return Path(__file__).resolve().parents[2]
