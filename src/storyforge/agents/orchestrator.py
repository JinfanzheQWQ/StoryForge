from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storyforge.core.config import AppConfig
from storyforge.domains.novel.contracts import NovelPackage, StoryBrief
from storyforge.pipelines.story_pipeline import StoryPipelineResult, run_story_pipeline
from storyforge.pipelines.video_pipeline import VideoPipelineResult, run_video_pipeline


@dataclass(slots=True)
class EndToEndResult:
    story: StoryPipelineResult
    video: VideoPipelineResult


class StoryForgeOrchestrator:
    def __init__(self, project_root: Path, config: AppConfig) -> None:
        self.project_root = project_root
        self.config = config

    def build_from_brief(
        self,
        brief: StoryBrief,
        use_llm: bool = False,
        output_root: Path | None = None,
        submit_seedance: bool = False,
    ) -> EndToEndResult:
        story_result = run_story_pipeline(
            brief=brief,
            config=self.config,
            project_root=self.project_root,
            use_llm=use_llm,
            output_root=output_root,
        )
        video_result = run_video_pipeline(
            novel_package=story_result.novel_package,
            config=self.config,
            project_root=self.project_root,
            output_root=story_result.output_dir,
            use_llm=use_llm,
            submit_seedance=submit_seedance,
        )
        return EndToEndResult(story=story_result, video=video_result)

    def build_video_from_package(
        self,
        novel_package: NovelPackage,
        output_root: Path | None = None,
        use_llm: bool = False,
        submit_seedance: bool = False,
    ) -> VideoPipelineResult:
        return run_video_pipeline(
            novel_package=novel_package,
            config=self.config,
            project_root=self.project_root,
            output_root=output_root,
            use_llm=use_llm,
            submit_seedance=submit_seedance,
        )
