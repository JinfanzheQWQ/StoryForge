from __future__ import annotations

from pathlib import Path
import shutil

from storyforge.agents.base import AgentBackend, PromptRequest
from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, to_jsonable, write_json
from storyforge.domains.novel.contracts import NovelPackage, StorySourcePackage
from storyforge.domains.video.contracts import (
    CharacterImageTask,
    CharacterVisualProfile,
    SceneImageTask,
    SeedanceClipTask,
    SeedanceManifest,
    StoryMemoryPackage,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.schemas import (
    ChapterSceneSchema,
    ChapterSceneStructureSchema,
    CharacterVisualBibleSchema,
    VideoSegmentPlanSchema,
)
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.continuity import write_continuity_report
from storyforge.pipelines.video_models import (
    VideoPlanningArtifacts,
    VideoPlanningPaths,
    VideoSceneStructureArtifacts,
)


def build_video_scene_structure_artifacts(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    backend: AgentBackend | None = None,
) -> VideoSceneStructureArtifacts:
    resolved_backend = backend or build_agent_backend(
        config,
        use_llm=use_llm,
        provider=llm_provider,
        model=llm_model,
    )
    service = _build_video_service(config, resolved_backend)
    output_dir = output_root or (project_root / config.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    visual_bible = service._run_structured_agent(
        schema=CharacterVisualBibleSchema,
        request=PromptRequest(
            system_prompt=(
                "你是影视角色视觉设计 Agent。"
                "请把小说角色转换成稳定、可复用的角色视觉设定。"
                "输出要偏风格化概念设计，不要写成真人摄影或现实人物描述。"
            ),
            user_prompt=service._build_visual_bible_user_prompt(novel_package),
            metadata={"task": "video-character-bible"},
        ),
        validator=lambda value: service._validate_character_visual_bible_output(
            value,
            novel_package=novel_package,
        ),
    )
    visual_bible = service._repair_character_visual_bible(visual_bible, novel_package)
    story_memory = service._build_story_memory(
        novel_package,
        visual_bible,
        str(output_dir),
    )

    runtime_scenes: list[VideoScene] = []
    for chapter in sorted(novel_package.outline.chapters, key=lambda item: item.number):
        scene_structure = service._run_structured_agent(
            schema=ChapterSceneStructureSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是章节场景规划 Agent。"
                    "请只规划当前章节有哪些 scene。"
                    "只输出 scene 结构，不要输出 segment，不要输出图片 prompt。"
                ),
                user_prompt=service._build_chapter_scene_planner_user_prompt(
                    novel_package,
                    chapter_number=chapter.number,
                    story_memory=story_memory,
                ),
                metadata={
                    "task": "video-chapter-scene-planner",
                    "chapter_number": chapter.number,
                },
            ),
            validator=lambda value, chapter_number=chapter.number: service._validate_chapter_scene_structure_output(
                value,
                novel_package=novel_package,
                chapter_number=chapter_number,
            ),
        )
        materialized_scenes = [
            service._materialize_chapter_scene(
                raw_scene=scene,
                novel_package=novel_package,
                chapter_number=chapter.number,
            )
            for scene in scene_structure.scenes
        ]
        runtime_scenes.extend(
            _build_runtime_scene_skeletons(
                service=service,
                scenes=materialized_scenes,
                output_dir=output_dir,
            )
        )

    scene_plan = VideoSegmentPlanSchema.model_validate(
        {"scenes": to_jsonable(runtime_scenes)}
    )
    story_memory = service._sync_story_memory_with_plan(
        story_memory,
        novel_package=novel_package,
        plan=scene_plan,
    )
    if novel_package.outline.chapters:
        story_memory.generation_notes.last_planned_chapter = novel_package.outline.chapters[-1].number
    story_memory.generation_notes.last_successful_stage = "video-scene-structure"

    paths = resolve_video_planning_paths(output_dir)
    character_profiles = service._build_character_profiles(visual_bible)
    write_json(paths.story_memory_path, story_memory)
    write_json(paths.character_bible_path, character_profiles)
    write_json(paths.scene_plan_path, {"scenes": runtime_scenes})

    return VideoSceneStructureArtifacts(
        output_dir=output_dir,
        story_memory_path=paths.story_memory_path,
        character_bible_path=paths.character_bible_path,
        scene_plan_path=paths.scene_plan_path,
        scene_plan=scene_plan,
        story_memory=story_memory,
    )


def build_video_segment_contract_artifacts(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    continuity_review_mode: str = "auto",
    backend: AgentBackend | None = None,
    scene_structure_artifacts: VideoSceneStructureArtifacts | None = None,
) -> VideoPlanningArtifacts:
    resolved_backend = backend or build_agent_backend(
        config,
        use_llm=use_llm,
        provider=llm_provider,
        model=llm_model,
    )
    service = _build_video_service(config, resolved_backend)
    output_dir = output_root or (project_root / config.paths.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = resolve_video_planning_paths(output_dir)

    scene_structure = scene_structure_artifacts or _load_scene_structure_artifacts(output_dir)
    visual_bible = _load_character_visual_bible(paths.character_bible_path)
    _clear_segment_contract_execution_artifacts(output_dir)

    chapter_plans: list[VideoSegmentPlanSchema] = []
    story_memory = scene_structure.story_memory
    for chapter in sorted(novel_package.outline.chapters, key=lambda item: item.number):
        chapter_scene_structure = _build_chapter_scene_structure_from_plan(
            plan=scene_structure.scene_plan,
            chapter_number=chapter.number,
        )
        if not chapter_scene_structure.scenes:
            raise ValueError(f"第 {chapter.number} 章缺少 scene structure，无法继续生成 segment contracts。")
        chapter_plan = service._build_chapter_plan_from_scene_structure(
            novel_package=novel_package,
            story_memory=story_memory,
            chapter_number=chapter.number,
            scene_structure=chapter_scene_structure,
        )
        chapter_plan = service._post_process_segment_plan(
            chapter_plan,
            novel_package=novel_package,
            visual_bible=visual_bible,
            normalize_for_seedance=True,
            repair_continuity=True,
        )
        story_memory = service._update_story_memory_after_chapter(
            story_memory,
            novel_package=novel_package,
            chapter_plan=chapter_plan,
            chapter_number=chapter.number,
        )
        chapter_plans.append(chapter_plan)

    merged_plan = service._merge_chapter_segment_plans(chapter_plans)
    merged_plan = service._post_process_segment_plan(
        merged_plan,
        novel_package=novel_package,
        visual_bible=visual_bible,
        normalize_for_seedance=False,
        repair_continuity=True,
    )
    merged_plan = service._validate_segment_plan_output(
        merged_plan,
        novel_package=novel_package,
    )
    story_memory = service._sync_story_memory_with_plan(
        story_memory,
        novel_package=novel_package,
        plan=merged_plan,
    )

    character_profiles = service._build_character_profiles(visual_bible)
    profile_map = {item.name: item for item in character_profiles}
    voice_map = service._build_voice_map(novel_package)
    character_images = service._build_character_image_tasks(character_profiles, str(output_dir))
    scenes = service._build_runtime_scenes(merged_plan, str(output_dir))
    segments = service._build_runtime_segments(merged_plan, voice_map)
    scene_images = service._build_scene_image_tasks(
        scenes,
        segments,
        character_images,
        profile_map,
        str(output_dir),
    )
    manifest = service._build_seedance_manifest(
        novel_package.outline.title,
        segments,
        scene_images,
        str(output_dir),
    )

    write_json(paths.story_memory_path, story_memory)
    write_json(paths.character_bible_path, character_profiles)
    write_json(paths.character_images_path, character_images)
    write_json(paths.scene_plan_path, {"scenes": scenes})
    write_json(paths.segment_plan_path, segments)
    write_json(paths.scene_images_path, scene_images)
    write_json(paths.manifest_path, manifest)
    write_continuity_report(
        output_dir,
        config=config,
        review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )

    project_package = VideoProjectPackage(
        title=novel_package.outline.title,
        character_profiles=character_profiles,
        character_images=character_images,
        scenes=scenes,
        segments=segments,
        scene_images=scene_images,
        seedance_manifest=manifest,
        story_memory=story_memory,
        workflow_trace={},
    )

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        story_memory_path=paths.story_memory_path,
        character_bible_path=paths.character_bible_path,
        character_images_path=paths.character_images_path,
        scene_plan_path=paths.scene_plan_path,
        segment_plan_path=paths.segment_plan_path,
        scene_images_path=paths.scene_images_path,
        manifest_path=paths.manifest_path,
        project_package=project_package,
        manifest=manifest,
    )


def build_video_planning_artifacts(
    novel_package: NovelPackage,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    use_llm: bool = True,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    continuity_review_mode: str = "auto",
    backend: AgentBackend | None = None,
) -> VideoPlanningArtifacts:
    scene_structure = build_video_scene_structure_artifacts(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=output_root,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        backend=backend,
    )
    return build_video_segment_contract_artifacts(
        novel_package=novel_package,
        config=config,
        project_root=project_root,
        output_root=scene_structure.output_dir,
        use_llm=use_llm,
        llm_provider=llm_provider,
        llm_model=llm_model,
        continuity_review_mode=continuity_review_mode,
        backend=backend,
        scene_structure_artifacts=scene_structure,
    )


def load_video_planning_artifacts(output_dir: Path) -> VideoPlanningArtifacts:
    paths = resolve_video_planning_paths(output_dir)

    required_paths = {
        "character_visual_bible.json": paths.character_bible_path,
        "character_image_manifest.json": paths.character_images_path,
        "segment_plan.json": paths.segment_plan_path,
        "scene_image_manifest.json": paths.scene_images_path,
        "seedance_manifest.json": paths.manifest_path,
    }
    missing_files = [name for name, path in required_paths.items() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            "Video planning artifacts are incomplete. Generate structured story information first. Missing: "
            + ", ".join(missing_files)
        )

    manifest = load_seedance_manifest(output_dir)
    scene_plan = load_video_segment_plan(output_dir)
    story_memory = (
        StoryMemoryPackage.from_dict(read_json(paths.story_memory_path))
        if paths.story_memory_path.exists()
        else None
    )

    project_package = VideoProjectPackage(
        title=_resolve_video_project_title(output_dir, manifest),
        character_profiles=[
            CharacterVisualProfile.from_dict(item)
            for item in read_json(paths.character_bible_path)
        ],
        character_images=[
            CharacterImageTask.from_dict(item)
            for item in read_json(paths.character_images_path)
        ],
        scenes=[
            VideoScene.from_dict(item.model_dump())
            for item in scene_plan.scenes
        ],
        segments=[VideoSegment.from_dict(item.model_dump()) for item in scene_plan.segments],
        scene_images=[
            SceneImageTask.from_dict(item)
            for item in read_json(paths.scene_images_path)
        ],
        seedance_manifest=manifest,
        story_memory=story_memory,
        workflow_trace={},
    )

    return VideoPlanningArtifacts(
        output_dir=output_dir,
        story_memory_path=paths.story_memory_path,
        character_bible_path=paths.character_bible_path,
        character_images_path=paths.character_images_path,
        scene_plan_path=paths.scene_plan_path,
        segment_plan_path=paths.segment_plan_path,
        scene_images_path=paths.scene_images_path,
        manifest_path=paths.manifest_path,
        project_package=project_package,
        manifest=project_package.seedance_manifest,
    )


def resolve_video_planning_paths(output_dir: Path) -> VideoPlanningPaths:
    return VideoPlanningPaths(
        output_dir=output_dir,
        story_memory_path=output_dir / "story_memory.json",
        character_bible_path=output_dir / "character_visual_bible.json",
        character_images_path=output_dir / "character_image_manifest.json",
        scene_plan_path=output_dir / "scene_plan.json",
        segment_plan_path=output_dir / "segment_plan.json",
        scene_images_path=output_dir / "scene_image_manifest.json",
        manifest_path=output_dir / "seedance_manifest.json",
    )


def load_video_segment_plan(output_dir: Path) -> VideoSegmentPlanSchema:
    paths = resolve_video_planning_paths(output_dir)
    return _load_scene_plan(paths.scene_plan_path, paths.segment_plan_path)


def load_scene_image_task_map(output_dir: Path) -> dict[str, SceneImageTask]:
    scene_images_path = resolve_video_planning_paths(output_dir).scene_images_path
    if not scene_images_path.exists():
        return {}
    raw_scene_tasks = read_json(scene_images_path)
    if not isinstance(raw_scene_tasks, list):
        return {}
    try:
        return {
            item.segment_id: item
            for item in (
                SceneImageTask.from_dict(raw)
                for raw in raw_scene_tasks
            )
        }
    except Exception:
        return {}


def load_seedance_manifest(output_dir: Path) -> SeedanceManifest:
    manifest_path = resolve_video_planning_paths(output_dir).manifest_path
    return SeedanceManifest.from_dict(read_json(manifest_path))


def load_seedance_clip_map(output_dir: Path) -> dict[str, SeedanceClipTask]:
    manifest_path = resolve_video_planning_paths(output_dir).manifest_path
    if not manifest_path.exists():
        return {}
    raw_manifest = read_json(manifest_path)
    if not isinstance(raw_manifest, dict):
        return {}
    if "title" not in raw_manifest or "model" not in raw_manifest:
        return {}
    try:
        manifest = SeedanceManifest.from_dict(raw_manifest)
    except Exception:
        return {}
    return {clip.segment_id: clip for clip in manifest.clips}


def _build_video_service(
    config: AppConfig,
    backend: AgentBackend,
) -> NovelToVideoService:
    return NovelToVideoService(
        backend=backend,
        segment_duration_seconds=config.video.segment_duration_seconds,
        aspect_ratio=config.video.aspect_ratio,
        fps=config.video.fps,
        character_image_provider=config.video.character_image_provider,
        scene_image_provider=config.video.scene_image_provider,
        seedance_config=config.seedance,
    )


def _build_runtime_scene_skeletons(
    *,
    service: NovelToVideoService,
    scenes: list[ChapterSceneSchema],
    output_dir: Path,
) -> list[VideoScene]:
    runtime_scenes = [
        VideoScene(
            scene_id=scene.scene_id,
            chapter_number=scene.chapter_number,
            title=scene.title,
            summary=scene.summary,
            scene_anchor=scene.scene_anchor,
            involved_characters=list(scene.involved_characters),
            segments=[],
            scene_bible=scene.scene_bible.model_copy(deep=True),
        )
        for scene in scenes
    ]
    return service._prepare_scene_master_frames(runtime_scenes, str(output_dir))


def _load_scene_structure_artifacts(output_dir: Path) -> VideoSceneStructureArtifacts:
    paths = resolve_video_planning_paths(output_dir)
    required_paths = {
        "story_memory.json": paths.story_memory_path,
        "character_visual_bible.json": paths.character_bible_path,
        "scene_plan.json": paths.scene_plan_path,
    }
    missing_files = [name for name, path in required_paths.items() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            "Scene structure artifacts are incomplete. Generate scene structure first. Missing: "
            + ", ".join(missing_files)
        )

    return VideoSceneStructureArtifacts(
        output_dir=output_dir,
        story_memory_path=paths.story_memory_path,
        character_bible_path=paths.character_bible_path,
        scene_plan_path=paths.scene_plan_path,
        story_memory=StoryMemoryPackage.from_dict(read_json(paths.story_memory_path)),
        scene_plan=load_video_segment_plan(output_dir),
    )


def _load_character_visual_bible(path: Path) -> CharacterVisualBibleSchema:
    raw_payload = read_json(path)
    if isinstance(raw_payload, list):
        return CharacterVisualBibleSchema.model_validate({"characters": raw_payload})
    if isinstance(raw_payload, dict) and isinstance(raw_payload.get("characters"), list):
        return CharacterVisualBibleSchema.model_validate(raw_payload)
    raise ValueError(f"Character visual bible at {path} is not a valid character list.")


def _build_chapter_scene_structure_from_plan(
    *,
    plan: VideoSegmentPlanSchema,
    chapter_number: int,
) -> ChapterSceneStructureSchema:
    scenes = [
        ChapterSceneSchema.model_validate(
            {
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "title": scene.title,
                "summary": scene.summary,
                "scene_anchor": scene.scene_anchor,
                "involved_characters": list(scene.involved_characters),
                "scene_bible": scene.scene_bible.model_dump(),
            }
        )
        for scene in plan.scenes
        if scene.chapter_number == chapter_number
    ]
    return ChapterSceneStructureSchema(scenes=scenes)


def _clear_segment_contract_execution_artifacts(output_dir: Path) -> None:
    removable_files = {
        output_dir / "segment_plan.json",
        output_dir / "scene_image_manifest.json",
        output_dir / "seedream_scene_execution.json",
        output_dir / "seedance_manifest.json",
        output_dir / "seedance_execution.json",
        output_dir / "continuity_report.json",
    }
    removable_dirs = {
        output_dir / "assets" / "frames",
        output_dir / "rendered",
    }

    for path in removable_files:
        if path.exists():
            path.unlink()

    for path in output_dir.glob("continuity_repair_*.json"):
        if path.is_file():
            path.unlink()

    for path in removable_dirs:
        if path.exists():
            shutil.rmtree(path)


def _resolve_video_project_title(output_dir: Path, manifest: SeedanceManifest) -> str:
    novel_package_path = output_dir / "novel_package.json"
    if novel_package_path.exists():
        payload = read_json(novel_package_path)
        if isinstance(payload, dict):
            outline = payload.get("outline")
            if isinstance(outline, dict):
                title = str(outline.get("title", "")).strip()
                if title:
                    return title

    story_source_path = output_dir / "story_source.json"
    if story_source_path.exists():
        payload = read_json(story_source_path)
        if isinstance(payload, dict):
            title = StorySourcePackage.from_dict(payload).title.strip()
            if title:
                return title

    manifest_title = manifest.title.strip()
    if manifest_title and manifest_title not in {"segment_video_manifest", "seedance_manifest"}:
        return manifest_title
    return output_dir.name


def _load_scene_plan(scene_plan_path: Path, segment_plan_path: Path) -> VideoSegmentPlanSchema:
    if scene_plan_path.exists():
        payload = read_json(scene_plan_path)
        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict) and "segments" in payload[0]:
                return VideoSegmentPlanSchema.model_validate({"scenes": payload})
            return VideoSegmentPlanSchema.model_validate({"segments": payload})
        return VideoSegmentPlanSchema.model_validate(payload)

    segment_payload = read_json(segment_plan_path)
    return VideoSegmentPlanSchema.model_validate({"segments": segment_payload})
