from __future__ import annotations

import re
from typing import Callable, TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackend,
    AgentBackendUnavailableError,
    PromptRequest,
    UnavailableAgentBackend,
)
from storyforge.core.io import to_jsonable
from storyforge.core.config import SeedanceConfig
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.errors import VideoStructuredGenerationError
from storyforge.domains.video.contracts import (
    CharacterVisualProfile,
    ContinuityLink,
    SceneBible,
    ShotState,
    VideoProjectPackage,
    VideoScene,
    VideoSegment,
)
from storyforge.domains.video.planning import VideoPlanningMixin
from storyforge.domains.video.prompting import VideoPromptingMixin
from storyforge.domains.video.repair import VideoRepairMixin
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    SegmentContinuityRepairSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)
TIMED_BEAT_PATTERN = re.compile(r"(?P<start>\d+(?:\.\d+)?)\s*[-~到]\s*(?P<end>\d+(?:\.\d+)?)\s*秒")


class NovelToVideoService(
    VideoPromptingMixin,
    VideoRepairMixin,
    VideoPlanningMixin,
):
    PLANNER_MIN_DURATION_SECONDS = 5
    SEEDANCE_MIN_DURATION_SECONDS = 2
    SEEDANCE_MAX_DURATION_SECONDS = 12
    SPEECH_CHARS_PER_SECOND = 3

    def __init__(
        self,
        backend: AgentBackend | None = None,
        segment_duration_seconds: int = 5,
        aspect_ratio: str = "16:9",
        fps: int = 24,
        character_image_provider: str = "prompt-only",
        scene_image_provider: str = "prompt-only",
        seedance_config: SeedanceConfig | None = None,
        structured_retry_attempts: int = 3,
    ) -> None:
        self.backend = backend or UnavailableAgentBackend(
            "NovelToVideoService requires a live LLM backend."
        )
        self.segment_duration_seconds = segment_duration_seconds
        self.aspect_ratio = aspect_ratio
        self.fps = fps
        self.character_image_provider = character_image_provider
        self.scene_image_provider = scene_image_provider
        self.seedance_config = seedance_config or SeedanceConfig()
        self.structured_retry_attempts = max(1, structured_retry_attempts)

    def build_video_project(self, novel_package: NovelPackage, output_dir: str) -> VideoProjectPackage:
        visual_bible = self._run_structured_agent(
            schema=CharacterVisualBibleSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是影视角色视觉设计 Agent。"
                    "请把小说角色转换成稳定、可复用的角色视觉设定。"
                    "输出要偏风格化概念设计，不要写成真人摄影或现实人物描述。"
                ),
                user_prompt=self._build_visual_bible_user_prompt(novel_package),
                metadata={"task": "video-character-bible"},
            ),
            validator=lambda value: self._validate_character_visual_bible_output(
                value,
                novel_package=novel_package,
            ),
        )
        visual_bible = self._repair_character_visual_bible(visual_bible, novel_package)

        segments_plan = self._run_structured_agent(
            schema=VideoSegmentPlanSchema,
            request=PromptRequest(
                system_prompt=(
                    "你是短视频分镜导演 Agent。"
                    "请先按场景拆分，再把每个场景拆成多个能独立成片的视频片段。"
                    "每个片段都要有首尾帧；必要时补充中段锚点帧。"
                    "输出偏镜头分镜和环境调度，避免真人特写描述。"
                ),
                user_prompt=self._build_segment_planner_user_prompt(novel_package),
                metadata={"task": "video-segment-planner"},
            ),
            validator=lambda value: self._validate_segment_plan_output(
                value,
                novel_package=novel_package,
            ),
        )
        segments_plan = self._repair_segment_plan(segments_plan, novel_package, visual_bible)
        segments_plan = self._normalize_segment_characters(segments_plan, novel_package, visual_bible)
        segments_plan = self._repair_scene_bibles(segments_plan, novel_package)
        segments_plan = self._repair_shot_states(segments_plan, novel_package)
        segments_plan = self._normalize_segments_for_seedance(segments_plan)
        segments_plan = self._repair_scene_bibles(segments_plan, novel_package)
        segments_plan = self._repair_shot_states(segments_plan, novel_package)
        segments_plan = self._repair_continuity_links(segments_plan)

        character_profiles = self._build_character_profiles(visual_bible)
        profile_map = {item.name: item for item in character_profiles}
        voice_map = self._build_voice_map(novel_package)
        character_images = self._build_character_image_tasks(character_profiles, output_dir)
        scenes = self._build_runtime_scenes(segments_plan, output_dir)
        segments = self._build_runtime_segments(segments_plan, voice_map)
        scene_images = self._build_scene_image_tasks(
            scenes,
            segments,
            character_images,
            profile_map,
            output_dir,
        )
        manifest = self._build_seedance_manifest(
            novel_package.outline.title,
            segments,
            scene_images,
            output_dir,
        )

        return VideoProjectPackage(
            title=novel_package.outline.title,
            character_profiles=character_profiles,
            character_images=character_images,
            scenes=scenes,
            segments=segments,
            scene_images=scene_images,
            seedance_manifest=manifest,
            workflow_trace={
                "character_visual_bible": visual_bible.model_dump(),
                "scene_plan": segments_plan.model_dump(),
                "segment_plan": [
                    item.model_dump()
                    for item in segments_plan.segments
                ],
            },
        )

    def _build_character_profiles(
        self,
        visual_bible: CharacterVisualBibleSchema,
    ) -> list[CharacterVisualProfile]:
        return [
            CharacterVisualProfile(
                name=item.name,
                role=item.role,
                gender=item.gender,
                appearance=item.appearance,
                outfit=item.outfit,
                color_palette=item.color_palette,
                portrait_prompt=self._build_character_sheet_prompt(
                    name=item.name,
                    role=item.role,
                    gender=item.gender,
                    appearance=item.appearance,
                    outfit=item.outfit,
                    source_prompt=item.portrait_prompt,
                ),
            )
            for item in visual_bible.characters
        ]

    def _build_voice_map(self, novel_package: NovelPackage) -> dict[str, object]:
        return {
            item.name: item.voice_profile
            for item in novel_package.outline.characters
        }

    def _build_runtime_scenes(
        self,
        segments_plan: VideoSegmentPlanSchema,
        output_dir: str,
    ) -> list[VideoScene]:
        scenes = [
            VideoScene.from_dict(item.model_dump())
            for item in segments_plan.scenes
        ]
        return self._prepare_scene_master_frames(scenes, output_dir)

    def _build_runtime_segments(
        self,
        segments_plan: VideoSegmentPlanSchema,
        voice_map: dict[str, object],
    ) -> list[VideoSegment]:
        return [
            VideoSegment(
                segment_id=item.segment_id,
                chapter_number=item.chapter_number,
                scene_id=item.scene_id,
                scene_title=item.scene_title,
                scene_summary=item.scene_summary,
                scene_anchor=item.scene_anchor,
                title=item.title,
                summary=item.summary,
                involved_characters=item.involved_characters,
                start_frame_characters=item.start_frame_characters,
                mid_frame_characters=item.mid_frame_characters,
                end_frame_characters=item.end_frame_characters,
                narration=item.narration,
                dialogue_lines=item.dialogue_lines,
                subtitle_lines=item.subtitle_lines
                or self._build_subtitle_lines(
                    narration=item.narration,
                    dialogue_lines=item.dialogue_lines,
                    timed_beats=item.timed_beats,
                ),
                character_voice_notes=self._build_segment_voice_notes(
                    item.involved_characters,
                    voice_map,
                ),
                sound_effects=item.sound_effects,
                music_direction=item.music_direction,
                timed_beats=item.timed_beats,
                scene_prompt=item.scene_prompt,
                start_frame_prompt=item.start_frame_prompt,
                mid_frame_prompt=item.mid_frame_prompt,
                end_frame_prompt=item.end_frame_prompt,
                duration_seconds=item.duration_seconds,
                requires_mid_frame=item.requires_mid_frame,
                transition_hint=item.transition_hint,
                source_segment_id=item.source_segment_id or item.segment_id,
                subsegment_index=item.subsegment_index,
                subsegment_count=item.subsegment_count,
                reuse_previous_end_frame=item.reuse_previous_end_frame,
                scene_bible=SceneBible.from_dict(item.scene_bible.model_dump()),
                shot_state=ShotState.from_dict(item.shot_state.model_dump()),
                continuity_link=ContinuityLink.from_dict(item.continuity_link.model_dump()),
            )
            for item in segments_plan.segments
        ]

    def repair_segment_continuity(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        segment_id: str,
        continuity_issues: list[dict[str, object]],
    ) -> tuple[VideoSegmentSchema, dict[str, object]]:
        target_index = next(
            (index for index, item in enumerate(project_package.segments) if item.segment_id == segment_id),
            -1,
        )
        if target_index < 0:
            raise ValueError(f"Segment {segment_id} not found in current project package.")

        target_segment = project_package.segments[target_index]
        previous_segment = project_package.segments[target_index - 1] if target_index > 0 else None
        next_segment = (
            project_package.segments[target_index + 1]
            if target_index + 1 < len(project_package.segments)
            else None
        )
        target_scene = next(
            (scene for scene in project_package.scenes if scene.scene_id == target_segment.scene_id),
            None,
        )
        if target_scene is None:
            raise ValueError(f"Scene {target_segment.scene_id} not found for segment {segment_id}.")

        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的 Segment Continuity Repair Agent。"
                "你只修复目标 segment 的连续性规划，不重写剧情，不改章节结构，不新增角色。"
                "你的职责是把当前 segment 修成更适合单段重生成的稳定执行合同。"
            ),
            user_prompt=self._build_segment_continuity_repair_user_prompt(
                story_title=project_package.title,
                character_profiles=project_package.character_profiles,
                scene_payload=to_jsonable(target_scene),
                segment_payload=to_jsonable(target_segment),
                previous_segment_payload=to_jsonable(previous_segment) if previous_segment else None,
                next_segment_payload=to_jsonable(next_segment) if next_segment else None,
                continuity_issues=continuity_issues,
            ),
            metadata={"task": "segment-continuity-repair", "segment_id": segment_id},
        )
        repair_patch = self._run_strict_structured_agent(
            schema=SegmentContinuityRepairSchema,
            request=request,
            validator=lambda candidate: self._validate_segment_continuity_repair(
                candidate,
                target_segment=target_segment,
                previous_segment=previous_segment,
            ),
        )
        repaired_segment = self._materialize_repaired_segment(
            novel_package=novel_package,
            project_package=project_package,
            target_segment=target_segment,
            target_scene=target_scene,
            previous_segment=previous_segment,
            repair_patch=repair_patch,
        )
        repair_report = {
            "segment_id": segment_id,
            "repair_summary": repair_patch.repair_summary.strip(),
            "continuity_issues": continuity_issues,
            "raw_patch": repair_patch.model_dump(),
            "changed_fields": self._collect_segment_changed_fields(target_segment, repaired_segment),
            "before": to_jsonable(target_segment),
            "after": repaired_segment.model_dump(),
        }
        return repaired_segment, repair_report

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT] | None = None,
    ) -> StructuredModelT:
        attempts = self.structured_retry_attempts
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=attempts,
            validator=validator,
            request_builder=self._build_retry_request,
            response_coercer=self._coerce_structured_response,
            failure_builder=lambda last_error: VideoStructuredGenerationError(
                task=str(request.metadata.get("task", "structured-agent")),
                schema_name=schema.__name__,
                attempts=attempts,
                cause=last_error or RuntimeError("unknown structured generation failure"),
            ),
        )

    def _run_strict_structured_agent(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        validator: Callable[[StructuredModelT], StructuredModelT],
        attempts: int = 3,
    ) -> StructuredModelT:
        total_attempts = max(1, attempts)
        task_name = str(request.metadata.get("task", "structured-repair"))
        return self._execute_structured_request(
            schema=schema,
            request=request,
            attempts=total_attempts,
            validator=validator,
            request_builder=self._build_repair_retry_request,
            response_coercer=self._validate_structured_response,
            failure_builder=lambda last_error: RuntimeError(
                f"Structured repair failed for task={task_name} schema={schema.__name__} "
                f"after {total_attempts} attempts: {last_error or 'unknown error'}"
            ),
        )

    def _build_repair_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次修复输出未通过结构化校验。",
            retry_suffix="不要解释，不要输出 Markdown 代码块，不要缺字段，不要改目标 segment_id。",
        )

    def _build_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
    ) -> PromptRequest:
        return self._build_structured_retry_request(
            request=request,
            schema=schema,
            attempt=attempt,
            last_error=last_error,
            retry_prefix="上一次输出未通过结构化校验。",
            retry_suffix=(
                "不要解释，不要输出 Markdown 代码块，不要遗漏字段，"
                "不要把分析备注写成正式分镜内容。"
            ),
        )

    def _build_structured_retry_request(
        self,
        *,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None,
        retry_prefix: str,
        retry_suffix: str,
    ) -> PromptRequest:
        if attempt <= 1:
            return request

        normalized_error = " ".join(str(last_error or "").split()).strip()
        retry_note = f"\n\n{retry_prefix}这是第 {attempt} 次尝试。"
        if normalized_error:
            retry_note += f" 失败原因：{normalized_error}。"
        retry_note += f" 请严格按 {schema.__name__} 返回。{retry_suffix}"
        metadata = dict(request.metadata)
        metadata["structured_retry_attempt"] = attempt
        return PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt + retry_note,
            metadata=metadata,
        )

    def _execute_structured_request(
        self,
        *,
        schema: type[StructuredModelT],
        request: PromptRequest,
        attempts: int,
        validator: Callable[[StructuredModelT], StructuredModelT] | None,
        request_builder: Callable[..., PromptRequest],
        response_coercer: Callable[[object, type[StructuredModelT]], StructuredModelT],
        failure_builder: Callable[[Exception | None], Exception],
    ) -> StructuredModelT:
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            attempt_request = request_builder(
                request=request,
                schema=schema,
                attempt=attempt,
                last_error=last_error,
            )
            try:
                response = self.backend.generate_structured(attempt_request, schema)
                candidate = response_coercer(response, schema)
                if validator is not None:
                    return validator(candidate)
                return candidate
            except AgentBackendUnavailableError:
                raise
            except Exception as exc:
                last_error = exc
        raise failure_builder(last_error)

    def _coerce_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        if response is None:
            raise RuntimeError(
                f"模型没有返回 {schema.__name__} 结构化对象；"
                "可能是本轮没有触发 tool call，也没有返回可解析 JSON。"
            )
        return schema.model_validate(response)

    def _validate_structured_response(
        self,
        response: object,
        schema: type[StructuredModelT],
    ) -> StructuredModelT:
        if isinstance(response, schema):
            return response
        return schema.model_validate(response)

    def _validate_character_visual_bible_output(
        self,
        visual_bible: CharacterVisualBibleSchema,
        *,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        canonical_names = [item.name for item in novel_package.outline.characters]
        canonical_genders = {
            item.name: item.gender
            for item in novel_package.outline.characters
        }
        actual_names = [item.name.strip() for item in visual_bible.characters]
        if len(actual_names) != len(canonical_names):
            raise ValueError(
                "CharacterVisualBibleSchema 角色数量必须与小说角色表一致。"
                f"期望 {len(canonical_names)}，实际 {len(actual_names)}。"
            )
        if set(actual_names) != set(canonical_names):
            raise ValueError(
                "CharacterVisualBibleSchema 角色名必须与小说角色表完全一致。"
                f"期望：{canonical_names}；实际：{actual_names}。"
            )
        for item in visual_bible.characters:
            if not item.appearance.strip() or not item.outfit.strip() or not item.portrait_prompt.strip():
                raise ValueError(
                    f"角色 {item.name} 缺少 appearance / outfit / portrait_prompt。"
                )
            expected_gender = canonical_genders.get(item.name.strip(), "").strip()
            if expected_gender and item.gender.strip() != expected_gender:
                raise ValueError(
                    f"角色 {item.name} 的 gender 必须继承小说角色卡。"
                    f"期望 {expected_gender}，实际 {item.gender!r}。"
                )
        return visual_bible

    def _validate_segment_plan_output(
        self,
        plan: VideoSegmentPlanSchema,
        *,
        novel_package: NovelPackage,
    ) -> VideoSegmentPlanSchema:
        chapter_numbers = {item.number for item in novel_package.outline.chapters}
        chapter_coverage: dict[int, int] = {
            number: 0 for number in chapter_numbers
        }
        forbidden_meta_phrases = (
            "当前片段聚焦",
            "结尾要保留",
            "当前小段聚焦",
        )
        if not plan.scenes:
            raise ValueError("VideoSegmentPlanSchema.scenes 不能为空。")
        for scene in plan.scenes:
            if scene.chapter_number not in chapter_numbers:
                raise ValueError(
                    f"scene {scene.scene_id} 引用了不存在的 chapter_number={scene.chapter_number}。"
                )
            if not scene.title.strip() or not scene.summary.strip():
                raise ValueError(f"scene {scene.scene_id} 缺少 title 或 summary。")
            if not scene.segments:
                raise ValueError(f"scene {scene.scene_id} 至少需要 1 个 segment。")
        for segment in plan.segments:
            if segment.chapter_number not in chapter_numbers:
                raise ValueError(
                    f"segment {segment.segment_id} 引用了不存在的 chapter_number={segment.chapter_number}。"
                )
            chapter_coverage[segment.chapter_number] = chapter_coverage.get(segment.chapter_number, 0) + 1
            if not segment.involved_characters:
                raise ValueError(f"segment {segment.segment_id} 缺少 involved_characters。")
            fields_to_check = [
                segment.summary,
                segment.narration,
                segment.scene_prompt,
                segment.start_frame_prompt,
                segment.mid_frame_prompt,
                segment.end_frame_prompt,
                *segment.dialogue_lines,
                *segment.subtitle_lines,
                *segment.timed_beats,
            ]
            joined = "\n".join(item for item in fields_to_check if item).strip()
            if not joined:
                raise ValueError(f"segment {segment.segment_id} 缺少有效分镜内容。")
            matched_phrase = next(
                (phrase for phrase in forbidden_meta_phrases if phrase in joined),
                "",
            )
            if matched_phrase:
                raise ValueError(
                    f"segment {segment.segment_id} 包含分析模板话术“{matched_phrase}”，"
                    "说明模型没有输出可直接执行的正式分镜。"
                )
        missing_chapters = [
            number for number, count in sorted(chapter_coverage.items()) if count <= 0
        ]
        if missing_chapters:
            raise ValueError(
                "视频分镜没有覆盖全部章节，缺失章节："
                + "、".join(str(item) for item in missing_chapters)
            )
        return plan

    def _validate_segment_continuity_repair(
        self,
        candidate: SegmentContinuityRepairSchema,
        *,
        target_segment: VideoSegment,
        previous_segment: VideoSegment | None,
    ) -> SegmentContinuityRepairSchema:
        if candidate.segment_id.strip() != target_segment.segment_id:
            raise ValueError(
                f"segment_id 必须保持为 {target_segment.segment_id}，实际为 {candidate.segment_id!r}。"
            )

        involved_characters = {
            str(name).strip()
            for name in target_segment.involved_characters
            if str(name).strip()
        }
        if not involved_characters:
            raise ValueError("目标 segment 缺少 involved_characters，无法执行修复。")

        for field_name, characters in (
            ("start_frame_characters", candidate.start_frame_characters),
            ("mid_frame_characters", candidate.mid_frame_characters if candidate.requires_mid_frame else []),
            ("end_frame_characters", candidate.end_frame_characters),
        ):
            invalid_names = [
                name for name in characters
                if str(name).strip() and str(name).strip() not in involved_characters
            ]
            if invalid_names:
                raise ValueError(
                    f"{field_name} 只能使用目标片段已有角色，非法角色：{'、'.join(invalid_names)}。"
                )

        if not candidate.start_frame_characters:
            raise ValueError("start_frame_characters 不能为空。")
        if not candidate.end_frame_characters:
            raise ValueError("end_frame_characters 不能为空。")
        if candidate.requires_mid_frame:
            if not candidate.mid_frame_prompt.strip():
                raise ValueError("requires_mid_frame=true 时 mid_frame_prompt 不能为空。")
            if not candidate.mid_frame_characters:
                raise ValueError("requires_mid_frame=true 时 mid_frame_characters 不能为空。")

        duration_seconds = self._normalize_seedance_duration(candidate.duration_seconds)
        if duration_seconds != candidate.duration_seconds:
            raise ValueError(
                f"duration_seconds 必须在 {self.SEEDANCE_MIN_DURATION_SECONDS}-{self.SEEDANCE_MAX_DURATION_SECONDS} 秒之间。"
            )

        subtitle_lines = candidate.subtitle_lines or self._build_subtitle_lines(
            narration=candidate.narration,
            dialogue_lines=candidate.dialogue_lines,
            timed_beats=candidate.timed_beats,
        )
        required_duration = self._estimate_required_speech_duration(
            narration=candidate.narration,
            dialogue_lines=candidate.dialogue_lines,
            subtitle_lines=subtitle_lines,
        )
        if required_duration > duration_seconds:
            raise ValueError(
                f"当前对白/字幕至少需要 {required_duration} 秒，但输出时长只有 {duration_seconds} 秒。"
            )

        if not candidate.timed_beats:
            raise ValueError("timed_beats 不能为空。")
        max_end_seconds = 0.0
        parsed_any = False
        for beat in candidate.timed_beats:
            match = TIMED_BEAT_PATTERN.search(str(beat))
            if match is None:
                continue
            parsed_any = True
            start_seconds = float(match.group("start"))
            end_seconds = float(match.group("end"))
            if start_seconds >= end_seconds:
                raise ValueError(f"timed_beats 存在无效时间范围：{beat}")
            max_end_seconds = max(max_end_seconds, end_seconds)
        if parsed_any and max_end_seconds > duration_seconds + 0.2:
            raise ValueError(
                f"timed_beats 最后结束时间 {max_end_seconds:g}s 超过当前片段时长 {duration_seconds}s。"
            )

        transition_mode = candidate.continuity_link.transition_mode.strip().lower()
        if previous_segment is None and transition_mode == "continue":
            raise ValueError("首段或无上一段时，continuity_link.transition_mode 不能为 continue。")
        if (
            previous_segment is not None
            and transition_mode == "continue"
            and candidate.continuity_link.previous_segment_id.strip()
            and candidate.continuity_link.previous_segment_id.strip() != previous_segment.segment_id
        ):
            raise ValueError(
                f"continue 模式下 previous_segment_id 必须是 {previous_segment.segment_id}。"
            )
        return candidate

    def _materialize_repaired_segment(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        target_segment: VideoSegment,
        target_scene: VideoScene,
        previous_segment: VideoSegment | None,
        repair_patch: SegmentContinuityRepairSchema,
    ) -> VideoSegmentSchema:
        target_schema = VideoSegmentSchema.model_validate(to_jsonable(target_segment))
        character_visual_bible = CharacterVisualBibleSchema(
            characters=[
                {
                    "name": item.name,
                    "role": item.role,
                    "gender": item.gender,
                    "appearance": item.appearance,
                    "outfit": item.outfit,
                    "color_palette": list(item.color_palette),
                    "portrait_prompt": item.portrait_prompt,
                }
                for item in project_package.character_profiles
            ]
        )
        candidate = target_schema.model_copy(
            update={
                "scene_prompt": repair_patch.scene_prompt.strip(),
                "start_frame_prompt": repair_patch.start_frame_prompt.strip(),
                "mid_frame_prompt": repair_patch.mid_frame_prompt.strip(),
                "end_frame_prompt": repair_patch.end_frame_prompt.strip(),
                "start_frame_characters": list(repair_patch.start_frame_characters),
                "mid_frame_characters": list(repair_patch.mid_frame_characters),
                "end_frame_characters": list(repair_patch.end_frame_characters),
                "narration": repair_patch.narration.strip(),
                "dialogue_lines": list(repair_patch.dialogue_lines),
                "subtitle_lines": list(repair_patch.subtitle_lines),
                "timed_beats": list(repair_patch.timed_beats),
                "duration_seconds": repair_patch.duration_seconds,
                "requires_mid_frame": repair_patch.requires_mid_frame,
                "transition_hint": self._normalize_transition_hint(repair_patch.transition_hint),
                "shot_state": repair_patch.shot_state,
                "continuity_link": repair_patch.continuity_link,
            }
        )
        single_plan = self._normalize_segment_characters(
            VideoSegmentPlanSchema.model_validate({"segments": [candidate.model_dump()]}),
            novel_package,
            character_visual_bible,
        )
        normalized_segment = single_plan.segments[0]
        requires_mid_frame = self._should_require_mid_frame(
            involved_characters=normalized_segment.involved_characters,
            duration_seconds=normalized_segment.duration_seconds,
            dialogue_lines=normalized_segment.dialogue_lines,
            timed_beats=normalized_segment.timed_beats,
            requested=normalized_segment.requires_mid_frame,
        )
        normalized_segment = normalized_segment.model_copy(
            update={
                "requires_mid_frame": requires_mid_frame,
                "mid_frame_prompt": (
                    normalized_segment.mid_frame_prompt
                    if requires_mid_frame
                    else ""
                ),
                "mid_frame_characters": (
                    normalized_segment.mid_frame_characters
                    if requires_mid_frame
                    else []
                ),
                "subtitle_lines": (
                    normalized_segment.subtitle_lines
                    or self._build_subtitle_lines(
                        narration=normalized_segment.narration,
                        dialogue_lines=normalized_segment.dialogue_lines,
                        timed_beats=normalized_segment.timed_beats,
                    )
                ),
                "source_segment_id": normalized_segment.source_segment_id or normalized_segment.segment_id,
            }
        )
        repaired_scene_bible = self._repair_scene_bible(
            novel_package=novel_package,
            chapter_number=normalized_segment.chapter_number,
            scene_title=target_scene.title,
            scene_summary=target_scene.summary,
            scene_anchor=target_scene.scene_anchor,
            scene_bible=normalized_segment.scene_bible,
            involved_characters=normalized_segment.involved_characters,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"scene_bible": repaired_scene_bible}
        )
        repaired_shot_state = self._repair_shot_state(
            novel_package=novel_package,
            segment=normalized_segment,
        )
        normalized_segment = normalized_segment.model_copy(
            update={"shot_state": repaired_shot_state}
        )
        previous_schema = (
            VideoSegmentSchema.model_validate(to_jsonable(previous_segment))
            if previous_segment is not None
            else None
        )
        repaired_continuity_link = self._repair_continuity_link(
            segment=normalized_segment,
            previous_segment=previous_schema,
        )
        return normalized_segment.model_copy(
            update={
                "continuity_link": repaired_continuity_link,
                "transition_hint": self._normalize_transition_hint(normalized_segment.transition_hint),
                "reuse_previous_end_frame": bool(
                    previous_schema is not None
                    and repaired_continuity_link.transition_mode == "continue"
                    and repaired_continuity_link.previous_segment_id == previous_schema.segment_id
                ),
            }
        )

    def _collect_segment_changed_fields(
        self,
        original_segment: VideoSegment,
        repaired_segment: VideoSegmentSchema,
    ) -> list[str]:
        original_payload = to_jsonable(original_segment)
        repaired_payload = repaired_segment.model_dump()
        tracked_fields = [
            "scene_prompt",
            "start_frame_prompt",
            "mid_frame_prompt",
            "end_frame_prompt",
            "start_frame_characters",
            "mid_frame_characters",
            "end_frame_characters",
            "narration",
            "dialogue_lines",
            "subtitle_lines",
            "timed_beats",
            "duration_seconds",
            "requires_mid_frame",
            "transition_hint",
            "shot_state",
            "continuity_link",
        ]
        changed_fields: list[str] = []
        for field_name in tracked_fields:
            if original_payload.get(field_name) != repaired_payload.get(field_name):
                changed_fields.append(field_name)
        return changed_fields
