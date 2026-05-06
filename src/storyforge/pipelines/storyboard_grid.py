from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from urllib.parse import quote

from storyforge.core.config import AppConfig
from storyforge.core.io import read_json, write_json
from storyforge.domains.video.contracts import (
    SeedanceClipTask,
    SeedanceManifest,
    StoryboardGridTask,
    VideoSegment,
)
from storyforge.integrations.gpt_image import GPTImageClient
from storyforge.integrations.seedream import SeedreamClient
from storyforge.pipelines.video_models import StoryboardGridPipelineResult
from storyforge.pipelines.video_planning import load_video_planning_artifacts
from storyforge.pipelines.video_reference_sync import (
    resolve_selected_segment_ids,
    sync_seedance_tail_frame_handoffs,
    sync_v2_seedance_references,
)


TIMED_BEAT_PATTERN = re.compile(
    r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒[：:，,\s]*(?P<body>.*)"
)
GRID_VIDEO_MODE = "grid_storyboard"
DIRECT_VIDEO_MODE = "direct_motion"
GRID_CELL_COUNT = 9
GRID_CELL_PROGRESSIONS = [
    "建立开场构图和角色初始站位，画面必须和后续格子有清晰区别。",
    "动作开始，角色重心、视线或手部位置发生可见变化。",
    "角色移动或镜头推进到下一状态，空间关系比上一格更明确。",
    "动作继续发展，角色距离、朝向或姿态必须不同于前三格。",
    "进入片段中点，情绪或互动关系出现明显转折。",
    "延续中点动作，镜头角度、景别或角色位置继续变化。",
    "进入收束前状态，动作幅度减小但站位和画面信息继续推进。",
    "接近最终状态，角色表情、手势或视线完成关键变化。",
    "最终收束画面，停在本段结尾状态，不要和第一格或中间格重复。",
]
GRID_CELL_VISUAL_DIRECTIVES = [
    "远景或中远景建立空间，人物完整入画，明确起点位置。",
    "中远景保持同一方向，角色重心、脚步或手部动作已经开始变化。",
    "中景推进到下一状态，人物距离、朝向或屏幕位置必须比上一格更靠近目标。",
    "关系中景，强化角色之间的空间距离和视线方向。",
    "中近景或关系镜头，呈现本段中点的情绪转折或互动变化。",
    "换到互补角度或更近景别，但保持同一空间锚点和屏幕方向。",
    "收束前中景，动作幅度减小但角色站位继续推进。",
    "近景或半身关系镜头，突出关键表情、手势或视线完成变化。",
    "最终定格式构图，明确停在本段结尾状态，不能回到第一格构图。",
]
GRID_CELL_PHASES = [
    "起始关键帧",
    "推进关键帧",
    "结果关键帧",
]
TAIL_HANDOFF_PREFIX_PATTERNS = (
    re.compile(r"^开场先严格承接上一\s*(?:段|场|chunk|个\s*chunk)尾部[：:，,、\s]*"),
    re.compile(r"^承接上一\s*(?:段|场|chunk|个\s*chunk)尾部[：:，,、\s]*"),
    re.compile(r"^承接上一\s*(?:段|场|chunk|个\s*chunk)[：:，,、\s]*"),
)


def run_storyboard_grid_pipeline(
    *,
    config: AppConfig,
    project_root: Path,
    output_root: Path | None = None,
    segment_id: str | None = None,
    scene_id: str | None = None,
    image_model: str | None = None,
    image_size: str | None = None,
    aspect_ratio: str | None = None,
    seedream_watermark: bool | None = None,
) -> StoryboardGridPipelineResult:
    output_dir = output_root or (project_root / config.paths.output_dir)
    planning = load_video_planning_artifacts(output_dir)
    manifest = planning.manifest
    sync_v2_seedance_references(manifest, planning.project_package)
    sync_seedance_tail_frame_handoffs(manifest, planning.project_package.scenes)

    selected_segment_ids = resolve_selected_segment_ids(
        planning.project_package,
        segment_id=segment_id,
        scene_id=scene_id,
    )
    clips = _select_manifest_clips(manifest, selected_segment_ids)
    segment_map = {segment.segment_id: segment for segment in planning.project_package.segments}
    resolved_model = _resolve_storyboard_image_model(config, image_model)
    resolved_size = _resolve_storyboard_size(image_size, resolved_model, config)
    resolved_ratio = _resolve_storyboard_aspect_ratio(aspect_ratio)
    storyboard_manifest_path = planning.storyboard_manifest_path
    existing_tasks = _load_storyboard_grid_tasks(storyboard_manifest_path)
    existing_by_segment = {item.segment_id: item for item in existing_tasks}
    generated_by_segment: dict[str, StoryboardGridTask] = {}

    generated_count = 0
    failed_count = 0
    for clip in clips:
        segment = segment_map.get(clip.segment_id)
        if segment is None:
            failed_count += 1
            generated_by_segment[clip.segment_id] = StoryboardGridTask(
                segment_id=clip.segment_id,
                scene_id=clip.scene_id,
                title=clip.title,
                prompt="",
                output_path="",
                model=resolved_model,
                size=resolved_size,
                aspect_ratio=resolved_ratio,
                status="failed",
                error=f"Segment {clip.segment_id} not found in segment_plan.json.",
            )
            continue
        task = _build_storyboard_grid_task(
            config=config,
            project_root=project_root,
            output_dir=output_dir,
            clip=clip,
            segment=segment,
            image_model=resolved_model,
            image_size=resolved_size,
            aspect_ratio=resolved_ratio,
        )
        task.status = "running"
        generated_by_segment[clip.segment_id] = task
        clip.video_mode = GRID_VIDEO_MODE
        clip.storyboard_grid_prompt = task.prompt
        clip.storyboard_grid_status = task.status
        clip.storyboard_grid_error = ""
        clip.storyboard_grid_request_info = {
            "reference_bindings": task.reference_bindings,
            "storyboard_scene_descriptions": task.scene_descriptions,
        }
        _write_storyboard_progress(
            manifest=manifest,
            manifest_path=planning.manifest_path,
            storyboard_manifest_path=storyboard_manifest_path,
            existing_by_segment=existing_by_segment,
            generated_by_segment=generated_by_segment,
        )
        try:
            result = _generate_storyboard_grid_image(
                config=config,
                project_root=project_root,
                task=task,
                seedream_watermark=seedream_watermark,
            )
            task.generated_url = result["generated_url"]
            task.request_info = result["request_info"]
            task.status = "completed"
            task.error = ""
            generated_count += 1
            _apply_storyboard_grid_to_clip(clip, task, segment)
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            _mark_clip_storyboard_failed(clip, task)
            failed_count += 1

    storyboard_tasks = _merge_storyboard_tasks(
        manifest=manifest,
        existing_by_segment=existing_by_segment,
        generated_by_segment=generated_by_segment,
    )
    write_json(storyboard_manifest_path, storyboard_tasks)
    write_json(planning.manifest_path, manifest)

    note = "九宫格分镜图已生成。"
    if failed_count:
        note = "九宫格分镜图生成完成，但存在失败片段。"
    return StoryboardGridPipelineResult(
        output_dir=planning.output_dir,
        character_bible_path=planning.character_bible_path,
        character_images_path=planning.character_images_path,
        scene_plan_path=planning.scene_plan_path,
        segment_plan_path=planning.segment_plan_path,
        scene_images_path=planning.scene_images_path,
        manifest_path=planning.manifest_path,
        storyboard_manifest_path=storyboard_manifest_path,
        project_package=planning.project_package,
        manifest=manifest,
        storyboard_tasks=storyboard_tasks,
        generated_count=generated_count,
        failed_count=failed_count,
        note=note,
    )


def _select_manifest_clips(
    manifest: SeedanceManifest,
    selected_segment_ids: set[str] | None,
) -> list[SeedanceClipTask]:
    if not selected_segment_ids:
        return list(manifest.clips)
    clips = [clip for clip in manifest.clips if clip.segment_id in selected_segment_ids]
    missing = sorted(selected_segment_ids - {clip.segment_id for clip in clips})
    if missing:
        raise ValueError(
            "Requested storyboard segments are not present in seedance_manifest.json: "
            + ", ".join(missing)
        )
    return clips


def _build_storyboard_grid_task(
    *,
    config: AppConfig,
    project_root: Path,
    output_dir: Path,
    clip: SeedanceClipTask,
    segment: VideoSegment,
    image_model: str,
    image_size: str,
    aspect_ratio: str,
) -> StoryboardGridTask:
    reference_bindings = _build_storyboard_reference_bindings(clip)
    reference_images = [item["url"] for item in reference_bindings if item.get("url")]
    if not clip.scene_master_url:
        raise ValueError(f"{clip.segment_id} 缺少场景母图，不能生成九宫格分镜图。")
    missing_character_count = _missing_character_reference_count(clip)
    if missing_character_count > 0:
        raise ValueError(f"{clip.segment_id} 缺少 {missing_character_count} 个角色图，不能生成九宫格分镜图。")
    scene_descriptions = build_storyboard_scene_descriptions(segment)
    prompt = build_storyboard_grid_prompt(
        segment=segment,
        scene_descriptions=scene_descriptions,
        reference_bindings=reference_bindings,
        uses_previous_last_frame=False,
        aspect_ratio=aspect_ratio,
    )
    output_path = (
        output_dir
        / "assets"
        / "storyboards"
        / f"{segment.segment_id}_grid.{_storyboard_output_suffix(image_model, config)}"
    )
    return StoryboardGridTask(
        segment_id=segment.segment_id,
        scene_id=segment.scene_id,
        title=segment.title,
        prompt=prompt,
        output_path=str(output_path),
        model=image_model,
        size=image_size,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
        reference_bindings=reference_bindings,
        scene_descriptions=scene_descriptions,
        uses_previous_last_frame=False,
        previous_last_frame_url=clip.first_frame_url,
    )


def _build_storyboard_reference_bindings(clip: SeedanceClipTask) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    if clip.scene_master_url:
        bindings.append(
            {
                "label": "图片1",
                "kind": "scene_master",
                "description": "当前 scene 的场景母图，用于锁定地点、空间、光线、背景锚点和固定道具。",
                "url": clip.scene_master_url,
            }
        )
    for index, url in enumerate(clip.character_image_urls, start=1):
        character_name = ""
        if index <= len(clip.visible_characters):
            character_name = str(clip.visible_characters[index - 1]).strip()
        bindings.append(
            {
                "label": f"图片{len(bindings) + 1}",
                "kind": "character",
                "description": (
                    f"{character_name} 的角色定妆图，用于锁定脸、发型、服装、体型和年龄感。"
                    if character_name
                    else "角色定妆图，用于锁定脸、发型、服装、体型和年龄感。"
                ),
                "url": url,
            }
        )
    return bindings


def build_storyboard_scene_descriptions(segment: VideoSegment) -> list[str]:
    parsed_beats = _parse_timed_beats(segment)
    fallback_body = _normalize_storyboard_beat_body(segment.summary.strip() or segment.title.strip())
    duration = max(float(segment.duration_seconds or 0), 1.0)
    descriptions: list[str] = []
    for cell_index in range(1, GRID_CELL_COUNT + 1):
        start_seconds = duration * (cell_index - 1) / GRID_CELL_COUNT
        end_seconds = duration * cell_index / GRID_CELL_COUNT
        midpoint = (start_seconds + end_seconds) / 2
        beat_body, beat_progress = _resolve_cell_beat(
            parsed_beats,
            midpoint=midpoint,
            fallback=fallback_body,
        )
        phase = _cell_phase_label(beat_progress)
        visual_directive = GRID_CELL_VISUAL_DIRECTIVES[cell_index - 1]
        progression = GRID_CELL_PROGRESSIONS[cell_index - 1]
        descriptions.append(
            f"格{cell_index} ({_format_seconds(start_seconds)}-{_format_seconds(end_seconds)}秒): "
            f"{phase}：{beat_body}；本格画面要求：{visual_directive}；画面演进：{progression}"
        )
    dialogue = "；".join(str(line).strip() for line in segment.dialogue_lines if str(line).strip())
    if dialogue:
        descriptions[-1] = f"{descriptions[-1]}；对白：{dialogue}"
    return descriptions


def _parse_timed_beats(segment: VideoSegment) -> list[tuple[float, float, str]]:
    parsed: list[tuple[float, float, str]] = []
    raw_beats = [str(item or "").strip() for item in segment.timed_beats or [] if str(item or "").strip()]
    for index, beat in enumerate(raw_beats, start=1):
        match = TIMED_BEAT_PATTERN.search(beat)
        if match is not None:
            start = float(match.group("start"))
            end = float(match.group("end"))
            body = str(match.group("body") or "").strip(" ：:，,") or beat
        else:
            fallback_start, fallback_end = _fallback_beat_range(index, len(raw_beats), segment.duration_seconds)
            start = float(fallback_start)
            end = float(fallback_end)
            body = beat
        if end <= start:
            end = start + 0.1
        parsed.append((start, end, _normalize_storyboard_beat_body(body)))
    return parsed


def _resolve_cell_beat(
    parsed_beats: list[tuple[float, float, str]],
    *,
    midpoint: float,
    fallback: str,
) -> tuple[str, float]:
    if not parsed_beats:
        return fallback, 0
    for start, end, body in parsed_beats:
        if start <= midpoint <= end:
            return body, _beat_progress(start, end, midpoint)
    nearest = min(
        parsed_beats,
        key=lambda item: min(abs(midpoint - item[0]), abs(midpoint - item[1])),
    )
    return nearest[2], _beat_progress(nearest[0], nearest[1], midpoint)


def _beat_progress(start: float, end: float, midpoint: float) -> float:
    if end <= start:
        return 0
    return max(0, min(1, (midpoint - start) / (end - start)))


def _cell_phase_label(progress: float) -> str:
    if progress < 0.34:
        return GRID_CELL_PHASES[0]
    if progress < 0.67:
        return GRID_CELL_PHASES[1]
    return GRID_CELL_PHASES[2]


def _normalize_storyboard_beat_body(body: str) -> str:
    normalized = str(body or "").strip(" ：:，,、\n\t ")
    for pattern in TAIL_HANDOFF_PREFIX_PATTERNS:
        normalized = pattern.sub("当前片段开场状态：", normalized).strip()
    normalized = normalized.replace("承接上一场尾部，", "当前片段开场状态：")
    normalized = normalized.replace("承接上一段尾部，", "当前片段开场状态：")
    normalized = normalized.replace("承接上一 chunk 尾部，", "当前片段开场状态：")
    normalized = normalized.replace("承接上一chunk尾部，", "当前片段开场状态：")
    return normalized.strip(" ：:，,、\n\t ") or "当前片段动作继续推进"


def _storyboard_continuity_hints(segment: VideoSegment) -> list[str]:
    hints: list[str] = []
    shot_state = segment.shot_state
    motion_plan = segment.motion_plan
    for label, value in (
        ("站位", getattr(shot_state, "blocking", "")),
        ("镜头", getattr(shot_state, "camera_motion", "")),
        ("动作推进", getattr(shot_state, "action_progression", "")),
        ("收束状态", getattr(shot_state, "end_state_lock", "")),
        ("角色运动", getattr(motion_plan, "character_motion", "")),
        ("镜头路径", getattr(motion_plan, "camera_path", "")),
    ):
        text = str(value or "").strip()
        if text:
            hints.append(f"{label}：{text}")
        if len(hints) >= 4:
            break
    return hints


def build_storyboard_grid_prompt(
    *,
    segment: VideoSegment,
    scene_descriptions: list[str],
    reference_bindings: list[dict[str, str]],
    uses_previous_last_frame: bool,
    aspect_ratio: str = "16:9",
) -> str:
    resolved_aspect_ratio = str(aspect_ratio or "16:9").strip() or "16:9"
    lines = [
        "原创虚构剧情短视频九宫格分镜图，风格化概念插画，非真人摄影。",
        "",
        f"画面规格：{resolved_aspect_ratio}，一张图内固定 3x3 九宫格，九个画面从左到右、从上到下表示同一个视频片段的连续动作推进。",
        "九宫格只表现画面，不要出现字幕、编号、说明文字、水印、Logo、时间码或信息排版。",
        "同一角色在九宫格中必须保持同一张脸、同一发型、同一服装、同一体型和年龄感；不要复制出额外角色或相似替身。",
        "九个格子必须是九个不同的连续状态，不允许多个格子使用几乎相同的站位、表情、景别或构图。",
        "",
        "参考图绑定：",
    ]
    for binding in reference_bindings:
        lines.append(f"- {binding['label']}：{binding['description']}")
    lines.extend(
        [
            "",
            "九宫格绘制规则：",
            "- 场景母图用于统一地点、光线、空间透视、背景锚点和固定道具。",
            "- 角色定妆图只用于统一人物身份和造型，不要把白底三视图版式画进九宫格。",
            "- 不要参考上一段视频尾帧绘制九宫格；上一段尾帧只会在后续 Seedance 视频生成阶段作为单独参考图提交。",
        ]
    )
    if uses_previous_last_frame:
        lines.append("- 本次九宫格不直接绘制上一段尾帧，但第一格应建立当前片段自身的开场状态。")
    else:
        lines.append("- 第一格直接建立当前片段开场状态，后续格子保持连续运动，不要跳切换景。")
    lines.extend(
        [
            "",
            "视频片段内容：",
            f"片段：{segment.title}",
            f"摘要：{segment.summary}",
        ]
    )
    continuity_hints = _storyboard_continuity_hints(segment)
    if continuity_hints:
        lines.extend(["动作与镜头连续性参考：", *[f"- {hint}" for hint in continuity_hints]])
    lines.extend(
        [
            "九格分镜节拍：",
        ]
    )
    lines.extend(f"- {description}" for description in scene_descriptions)
    lines.extend(
        [
            "",
            "输出要求：九格之间必须像同一个镜头或同一组连续镜头的关键帧推进，保持场景、人物、道具和屏幕方向一致；每一格都必须有可见的动作、站位、距离、景别或视线差异，禁止九格重复、静止或只换极小表情。",
            "如果相邻格使用同一段动作，必须把它拆成起始、推进、结果三个不同关键帧，不得画成同一张图的近似复制。",
        ]
    )
    return "\n".join(lines)


def build_grid_seedance_prompt(
    *,
    clip: SeedanceClipTask,
    segment: VideoSegment,
    scene_descriptions: list[str],
) -> str:
    lines = [
        f"请根据图片1的九宫格分镜图生成中文剧情短视频片段，时长 {clip.duration_seconds} 秒。",
        "图片1已经给出完整画面分镜：从左到右、从上到下依次对应本段动作推进。",
    ]
    if clip.first_frame_url:
        lines.append("如果提交阶段绑定了上一段视频尾帧，开头先对齐尾帧的构图、角色站位、朝向、动作停点和光线状态，再按图片1九宫格推进。")
    lines.extend([
        "画面推进：按九宫格的空间、人物、道具、光线和动作顺序连续生成，镜头运动自然流畅，不要跳切、换脸、换服装或改变场景锚点。",
        "九格时间分配：",
    ])
    lines.extend(scene_descriptions)
    lines.extend(
        [
            "结尾状态必须自然停在最后一个分镜格所表达的动作收束点。",
            "若场景描述中包含对白，只让对应角色在该场景时间内自然说出。",
        ]
    )
    return "\n".join(lines)


def _generate_storyboard_grid_image(
    *,
    config: AppConfig,
    project_root: Path,
    task: StoryboardGridTask,
    seedream_watermark: bool | None,
) -> dict[str, object]:
    output_path = Path(task.output_path)
    if task.model == config.gpt_image.model:
        image_result = GPTImageClient(config.gpt_image).generate_single_image(
            mode="image_to_image",
            prompt=task.prompt,
            reference_images=task.reference_images,
            aspect_ratio=task.aspect_ratio,
            output_size=task.size,
            output_path=output_path,
        )
        generated_url = image_result.image_url or _build_output_file_url(config, project_root, output_path)
        return {
            "generated_url": generated_url,
            "request_info": {
                **image_result.request_info,
                "reference_bindings": task.reference_bindings,
                "storyboard_scene_descriptions": task.scene_descriptions,
            },
        }

    seedream_config = replace(
        config.seedream,
        image_size=task.size,
        watermark=config.seedream.watermark if seedream_watermark is None else bool(seedream_watermark),
    )
    image_result = SeedreamClient(seedream_config).generate_single_image(
        prompt=task.prompt,
        reference_images=task.reference_images,
        aspect_ratio=task.aspect_ratio,
        output_path=output_path,
        force_submit=True,
    )
    generated_url = image_result.image_url or _build_output_file_url(config, project_root, output_path)
    return {
        "generated_url": generated_url,
        "request_info": {
            **image_result.request_info,
            "reference_bindings": task.reference_bindings,
            "storyboard_scene_descriptions": task.scene_descriptions,
        },
    }


def _apply_storyboard_grid_to_clip(
    clip: SeedanceClipTask,
    task: StoryboardGridTask,
    segment: VideoSegment,
) -> None:
    clip.video_mode = GRID_VIDEO_MODE
    clip.storyboard_grid_path = task.output_path
    clip.storyboard_grid_url = task.generated_url
    clip.storyboard_grid_prompt = task.prompt
    clip.storyboard_grid_status = "completed"
    clip.storyboard_grid_error = ""
    clip.storyboard_grid_request_info = task.request_info
    clip.storyboard_scene_descriptions = list(task.scene_descriptions)
    clip.prompt = build_grid_seedance_prompt(
        clip=clip,
        segment=segment,
        scene_descriptions=task.scene_descriptions,
    )
    _reset_clip_video_output(clip)


def _mark_clip_storyboard_failed(clip: SeedanceClipTask, task: StoryboardGridTask) -> None:
    clip.video_mode = GRID_VIDEO_MODE
    clip.storyboard_grid_status = "failed"
    clip.storyboard_grid_error = task.error
    clip.storyboard_grid_prompt = task.prompt
    clip.storyboard_scene_descriptions = list(task.scene_descriptions)
    clip.storyboard_grid_request_info = task.request_info
    _reset_clip_video_output(clip)


def _reset_clip_video_output(clip: SeedanceClipTask) -> None:
    for raw_path in (clip.downloaded_path, clip.output_path):
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.exists() and path.is_file():
            path.unlink()
    clip.submitted_prompt = ""
    clip.submit_variant = ""
    clip.submitted_reference_bindings = []
    clip.submitted_request_info = {}
    clip.remote_task_id = ""
    clip.submit_status = "planned"
    clip.remote_status = "planned"
    clip.video_url = ""
    clip.cover_url = ""
    clip.last_frame_url = ""
    clip.last_frame_path = ""
    clip.downloaded_path = ""
    clip.error = ""


def _merge_storyboard_tasks(
    *,
    manifest: SeedanceManifest,
    existing_by_segment: dict[str, StoryboardGridTask],
    generated_by_segment: dict[str, StoryboardGridTask],
) -> list[StoryboardGridTask]:
    merged: list[StoryboardGridTask] = []
    for clip in manifest.clips:
        task = generated_by_segment.get(clip.segment_id) or existing_by_segment.get(clip.segment_id)
        if task is not None:
            merged.append(task)
    for segment_id, task in existing_by_segment.items():
        if segment_id not in {clip.segment_id for clip in manifest.clips}:
            merged.append(task)
    return merged


def _write_storyboard_progress(
    *,
    manifest: SeedanceManifest,
    manifest_path: Path,
    storyboard_manifest_path: Path,
    existing_by_segment: dict[str, StoryboardGridTask],
    generated_by_segment: dict[str, StoryboardGridTask],
) -> None:
    storyboard_tasks = _merge_storyboard_tasks(
        manifest=manifest,
        existing_by_segment=existing_by_segment,
        generated_by_segment=generated_by_segment,
    )
    write_json(storyboard_manifest_path, storyboard_tasks)
    write_json(manifest_path, manifest)


def _load_storyboard_grid_tasks(path: Path) -> list[StoryboardGridTask]:
    if not path.exists():
        return []
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    return [StoryboardGridTask.from_dict(item) for item in payload if isinstance(item, dict)]


def _missing_character_reference_count(clip: SeedanceClipTask) -> int:
    expected_count = len([name for name in clip.visible_characters if str(name).strip()])
    actual_count = len([url for url in clip.character_image_urls if str(url).strip()])
    return max(0, expected_count - actual_count)


def _resolve_storyboard_image_model(config: AppConfig, raw_model: str | None) -> str:
    model = str(raw_model or "").strip()
    if not model:
        return config.seedream.model
    if model in {"gpt-image-2", config.gpt_image.model}:
        return config.gpt_image.model
    if model in {"seedream", "seedream-4.5", config.seedream.model}:
        return config.seedream.model
    raise ValueError(f"九宫格生图模型只支持 {config.gpt_image.model} 或 {config.seedream.model}。")


def _resolve_storyboard_size(raw_size: str | None, model: str, config: AppConfig) -> str:
    size = str(raw_size or "").strip().upper()
    if size:
        return size
    if model == config.gpt_image.model:
        return "2K"
    return str(config.seedream.image_size or "2K").strip() or "2K"


def _resolve_storyboard_aspect_ratio(raw_aspect_ratio: str | None) -> str:
    return str(raw_aspect_ratio or "").strip() or "16:9"


def _storyboard_output_suffix(model: str, config: AppConfig) -> str:
    if model == config.gpt_image.model:
        suffix = str(config.gpt_image.output_format or "").strip().lower()
        if suffix in {"jpg", "jpeg", "png", "webp"}:
            return "jpg" if suffix == "jpeg" else suffix
    return "png"


def _build_output_file_url(config: AppConfig, project_root: Path, path: Path) -> str:
    if not path.exists():
        return ""
    output_root = (project_root / config.paths.output_dir).resolve()
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(output_root)
    except ValueError:
        return ""
    encoded_path = "/".join(quote(part) for part in relative_path.parts)
    return f"/outputs/{encoded_path}?v={int(resolved_path.stat().st_mtime_ns)}"


def _format_seconds(value: str | float) -> str:
    numeric = round(float(value), 1)
    return str(int(numeric)) if numeric.is_integer() else str(numeric).rstrip("0").rstrip(".")


def _fallback_beat_range(index: int, total: int, duration: int) -> tuple[str, str]:
    count = max(1, total)
    start = round((index - 1) * duration / count, 1)
    end = round(index * duration / count, 1)
    return _format_seconds(str(start)), _format_seconds(str(end))


__all__ = [
    "DIRECT_VIDEO_MODE",
    "GRID_VIDEO_MODE",
    "build_grid_seedance_prompt",
    "build_storyboard_grid_prompt",
    "build_storyboard_scene_descriptions",
    "run_storyboard_grid_pipeline",
]
