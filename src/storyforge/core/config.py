from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib


@dataclass(slots=True)
class LLMConfig:
    enabled: bool = False
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: float = 0.7
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com/v1"
    timeout_seconds: int = 120


@dataclass(slots=True)
class NovelConfig:
    default_chapter_count: int = 8
    default_chapter_word_target: int = 2500
    chapter_scene_count: int = 3
    major_character_count: int = 3
    review_passes: int = 1


@dataclass(slots=True)
class VideoConfig:
    segment_duration_seconds: int = 5
    aspect_ratio: str = "16:9"
    fps: int = 24
    character_image_provider: str = "seedream-4.5"
    scene_image_provider: str = "seedream-4.5"
    submit_seedance: bool = False


@dataclass(slots=True)
class SeedreamConfig:
    enabled: bool = True
    base_url: str = ""
    api_key_env: str = "SEEDREAM_API_KEY"
    model: str = "doubao-seedream-4-5-251128"
    auto_submit: bool = False
    image_size: str = "2K"
    response_format: str = "url"
    download_outputs: bool = True


@dataclass(slots=True)
class SeedanceConfig:
    enabled: bool = True
    base_url: str = ""
    api_key_env: str = "SEEDANCE_API_KEY"
    model: str = "doubao-seedance-2-0-260128"
    auto_submit: bool = False
    with_audio: bool = True
    subtitle_mode: str = "burned_in"
    subtitle_style: str = "底部居中中文硬字幕，白字黑边，电影感，无额外花字"
    watermark: bool = False
    download_outputs: bool = True
    poll_interval_seconds: float = 5.0
    max_wait_seconds: int = 900


@dataclass(slots=True)
class DatabaseConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    password_env: str = "STORYFORGE_DB_PASSWORD"
    database: str = "storyforge"
    charset: str = "utf8mb4"
    connect_timeout_seconds: int = 5
    auto_create_schema: bool = True

    def resolved_password(self) -> str:
        if self.password:
            return self.password
        if self.password_env:
            return os.getenv(self.password_env, "")
        return ""


@dataclass(slots=True)
class QueueConfig:
    concurrency: int = 2
    poll_interval_seconds: float = 0.2


@dataclass(slots=True)
class PathConfig:
    output_dir: str = "outputs"
    workspace_dir: str = "workspace"
    prompt_dir: str = "prompts"


@dataclass(slots=True)
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    novel: NovelConfig = field(default_factory=NovelConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    seedream: SeedreamConfig = field(default_factory=SeedreamConfig)
    seedance: SeedanceConfig = field(default_factory=SeedanceConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        if path is None or not path.exists():
            return cls()

        with path.open("rb") as handle:
            raw = tomllib.load(handle)

        llm = raw.get("llm", {})
        novel = raw.get("novel", {})
        video = raw.get("video", {})
        seedream = raw.get("seedream", {})
        seedance = raw.get("seedance", {})
        database = raw.get("database", {})
        queue = raw.get("queue", {})
        paths = raw.get("paths", {})

        return cls(
            llm=LLMConfig(
                enabled=llm.get("enabled", False),
                provider=llm.get("provider", "deepseek"),
                model=llm.get("model", "deepseek-chat"),
                temperature=llm.get("temperature", 0.7),
                api_key_env=llm.get("api_key_env", "DEEPSEEK_API_KEY"),
                base_url=llm.get("base_url", "https://api.deepseek.com/v1"),
                timeout_seconds=llm.get("timeout_seconds", 120),
            ),
            novel=NovelConfig(
                default_chapter_count=novel.get("default_chapter_count", 8),
                default_chapter_word_target=novel.get("default_chapter_word_target", 2500),
                chapter_scene_count=novel.get("chapter_scene_count", 3),
                major_character_count=novel.get("major_character_count", 3),
                review_passes=novel.get("review_passes", 1),
            ),
            video=VideoConfig(
                segment_duration_seconds=video.get("segment_duration_seconds", 5),
                aspect_ratio=video.get("aspect_ratio", "16:9"),
                fps=video.get("fps", 24),
                character_image_provider=video.get("character_image_provider", "seedream-4.5"),
                scene_image_provider=video.get("scene_image_provider", "seedream-4.5"),
                submit_seedance=video.get("submit_seedance", False),
            ),
            seedream=SeedreamConfig(
                enabled=seedream.get("enabled", True),
                base_url=seedream.get("base_url", ""),
                api_key_env=seedream.get("api_key_env", "SEEDREAM_API_KEY"),
                model=seedream.get("model", "doubao-seedream-4-5-251128"),
                auto_submit=seedream.get("auto_submit", False),
                image_size=seedream.get("image_size", "2K"),
                response_format=seedream.get("response_format", "url"),
                download_outputs=seedream.get("download_outputs", True),
            ),
            seedance=SeedanceConfig(
                enabled=seedance.get("enabled", True),
                base_url=seedance.get("base_url", ""),
                api_key_env=seedance.get("api_key_env", "SEEDANCE_API_KEY"),
                model=seedance.get("model", "doubao-seedance-2-0-260128"),
                auto_submit=seedance.get("auto_submit", False),
                with_audio=seedance.get("with_audio", True),
                subtitle_mode=seedance.get("subtitle_mode", "burned_in"),
                subtitle_style=seedance.get(
                    "subtitle_style",
                    "底部居中中文硬字幕，白字黑边，电影感，无额外花字",
                ),
                watermark=seedance.get("watermark", False),
                download_outputs=seedance.get("download_outputs", True),
                poll_interval_seconds=seedance.get("poll_interval_seconds", 5.0),
                max_wait_seconds=seedance.get("max_wait_seconds", 900),
            ),
            database=DatabaseConfig(
                enabled=database.get("enabled", False),
                host=database.get("host", "127.0.0.1"),
                port=database.get("port", 3306),
                user=database.get("user", "root"),
                password=database.get("password", ""),
                password_env=database.get("password_env", "STORYFORGE_DB_PASSWORD"),
                database=database.get("database", "storyforge"),
                charset=database.get("charset", "utf8mb4"),
                connect_timeout_seconds=database.get("connect_timeout_seconds", 5),
                auto_create_schema=database.get("auto_create_schema", True),
            ),
            queue=QueueConfig(
                concurrency=queue.get("concurrency", 2),
                poll_interval_seconds=queue.get("poll_interval_seconds", 0.2),
            ),
            paths=PathConfig(
                output_dir=paths.get("output_dir", "outputs"),
                workspace_dir=paths.get("workspace_dir", "workspace"),
                prompt_dir=paths.get("prompt_dir", "prompts"),
            ),
        )

    def ensure_directories(self, project_root: Path) -> None:
        for folder in (
            self.paths.output_dir,
            self.paths.workspace_dir,
            self.paths.prompt_dir,
        ):
            (project_root / folder).mkdir(parents=True, exist_ok=True)
