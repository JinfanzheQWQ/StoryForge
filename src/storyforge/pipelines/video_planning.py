from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Callable

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
    SceneSegmentChunkPlanSchema,
    SceneSegmentContractBatchSchema,
    SceneSegmentContractSchema,
    VideoSegmentPlanSchema,
)
from storyforge.domains.video.service import NovelToVideoService
from storyforge.integrations.llm import build_agent_backend
from storyforge.pipelines.continuity import write_continuity_report
from storyforge.pipelines.video_models import (
    SegmentContractChunkProgress,
    SegmentContractChapterProgress,
    SegmentContractProgress,
    SegmentContractSceneProgress,
    VideoPlanningArtifacts,
    VideoPlanningPaths,
    VideoSceneStructureArtifacts,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        scene_structure = service._plan_chapter_scene_structure(
            novel_package=novel_package,
            story_memory=story_memory,
            chapter_number=chapter.number,
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
    resume_from_progress: bool = False,
    progress_callback: Callable[[SegmentContractProgress], None] | None = None,
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
    progress = _build_initial_segment_contract_progress(
        novel_package=novel_package,
        scene_structure=scene_structure,
        story_source_revision=scene_structure.story_memory.story_identity.story_source_revision,
    )
    chapter_plan_map: dict[int, VideoSegmentPlanSchema] = {}
    story_memory = scene_structure.story_memory

    if resume_from_progress:
        progress, chapter_plan_map, story_memory = _restore_segment_contract_resume_state(
            output_dir=output_dir,
            novel_package=novel_package,
            scene_structure=scene_structure,
            service=service,
        )
    else:
        _clear_segment_contract_execution_artifacts(output_dir)

    write_json(_scene_structure_snapshot_path(output_dir), scene_structure.scene_plan)

    progress.status = "running"
    progress.running_chapter_number = 0
    progress.running_chunk_id = ""
    progress.failed_chapter_number = 0
    progress.failed_scene_id = ""
    progress.failed_chunk_id = ""
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = _utc_now()
    _refresh_segment_contract_progress(progress)
    write_json(paths.segment_contract_progress_path, progress)
    if progress_callback is not None:
        progress_callback(progress)
    for chapter in sorted(novel_package.outline.chapters, key=lambda item: item.number):
        chapter_progress = _require_segment_contract_chapter(progress, chapter.number)
        if chapter_progress.status == "completed":
            continue
        chapter_scene_structure = _build_chapter_scene_structure_from_plan(
            plan=scene_structure.scene_plan,
            chapter_number=chapter.number,
        )
        if not chapter_scene_structure.scenes:
            raise ValueError(f"第 {chapter.number} 章缺少 scene structure，无法继续生成 segment contracts。")
        _mark_segment_contract_chapter_running(progress, chapter.number)
        write_json(paths.segment_contract_progress_path, progress)
        if progress_callback is not None:
            progress_callback(progress)
        chapter_plan = chapter_plan_map.get(chapter.number) or _empty_video_segment_plan()
        try:
            for scene in chapter_scene_structure.scenes:
                scene_progress = _require_segment_contract_scene(
                    progress,
                    chapter_number=chapter.number,
                    scene_id=scene.scene_id,
                )
                if scene_progress.status == "completed":
                    continue
                _mark_segment_contract_scene_running(
                    progress,
                    chapter_number=chapter.number,
                    scene_id=scene.scene_id,
                    scene_title=scene.title,
                )
                write_json(paths.segment_contract_progress_path, progress)
                if progress_callback is not None:
                    progress_callback(progress)
                materialized_scene = service._materialize_chapter_scene(
                    raw_scene=scene,
                    novel_package=novel_package,
                    chapter_number=chapter.number,
                )
                chunk_plan = _load_or_create_segment_contract_scene_chunk_plan(
                    progress=progress,
                    service=service,
                    novel_package=novel_package,
                    story_memory=story_memory,
                    chapter_number=chapter.number,
                    scene=materialized_scene,
                )
                write_json(paths.segment_contract_progress_path, progress)
                if progress_callback is not None:
                    progress_callback(progress)

                scene_plan = _extract_segment_contract_scene_plan(
                    chapter_plan,
                    scene_id=materialized_scene.scene_id,
                )
                chunk_batches = _build_chunk_batches_from_existing_scene_plan(scene_plan)
                if (
                    any(chunk.status == "completed" for chunk in scene_progress.chunks)
                    and not chunk_batches
                ):
                    raise ValueError(
                        "segment_contracts checkpoint 已记录完成 chunk，但当前 scene 的部分分段合同缺失，"
                        f"无法恢复 chapter={chapter.number} scene_id={materialized_scene.scene_id}。"
                    )
                previous_tail_segment = _extract_scene_tail_contract(scene_plan)
                previous_chunk_exit_state = (
                    service._build_scene_chunk_exit_state(previous_tail_segment)
                    if previous_tail_segment is not None
                    else None
                )

                for chunk in chunk_plan.chunks:
                    chunk_progress = _require_segment_contract_chunk(
                        progress,
                        chapter_number=chapter.number,
                        scene_id=materialized_scene.scene_id,
                        chunk_id=chunk.chunk_id,
                    )
                    if chunk_progress.status == "completed":
                        continue
                    _mark_segment_contract_chunk_running(
                        progress=progress,
                        chapter_number=chapter.number,
                        scene_id=materialized_scene.scene_id,
                        chunk_id=chunk.chunk_id,
                    )
                    write_json(paths.segment_contract_progress_path, progress)
                    if progress_callback is not None:
                        progress_callback(progress)

                    chunk_batch = service._build_scene_chunk_contract_batch(
                        novel_package=novel_package,
                        story_memory=story_memory,
                        chapter_number=chapter.number,
                        scene=materialized_scene,
                        chunk=chunk,
                        previous_chunk_exit_state=previous_chunk_exit_state,
                        previous_tail_segment=previous_tail_segment,
                    )
                    previous_scene_segment_count = len(scene_plan.segments) if scene_plan is not None else 0
                    chunk_batches.append(chunk_batch)
                    scene_plan = service._build_scene_plan_from_chunk_batches(
                        novel_package=novel_package,
                        scene=materialized_scene,
                        chunk_batches=chunk_batches,
                    )
                    chapter_plan = _merge_segment_contract_scene_plan(
                        service=service,
                        novel_package=novel_package,
                        visual_bible=visual_bible,
                        existing_plan=chapter_plan,
                        scene_plan=scene_plan,
                    )
                    chapter_plan_map[chapter.number] = chapter_plan
                    scene_plan = _extract_segment_contract_scene_plan(
                        chapter_plan,
                        scene_id=materialized_scene.scene_id,
                    ) or scene_plan
                    _mark_segment_contract_chunk_completed(
                        progress=progress,
                        chapter_number=chapter.number,
                        scene_id=materialized_scene.scene_id,
                        chunk_id=chunk.chunk_id,
                        chunk_segment_count=max(
                            0,
                            len(scene_plan.segments) - previous_scene_segment_count,
                        ),
                        scene_plan=scene_plan,
                    )
                    _write_segment_contract_checkpoint(
                        service=service,
                        novel_package=novel_package,
                        visual_bible=visual_bible,
                        story_memory=story_memory,
                        chapter_plans=_ordered_segment_contract_chapter_plans(chapter_plan_map),
                        paths=paths,
                        progress=progress,
                    )
                    if progress_callback is not None:
                        progress_callback(progress)
                    previous_tail_segment = _extract_scene_tail_contract(scene_plan)
                    previous_chunk_exit_state = (
                        service._build_scene_chunk_exit_state(previous_tail_segment)
                        if previous_tail_segment is not None
                        else None
                    )

                if scene_plan is None or not scene_plan.scenes:
                    raise ValueError(
                        f"scene {materialized_scene.scene_id} 没有可恢复的 chunk contracts，无法完成 scene 规划。"
                    )
                chapter_plan = _merge_segment_contract_scene_plan(
                    service=service,
                    novel_package=novel_package,
                    visual_bible=visual_bible,
                    existing_plan=chapter_plan,
                    scene_plan=scene_plan,
                )
                chapter_plan_map[chapter.number] = chapter_plan
                _mark_segment_contract_scene_completed(
                    progress=progress,
                    chapter_number=chapter.number,
                    scene_id=materialized_scene.scene_id,
                    scene_plan=scene_plan,
                )
                _write_segment_contract_checkpoint(
                    service=service,
                    novel_package=novel_package,
                    visual_bible=visual_bible,
                    story_memory=story_memory,
                    chapter_plans=_ordered_segment_contract_chapter_plans(chapter_plan_map),
                    paths=paths,
                    progress=progress,
                )
                if progress_callback is not None:
                    progress_callback(progress)
            if not chapter_plan.scenes:
                raise ValueError(f"第 {chapter.number} 章没有可恢复的 scene contracts，无法完成章节规划。")
            story_memory = service._update_story_memory_after_chapter(
                story_memory,
                novel_package=novel_package,
                chapter_plan=chapter_plan,
                chapter_number=chapter.number,
            )
            chapter_plan_map[chapter.number] = chapter_plan

            _mark_segment_contract_chapter_completed(
                progress=progress,
                chapter_number=chapter.number,
                chapter_plan=chapter_plan,
            )
            _write_segment_contract_checkpoint(
                service=service,
                novel_package=novel_package,
                visual_bible=visual_bible,
                story_memory=story_memory,
                chapter_plans=_ordered_segment_contract_chapter_plans(chapter_plan_map),
                paths=paths,
                progress=progress,
            )
            if progress_callback is not None:
                progress_callback(progress)
        except Exception as exc:
            _mark_segment_contract_scene_failed(
                progress=progress,
                chapter_number=chapter.number,
                scene_id=str(getattr(exc, "scene_id", "") or progress.running_scene_id),
                error=exc,
            )
            write_json(paths.segment_contract_progress_path, progress)
            if progress_callback is not None:
                progress_callback(progress)
            raise

    progress.status = "completed"
    progress.running_chapter_number = 0
    progress.running_chunk_id = ""
    progress.failed_chapter_number = 0
    progress.failed_scene_id = ""
    progress.failed_chunk_id = ""
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = _utc_now()

    final_artifacts = _write_segment_contract_checkpoint(
        service=service,
        novel_package=novel_package,
        visual_bible=visual_bible,
        story_memory=story_memory,
        chapter_plans=_ordered_segment_contract_chapter_plans(chapter_plan_map),
        paths=paths,
        progress=progress,
        write_continuity=True,
        config=config,
        continuity_review_mode=continuity_review_mode,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    if progress_callback is not None:
        progress_callback(progress)
    return final_artifacts


def _build_initial_segment_contract_progress(
    *,
    novel_package: NovelPackage,
    scene_structure: VideoSceneStructureArtifacts,
    story_source_revision: str,
) -> SegmentContractProgress:
    scenes_by_chapter: dict[int, list[ChapterSceneSchema]] = {}
    for scene in scene_structure.scene_plan.scenes:
        scenes_by_chapter.setdefault(scene.chapter_number, []).append(scene)
    progress = SegmentContractProgress(
        status="pending",
        story_title=novel_package.outline.title,
        story_source_revision=story_source_revision,
        total_chapters=len(novel_package.outline.chapters),
        total_scenes=len(scene_structure.scene_plan.scenes),
        chapters=[
            SegmentContractChapterProgress(
                chapter_number=chapter.number,
                chapter_title=chapter.title,
                scene_count=len(scenes_by_chapter.get(chapter.number, [])),
                scenes=[
                    SegmentContractSceneProgress(
                        scene_id=scene.scene_id,
                        scene_title=scene.title,
                        chapter_number=scene.chapter_number,
                    )
                    for scene in scenes_by_chapter.get(chapter.number, [])
                ],
            )
            for chapter in sorted(novel_package.outline.chapters, key=lambda item: item.number)
        ],
    )
    _refresh_segment_contract_progress(progress)
    progress.last_updated_at = _utc_now()
    return progress


def _restore_segment_contract_resume_state(
    *,
    output_dir: Path,
    novel_package: NovelPackage,
    scene_structure: VideoSceneStructureArtifacts,
    service: NovelToVideoService,
) -> tuple[SegmentContractProgress, dict[int, VideoSegmentPlanSchema], StoryMemoryPackage]:
    progress = load_segment_contract_progress(output_dir)
    if progress is None:
        raise FileNotFoundError(
            "segment_contract_progress.json 不存在，无法继续分段合同任务。请重新生成分段合同。"
        )

    expected_revision = scene_structure.story_memory.story_identity.story_source_revision
    if progress.story_source_revision and progress.story_source_revision != expected_revision:
        raise ValueError("现有分段合同 checkpoint 与当前 story_source_revision 不一致，不能继续恢复。")

    if progress.status == "completed":
        raise ValueError("现有分段合同 checkpoint 已完成，无需继续恢复。")

    if not any(chapter.scenes for chapter in progress.chapters):
        raise ValueError(
            "现有分段合同 checkpoint 缺少 scene 级结构，属于旧版本数据；请重新生成分段合同。"
        )
    if any(
        not scene.chunks
        for chapter in progress.chapters
        for scene in chapter.scenes
        if (
            scene.status != "pending"
            or scene.completed_chunk_count > 0
            or scene.segment_count > 0
            or scene.failed_chunk_id
        )
    ):
        raise ValueError(
            "现有分段合同 checkpoint 缺少 chunk 级进度，属于旧版本数据；请重新生成分段合同。"
        )

    partial_plan = (
        load_video_segment_plan(output_dir)
        if _progress_has_completed_scenes(progress)
        and (
            resolve_video_planning_paths(output_dir).scene_plan_path.exists()
            or resolve_video_planning_paths(output_dir).segment_plan_path.exists()
        )
        else VideoSegmentPlanSchema.model_validate({"scenes": []})
    )
    chapter_plan_map = _split_plan_by_progress(partial_plan, progress)
    story_memory = _restore_story_memory_for_resume(
        service=service,
        novel_package=novel_package,
        scene_structure=scene_structure,
        chapter_plan_map=chapter_plan_map,
        progress=progress,
    )

    progress.status = "running"
    progress.running_chapter_number = 0
    progress.running_scene_id = ""
    progress.running_chunk_id = ""
    progress.failed_chapter_number = 0
    progress.failed_scene_id = ""
    progress.failed_chunk_id = ""
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = _utc_now()
    for chapter in progress.chapters:
        if chapter.status != "completed":
            chapter.status = "pending"
            chapter.running_scene_id = ""
            chapter.started_at = None
            chapter.finished_at = None
            chapter.failed_scene_id = ""
            chapter.error = ""
        for scene in chapter.scenes:
            if scene.status != "completed":
                scene.status = "pending"
                scene.running_chunk_id = ""
                scene.started_at = None
                scene.finished_at = None
                scene.failed_chunk_id = ""
                scene.error = ""
            for chunk in scene.chunks:
                if chunk.status != "completed":
                    chunk.status = "pending"
                    chunk.started_at = None
                    chunk.finished_at = None
                    chunk.error = ""
    _refresh_segment_contract_progress(progress)
    return progress, chapter_plan_map, story_memory


def _split_plan_by_progress(
    plan: VideoSegmentPlanSchema,
    progress: SegmentContractProgress,
) -> dict[int, VideoSegmentPlanSchema]:
    chapter_plans: dict[int, VideoSegmentPlanSchema] = {}
    for chapter in progress.chapters:
        resumable_scene_ids = {
            item.scene_id
            for item in chapter.scenes
            if item.status == "completed"
            or any(chunk.status == "completed" for chunk in item.chunks)
        }
        scenes = [
            scene.model_dump()
            for scene in plan.scenes
            if scene.chapter_number == chapter.chapter_number
            and (
                chapter.status == "completed"
                or not resumable_scene_ids
                or scene.scene_id in resumable_scene_ids
            )
        ]
        if not scenes:
            continue
        chapter_plans[chapter.chapter_number] = VideoSegmentPlanSchema.model_validate({"scenes": scenes})
    return chapter_plans


def _progress_has_completed_scenes(progress: SegmentContractProgress) -> bool:
    if (
        progress.completed_scene_count > 0
        or progress.completed_chapters > 0
        or progress.completed_chunk_count > 0
    ):
        return True
    return any(
        scene.status == "completed"
        or any(chunk.status == "completed" for chunk in scene.chunks)
        for chapter in progress.chapters
        for scene in chapter.scenes
    )


def _restore_story_memory_for_resume(
    *,
    service: NovelToVideoService,
    novel_package: NovelPackage,
    scene_structure: VideoSceneStructureArtifacts,
    chapter_plan_map: dict[int, VideoSegmentPlanSchema],
    progress: SegmentContractProgress,
) -> StoryMemoryPackage:
    completed_chapter_plans = [
        plan
        for chapter_number, plan in sorted(chapter_plan_map.items())
        if _require_segment_contract_chapter(progress, chapter_number).status == "completed"
    ]
    if not completed_chapter_plans:
        return StoryMemoryPackage.from_dict(to_jsonable(scene_structure.story_memory))
    restored_story_memory = StoryMemoryPackage.from_dict(to_jsonable(scene_structure.story_memory))
    return service._sync_story_memory_with_plan(
        restored_story_memory,
        novel_package=novel_package,
        plan=service._merge_chapter_segment_plans(completed_chapter_plans),
    )


def _empty_video_segment_plan() -> VideoSegmentPlanSchema:
    return VideoSegmentPlanSchema.model_validate({"scenes": []})


def _ordered_segment_contract_chapter_plans(
    chapter_plan_map: dict[int, VideoSegmentPlanSchema],
) -> list[VideoSegmentPlanSchema]:
    return [
        chapter_plan_map[chapter_number]
        for chapter_number in sorted(chapter_plan_map)
    ]


def _merge_segment_contract_scene_plan(
    *,
    service: NovelToVideoService,
    novel_package: NovelPackage,
    visual_bible: CharacterVisualBibleSchema,
    existing_plan: VideoSegmentPlanSchema,
    scene_plan: VideoSegmentPlanSchema,
) -> VideoSegmentPlanSchema:
    replacement_map = {
        scene.scene_id: scene.model_dump()
        for scene in scene_plan.scenes
    }
    merged_scenes: list[dict[str, object]] = []
    inserted_scene_ids: set[str] = set()
    for existing_scene in existing_plan.scenes:
        if existing_scene.scene_id in replacement_map:
            merged_scenes.append(replacement_map[existing_scene.scene_id])
            inserted_scene_ids.add(existing_scene.scene_id)
        else:
            merged_scenes.append(existing_scene.model_dump())
    for scene in scene_plan.scenes:
        if scene.scene_id not in inserted_scene_ids:
            merged_scenes.append(scene.model_dump())
    merged_plan = VideoSegmentPlanSchema.model_validate(
        {"scenes": merged_scenes}
    )
    return service._post_process_segment_plan(
        merged_plan,
        novel_package=novel_package,
        visual_bible=visual_bible,
        normalize_for_seedance=True,
        repair_continuity=True,
    )


def _require_segment_contract_chapter(
    progress: SegmentContractProgress,
    chapter_number: int,
) -> SegmentContractChapterProgress:
    chapter = next(
        (item for item in progress.chapters if item.chapter_number == chapter_number),
        None,
    )
    if chapter is None:
        raise ValueError(f"Segment contract progress 缺少 chapter={chapter_number}。")
    return chapter


def _require_segment_contract_scene(
    progress: SegmentContractProgress,
    *,
    chapter_number: int,
    scene_id: str,
) -> SegmentContractSceneProgress:
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    scene = next((item for item in chapter.scenes if item.scene_id == scene_id), None)
    if scene is None:
        raise ValueError(
            f"Segment contract progress 缺少 chapter={chapter_number} scene_id={scene_id}。"
        )
    return scene


def _require_segment_contract_chunk(
    progress: SegmentContractProgress,
    *,
    chapter_number: int,
    scene_id: str,
    chunk_id: str,
) -> SegmentContractChunkProgress:
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    chunk = next((item for item in scene.chunks if item.chunk_id == chunk_id), None)
    if chunk is None:
        raise ValueError(
            "Segment contract progress 缺少 "
            f"chapter={chapter_number} scene_id={scene_id} chunk_id={chunk_id}。"
        )
    return chunk


def _load_or_create_segment_contract_scene_chunk_plan(
    *,
    progress: SegmentContractProgress,
    service: NovelToVideoService,
    novel_package: NovelPackage,
    story_memory: StoryMemoryPackage,
    chapter_number: int,
    scene: ChapterSceneSchema,
) -> SceneSegmentChunkPlanSchema:
    scene_progress = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene.scene_id,
    )
    if scene_progress.chunks:
        return SceneSegmentChunkPlanSchema.model_validate(
            {
                "scene_id": scene.scene_id,
                "chapter_number": chapter_number,
                "chunks": [
                    {
                        "chunk_id": item.chunk_id,
                        "order_index": item.order_index,
                        "title": item.title,
                        "summary": item.summary,
                        "must_cover": list(item.must_cover),
                        "transition_goal": item.transition_goal,
                        "expected_segment_count": item.expected_segment_count,
                    }
                    for item in sorted(scene_progress.chunks, key=lambda chunk: chunk.order_index)
                ],
            }
        )

    chunk_plan = service._plan_scene_chunk_outline(
        novel_package=novel_package,
        story_memory=story_memory,
        chapter_number=chapter_number,
        scene=scene,
    )
    _apply_segment_contract_scene_chunk_plan(
        progress=progress,
        chapter_number=chapter_number,
        scene_id=scene.scene_id,
        chunk_plan=chunk_plan,
    )
    return chunk_plan


def _apply_segment_contract_scene_chunk_plan(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    scene_id: str,
    chunk_plan: SceneSegmentChunkPlanSchema,
) -> None:
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    preserved_status: dict[str, SegmentContractChunkProgress] = {
        item.chunk_id: item
        for item in scene.chunks
    }
    rebuilt_chunks: list[SegmentContractChunkProgress] = []
    for chunk in chunk_plan.chunks:
        previous_chunk = preserved_status.get(chunk.chunk_id)
        rebuilt_chunks.append(
            SegmentContractChunkProgress(
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                summary=chunk.summary,
                order_index=chunk.order_index,
                must_cover=list(chunk.must_cover),
                transition_goal=chunk.transition_goal,
                expected_segment_count=chunk.expected_segment_count,
                status=previous_chunk.status if previous_chunk else "pending",
                segment_count=previous_chunk.segment_count if previous_chunk else 0,
                started_at=previous_chunk.started_at if previous_chunk else None,
                finished_at=previous_chunk.finished_at if previous_chunk else None,
                error=previous_chunk.error if previous_chunk else "",
            )
        )
    scene.chunks = rebuilt_chunks
    _refresh_segment_contract_progress(progress)
    progress.last_updated_at = _utc_now()


def _extract_segment_contract_scene_plan(
    chapter_plan: VideoSegmentPlanSchema,
    *,
    scene_id: str,
) -> VideoSegmentPlanSchema | None:
    target_scene = next(
        (scene for scene in chapter_plan.scenes if scene.scene_id == scene_id),
        None,
    )
    if target_scene is None:
        return None
    return VideoSegmentPlanSchema.model_validate(
        {"scenes": [target_scene.model_dump()]}
    )


def _build_chunk_batches_from_existing_scene_plan(
    scene_plan: VideoSegmentPlanSchema | None,
) -> list[SceneSegmentContractBatchSchema]:
    if scene_plan is None or not scene_plan.scenes:
        return []
    scene = scene_plan.scenes[0]
    if not scene.segments:
        return []
    return [
        SceneSegmentContractBatchSchema.model_validate(
            {
                "scene_id": scene.scene_id,
                "chapter_number": scene.chapter_number,
                "segments": [
                    _build_contract_payload_from_video_segment(segment)
                    for segment in scene.segments
                ],
            }
        )
    ]


def _extract_scene_tail_contract(
    scene_plan: VideoSegmentPlanSchema | None,
) -> SceneSegmentContractSchema | None:
    if scene_plan is None or not scene_plan.scenes or not scene_plan.segments:
        return None
    return SceneSegmentContractSchema.model_validate(
        _build_contract_payload_from_video_segment(scene_plan.segments[-1])
    )


def _build_contract_payload_from_video_segment(segment) -> dict[str, object]:
    return {
        "segment_id": segment.segment_id,
        "chapter_number": segment.chapter_number,
        "scene_id": segment.scene_id,
        "title": segment.title,
        "summary": segment.summary,
        "involved_characters": list(segment.involved_characters),
        "start_frame_characters": list(segment.start_frame_characters),
        "mid_frame_characters": list(segment.mid_frame_characters),
        "end_frame_characters": list(segment.end_frame_characters),
        "narration": segment.narration,
        "dialogue_lines": list(segment.dialogue_lines),
        "subtitle_lines": list(segment.subtitle_lines),
        "timed_beats": list(segment.timed_beats),
        "duration_seconds": segment.duration_seconds,
        "requires_mid_frame": segment.requires_mid_frame,
        "transition_hint": segment.transition_hint,
        "shot_state": segment.shot_state.model_dump(),
        "continuity_link": segment.continuity_link.model_dump(),
    }


def _refresh_segment_contract_progress(progress: SegmentContractProgress) -> None:
    progress.total_chapters = len(progress.chapters)
    progress.total_scenes = 0
    progress.total_chunks = 0
    progress.completed_chapters = 0
    progress.completed_scene_count = 0
    progress.completed_chunk_count = 0
    progress.completed_segment_count = 0
    progress.running_chapter_number = 0
    progress.running_scene_id = ""
    progress.running_chunk_id = ""
    progress.failed_chapter_number = 0
    progress.failed_scene_id = ""
    progress.failed_chunk_id = ""
    for chapter in progress.chapters:
        if chapter.scenes:
            chapter.scene_count = len(chapter.scenes)
            chapter.completed_scene_count = len(
                [item for item in chapter.scenes if item.status == "completed"]
            )
            chapter.segment_count = sum(item.segment_count for item in chapter.scenes)
            running_scene = next(
                (item.scene_id for item in chapter.scenes if item.status == "running"),
                "",
            )
            chapter.running_scene_id = running_scene
        for scene in chapter.scenes:
            scene.chunk_count = len(scene.chunks)
            scene.completed_chunk_count = len(
                [item for item in scene.chunks if item.status == "completed"]
            )
            progress.total_chunks += scene.chunk_count
            progress.completed_chunk_count += scene.completed_chunk_count
            if scene.status == "running" and scene.running_chunk_id and not progress.running_chunk_id:
                progress.running_chunk_id = scene.running_chunk_id
            if scene.status == "failed" and scene.failed_chunk_id and not progress.failed_chunk_id:
                progress.failed_chunk_id = scene.failed_chunk_id
        progress.total_scenes += chapter.scene_count
        progress.completed_scene_count += chapter.completed_scene_count
        progress.completed_segment_count += chapter.segment_count
        if chapter.status == "completed":
            progress.completed_chapters += 1
        elif chapter.status == "running" and not progress.running_chapter_number:
            progress.running_chapter_number = chapter.chapter_number
            progress.running_scene_id = chapter.running_scene_id
        elif chapter.status == "failed" and not progress.failed_chapter_number:
            progress.failed_chapter_number = chapter.chapter_number
            progress.failed_scene_id = chapter.failed_scene_id


def _mark_segment_contract_chapter_running(
    progress: SegmentContractProgress,
    chapter_number: int,
) -> None:
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    progress.status = "running"
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = now
    chapter.status = "running"
    chapter.started_at = chapter.started_at or now
    chapter.finished_at = None
    chapter.running_scene_id = ""
    chapter.failed_scene_id = ""
    chapter.error = ""
    _refresh_segment_contract_progress(progress)
    progress.failed_chapter_number = 0
    progress.failed_scene_id = ""
    progress.failed_chunk_id = ""
    progress.running_chapter_number = chapter_number
    progress.running_scene_id = ""
    progress.running_chunk_id = ""


def _mark_segment_contract_scene_running(
    progress: SegmentContractProgress,
    *,
    chapter_number: int,
    scene_id: str,
    scene_title: str,
) -> None:
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    progress.status = "running"
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = now
    chapter.status = "running"
    chapter.started_at = chapter.started_at or now
    chapter.finished_at = None
    chapter.running_scene_id = scene_id
    chapter.failed_scene_id = ""
    chapter.error = ""
    scene.scene_title = scene_title or scene.scene_title
    scene.status = "running"
    scene.started_at = scene.started_at or now
    scene.finished_at = None
    scene.running_chunk_id = ""
    scene.failed_chunk_id = ""
    scene.error = ""
    _refresh_segment_contract_progress(progress)
    progress.running_chapter_number = chapter_number
    progress.running_scene_id = scene_id
    progress.running_chunk_id = ""


def _mark_segment_contract_chapter_completed(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    chapter_plan: VideoSegmentPlanSchema,
) -> None:
    chapter_scene_count = len(chapter_plan.scenes)
    chapter_segment_count = len(chapter_plan.segments)
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    chapter.status = "completed"
    chapter.scene_count = chapter_scene_count
    chapter.segment_count = chapter_segment_count
    chapter.completed_scene_count = chapter_scene_count
    chapter.running_scene_id = ""
    chapter.finished_at = now
    chapter.failed_scene_id = ""
    chapter.error = ""
    scene_segment_counts = {
        item.scene_id: len(item.segments)
        for item in chapter_plan.scenes
    }
    for scene in chapter.scenes:
        if scene.scene_id in scene_segment_counts:
            scene.status = "completed"
            scene.segment_count = scene_segment_counts[scene.scene_id]
            scene.finished_at = scene.finished_at or now
            scene.error = ""
    _refresh_segment_contract_progress(progress)
    progress.last_error = ""
    progress.resume_ready = progress.completed_chapters < progress.total_chapters
    progress.last_updated_at = now


def _mark_segment_contract_scene_completed(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    scene_id: str,
    scene_plan: VideoSegmentPlanSchema,
) -> None:
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    scene.status = "completed"
    scene.segment_count = len(scene_plan.segments)
    scene.finished_at = now
    scene.running_chunk_id = ""
    scene.failed_chunk_id = ""
    scene.error = ""
    for chunk in scene.chunks:
        chunk.status = "completed"
        chunk.finished_at = chunk.finished_at or now
        chunk.error = ""
    chapter.status = "running"
    chapter.running_scene_id = ""
    chapter.failed_scene_id = ""
    chapter.error = ""
    _refresh_segment_contract_progress(progress)
    progress.status = "running"
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = now


def _mark_segment_contract_scene_failed(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    scene_id: str,
    error: Exception,
) -> None:
    failure_scene_id = scene_id.strip() or str(getattr(error, "scene_id", "") or "")
    metadata = getattr(error, "metadata", None)
    failure_chunk_id = str(getattr(error, "chunk_id", "") or "")
    if not failure_scene_id and isinstance(metadata, dict):
        failure_scene_id = str(metadata.get("scene_id", "") or "")
    if not failure_chunk_id and isinstance(metadata, dict):
        failure_chunk_id = str(metadata.get("chunk_id", "") or "")
    normalized_error = " ".join(str(error).split()).strip()
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    if failure_scene_id:
        scene = _require_segment_contract_scene(
            progress,
            chapter_number=chapter_number,
            scene_id=failure_scene_id,
        )
        scene.status = "failed"
        scene.finished_at = now
        scene.running_chunk_id = ""
        scene.failed_chunk_id = failure_chunk_id
        scene.error = normalized_error
        if failure_chunk_id:
            chunk = _require_segment_contract_chunk(
                progress,
                chapter_number=chapter_number,
                scene_id=failure_scene_id,
                chunk_id=failure_chunk_id,
            )
            chunk.status = "failed"
            chunk.finished_at = now
            chunk.error = normalized_error
    chapter.status = "failed"
    chapter.running_scene_id = ""
    chapter.finished_at = now
    chapter.failed_scene_id = failure_scene_id
    chapter.error = normalized_error
    _refresh_segment_contract_progress(progress)
    progress.status = "failed"
    progress.failed_chapter_number = chapter_number
    progress.failed_scene_id = failure_scene_id
    progress.failed_chunk_id = failure_chunk_id
    progress.last_error = normalized_error
    progress.resume_ready = True
    progress.last_updated_at = now


def _mark_segment_contract_chunk_running(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    scene_id: str,
    chunk_id: str,
) -> None:
    now = _utc_now()
    chapter = _require_segment_contract_chapter(progress, chapter_number)
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    chunk = _require_segment_contract_chunk(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
        chunk_id=chunk_id,
    )
    progress.status = "running"
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = now
    chapter.status = "running"
    chapter.running_scene_id = scene_id
    chapter.failed_scene_id = ""
    chapter.error = ""
    scene.status = "running"
    scene.running_chunk_id = chunk_id
    scene.failed_chunk_id = ""
    scene.error = ""
    chunk.status = "running"
    chunk.started_at = chunk.started_at or now
    chunk.finished_at = None
    chunk.error = ""
    _refresh_segment_contract_progress(progress)
    progress.running_chapter_number = chapter_number
    progress.running_scene_id = scene_id
    progress.running_chunk_id = chunk_id


def _mark_segment_contract_chunk_completed(
    *,
    progress: SegmentContractProgress,
    chapter_number: int,
    scene_id: str,
    chunk_id: str,
    chunk_segment_count: int,
    scene_plan: VideoSegmentPlanSchema,
) -> None:
    now = _utc_now()
    scene = _require_segment_contract_scene(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
    )
    chunk = _require_segment_contract_chunk(
        progress,
        chapter_number=chapter_number,
        scene_id=scene_id,
        chunk_id=chunk_id,
    )
    chunk.status = "completed"
    chunk.segment_count = chunk_segment_count
    chunk.finished_at = now
    chunk.error = ""
    scene.segment_count = len(scene_plan.segments)
    scene.running_chunk_id = ""
    scene.failed_chunk_id = ""
    scene.error = ""
    _refresh_segment_contract_progress(progress)
    progress.status = "running"
    progress.last_error = ""
    progress.resume_ready = False
    progress.last_updated_at = now


def _write_segment_contract_checkpoint(
    *,
    service: NovelToVideoService,
    novel_package: NovelPackage,
    visual_bible: CharacterVisualBibleSchema,
    story_memory: StoryMemoryPackage,
    chapter_plans: list[VideoSegmentPlanSchema],
    paths: VideoPlanningPaths,
    progress: SegmentContractProgress,
    write_continuity: bool = False,
    config: AppConfig | None = None,
    continuity_review_mode: str = "auto",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> VideoPlanningArtifacts:
    merged_plan = service._merge_chapter_segment_plans(chapter_plans)
    expected_chapter_numbers = {
        item.scenes[0].chapter_number
        for item in chapter_plans
        if item.scenes
    }
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
        expected_chapter_numbers=expected_chapter_numbers or None,
    )
    checkpoint_story_memory = service._sync_story_memory_with_plan(
        StoryMemoryPackage.from_dict(to_jsonable(story_memory)),
        novel_package=novel_package,
        plan=merged_plan,
    )

    character_profiles = service._build_character_profiles(visual_bible)
    profile_map = {item.name: item for item in character_profiles}
    voice_map = service._build_voice_map(novel_package)
    character_images = service._build_character_image_tasks(character_profiles, str(paths.output_dir))
    scenes = service._build_runtime_scenes(merged_plan, str(paths.output_dir))
    segments = service._build_runtime_segments(merged_plan, voice_map)
    scene_images = service._build_scene_image_tasks(
        scenes,
        segments,
        character_images,
        profile_map,
        str(paths.output_dir),
    )
    manifest = service._build_seedance_manifest(
        novel_package.outline.title,
        segments,
        scene_images,
        str(paths.output_dir),
    )

    write_json(paths.story_memory_path, checkpoint_story_memory)
    write_json(paths.character_bible_path, character_profiles)
    write_json(paths.character_images_path, character_images)
    write_json(paths.scene_plan_path, {"scenes": scenes})
    write_json(paths.segment_plan_path, segments)
    write_json(paths.segment_contract_progress_path, progress)
    write_json(paths.scene_images_path, scene_images)
    write_json(paths.manifest_path, manifest)
    if write_continuity:
        if config is None:
            raise ValueError("config is required when write_continuity=True.")
        write_continuity_report(
            paths.output_dir,
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
        story_memory=checkpoint_story_memory,
        workflow_trace={},
    )
    return VideoPlanningArtifacts(
        output_dir=paths.output_dir,
        story_memory_path=paths.story_memory_path,
        character_bible_path=paths.character_bible_path,
        character_images_path=paths.character_images_path,
        scene_plan_path=paths.scene_plan_path,
        segment_plan_path=paths.segment_plan_path,
        segment_contract_progress_path=paths.segment_contract_progress_path,
        scene_images_path=paths.scene_images_path,
        manifest_path=paths.manifest_path,
        project_package=project_package,
        manifest=manifest,
        segment_contract_progress=progress,
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
        segment_contract_progress_path=paths.segment_contract_progress_path,
        scene_images_path=paths.scene_images_path,
        manifest_path=paths.manifest_path,
        project_package=project_package,
        manifest=project_package.seedance_manifest,
        segment_contract_progress=load_segment_contract_progress(output_dir),
    )


def resolve_video_planning_paths(output_dir: Path) -> VideoPlanningPaths:
    return VideoPlanningPaths(
        output_dir=output_dir,
        story_memory_path=output_dir / "story_memory.json",
        character_bible_path=output_dir / "character_visual_bible.json",
        character_images_path=output_dir / "character_image_manifest.json",
        scene_plan_path=output_dir / "scene_plan.json",
        segment_plan_path=output_dir / "segment_plan.json",
        segment_contract_progress_path=output_dir / "segment_contract_progress.json",
        scene_images_path=output_dir / "scene_image_manifest.json",
        manifest_path=output_dir / "seedance_manifest.json",
    )


def load_video_segment_plan(output_dir: Path) -> VideoSegmentPlanSchema:
    paths = resolve_video_planning_paths(output_dir)
    return _load_scene_plan(paths.scene_plan_path, paths.segment_plan_path)


def _scene_structure_snapshot_path(output_dir: Path) -> Path:
    return output_dir / "scene_structure_source.json"


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


def load_segment_contract_progress(output_dir: Path) -> SegmentContractProgress | None:
    progress_path = resolve_video_planning_paths(output_dir).segment_contract_progress_path
    if not progress_path.exists():
        return None
    raw_payload = read_json(progress_path)
    if not isinstance(raw_payload, dict):
        return None
    return SegmentContractProgress.from_dict(raw_payload)


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
            covered_event_ids=list(scene.covered_event_ids),
            segments=[],
            scene_bible=scene.scene_bible.model_copy(deep=True),
        )
        for scene in scenes
    ]
    return service._prepare_scene_master_frames(runtime_scenes, str(output_dir))


def _load_scene_structure_artifacts(output_dir: Path) -> VideoSceneStructureArtifacts:
    paths = resolve_video_planning_paths(output_dir)
    scene_structure_snapshot_path = _scene_structure_snapshot_path(output_dir)
    scene_structure_source_path = (
        scene_structure_snapshot_path
        if scene_structure_snapshot_path.exists()
        else paths.scene_plan_path
    )
    required_paths = {
        "story_memory.json": paths.story_memory_path,
        "character_visual_bible.json": paths.character_bible_path,
        "scene_plan.json": scene_structure_source_path,
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
        scene_plan=_load_scene_plan(scene_structure_source_path, paths.segment_plan_path),
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
                "covered_event_ids": list(scene.covered_event_ids),
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
        output_dir / "segment_contract_progress.json",
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
