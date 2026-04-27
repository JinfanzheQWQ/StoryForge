from __future__ import annotations

import re

from storyforge.agents.base import PromptRequest
from storyforge.core.io import to_jsonable
from storyforge.domains.novel.contracts import NovelPackage
from storyforge.domains.video.contracts import VideoProjectPackage, VideoScene, VideoSegment
from storyforge.domains.video.schemas import (
    CharacterVisualBibleSchema,
    ContinuityLinkSchema,
    SceneBibleSchema,
    SceneContinuityRepairSchema,
    SegmentContinuityRepairSchema,
    ShotStateSchema,
    VideoSceneSchema,
    VideoSegmentPlanSchema,
    VideoSegmentSchema,
)


class VideoRepairMixin:
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
                speech_budget_context={
                    "current_duration_seconds": target_segment.duration_seconds,
                    "required_duration_seconds": self._estimate_required_speech_duration(
                        narration=target_segment.narration,
                        dialogue_lines=target_segment.dialogue_lines,
                        subtitle_lines=target_segment.subtitle_lines,
                    ),
                    "max_duration_seconds": self.SEEDANCE_MAX_DURATION_SECONDS,
                    "speech_chars_per_second": self.SPEECH_CHARS_PER_SECOND,
                },
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

    def repair_scene_continuity(
        self,
        *,
        novel_package: NovelPackage,
        project_package: VideoProjectPackage,
        scene_id: str,
        scene_issues: list[dict[str, object]],
        related_segment_issues: list[dict[str, object]],
        target_segment_ids: list[str],
        selection_mode: str,
    ) -> tuple[VideoScene, dict[str, object]]:
        target_scene = next(
            (scene for scene in project_package.scenes if scene.scene_id == scene_id),
            None,
        )
        if target_scene is None:
            raise ValueError(f"Scene {scene_id} not found in current project package.")

        target_segment_set = {item for item in target_segment_ids if item}
        target_segments = [
            segment for segment in target_scene.segments
            if not target_segment_set or segment.segment_id in target_segment_set
        ]
        if not target_segments:
            raise ValueError(f"Scene {scene_id} has no target segments for continuity repair.")

        request = PromptRequest(
            system_prompt=(
                "你是 StoryForge 的 Scene Continuity Repair Agent。"
                "你只修复目标 scene 的场景连续性基线，不重写剧情，不改章节结构，不新增角色。"
                "你的职责是把当前 scene 修成更适合后续场景母图和视频复用的稳定环境合同。"
            ),
            user_prompt=self._build_scene_continuity_repair_user_prompt(
                story_title=project_package.title,
                character_profiles=project_package.character_profiles,
                scene_payload=to_jsonable(target_scene),
                target_segment_payloads=[to_jsonable(item) for item in target_segments],
                scene_issues=scene_issues,
                related_segment_issues=related_segment_issues,
                selection_mode=selection_mode,
            ),
            metadata={"task": "scene-continuity-repair", "scene_id": scene_id},
        )
        repair_patch = self._run_strict_structured_agent(
            schema=SceneContinuityRepairSchema,
            request=request,
            validator=lambda candidate: self._validate_scene_continuity_repair(
                candidate,
                target_scene=target_scene,
            ),
        )
        repaired_scene = self._materialize_repaired_scene(
            novel_package=novel_package,
            target_scene=target_scene,
            repair_patch=repair_patch,
        )
        repair_report = {
            "scene_id": scene_id,
            "repair_summary": repair_patch.repair_summary.strip(),
            "selection_mode": selection_mode,
            "affected_segment_ids": list(target_segment_ids),
            "continuity_issues": scene_issues,
            "related_segment_issues": related_segment_issues,
            "raw_patch": repair_patch.model_dump(),
            "changed_fields": self._collect_scene_changed_fields(target_scene, repaired_scene),
            "before": to_jsonable(target_scene),
            "after": to_jsonable(repaired_scene),
        }
        return repaired_scene, repair_report

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

        candidate_characters = [
            str(name).strip()
            for name in candidate.involved_characters
            if str(name).strip()
        ] or list(involved_characters)
        invalid_names = [name for name in candidate_characters if name not in involved_characters]
        if invalid_names:
            raise ValueError(
                f"involved_characters 只能使用目标片段已有角色，非法角色：{'、'.join(invalid_names)}。"
            )
        if not candidate_characters:
            raise ValueError("involved_characters 不能为空。")
        self._validate_segment_direction_consistency(
            segment_id=candidate.segment_id,
            screen_direction=candidate.shot_state.screen_direction,
            end_state_lock=candidate.shot_state.end_state_lock,
            tail_state_prompt=candidate.shot_state.end_state_lock,
            timed_beats=candidate.timed_beats,
        )

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
        duration_seconds = self._fit_duration_to_speech_budget(
            segment_id=candidate.segment_id,
            current_duration_seconds=duration_seconds,
            required_duration_seconds=required_duration,
            allow_split_retry=False,
        )
        if duration_seconds != candidate.duration_seconds:
            candidate = candidate.model_copy(update={"duration_seconds": duration_seconds})

        self._validate_timed_beats_timeline(
            segment_id=candidate.segment_id,
            timed_beats=candidate.timed_beats,
            duration_seconds=duration_seconds,
            require_full_coverage=True,
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

    def _validate_scene_continuity_repair(
        self,
        candidate: SceneContinuityRepairSchema,
        *,
        target_scene: VideoScene,
    ) -> SceneContinuityRepairSchema:
        if candidate.scene_id.strip() != target_scene.scene_id:
            raise ValueError(
                f"scene_id 必须保持为 {target_scene.scene_id}，实际为 {candidate.scene_id!r}。"
            )
        if not candidate.scene_anchor.strip():
            raise ValueError("scene_anchor 不能为空。")
        scene_bible = candidate.scene_bible
        required_text_fields = {
            "location": scene_bible.location,
            "time_window": scene_bible.time_window,
            "weather": scene_bible.weather,
            "lighting": scene_bible.lighting,
            "spatial_layout": scene_bible.spatial_layout,
            "continuity_notes": scene_bible.continuity_notes,
        }
        missing_fields = [key for key, value in required_text_fields.items() if not str(value or "").strip()]
        if missing_fields:
            raise ValueError("scene_bible 缺少必要字段：" + "、".join(missing_fields))
        if len([item for item in scene_bible.background_anchors if str(item or "").strip()]) < 2:
            raise ValueError("scene_bible.background_anchors 至少需要 2 个。")
        if len([item for item in scene_bible.fixed_props if str(item or "").strip()]) < 1:
            raise ValueError("scene_bible.fixed_props 至少需要 1 个。")
        if len([item for item in scene_bible.dominant_palette if str(item or "").strip()]) < 1:
            raise ValueError("scene_bible.dominant_palette 至少需要 1 个。")
        return candidate

    def _rebuild_plan_preserving_scenes(
        self,
        *,
        source_plan: VideoSegmentPlanSchema,
        replacement_segments: list[VideoSegmentSchema],
        scene_bible_overrides: dict[tuple[int, str], SceneBibleSchema] | None = None,
    ) -> VideoSegmentPlanSchema:
        grouped_segments: dict[tuple[int, str], list[VideoSegmentSchema]] = {}
        for segment in replacement_segments:
            grouped_segments.setdefault(
                (segment.chapter_number, segment.scene_id),
                [],
            ).append(segment)

        rebuilt_scenes: list[VideoSceneSchema] = []
        inserted_keys: set[tuple[int, str]] = set()
        for scene in source_plan.scenes:
            scene_key = (scene.chapter_number, scene.scene_id)
            scene_segments = grouped_segments.get(scene_key, [])
            if not scene_segments:
                continue
            scene_bible = (
                scene_bible_overrides.get(scene_key, scene.scene_bible)
                if scene_bible_overrides is not None
                else scene.scene_bible
            )
            involved_characters = list(scene.involved_characters)
            for segment in scene_segments:
                for name in segment.involved_characters:
                    if name not in involved_characters:
                        involved_characters.append(name)
            rebuilt_scenes.append(
                scene.model_copy(
                    update={
                        "segments": scene_segments,
                        "scene_bible": scene_bible,
                        "involved_characters": involved_characters,
                    }
                )
            )
            inserted_keys.add(scene_key)

        if len(inserted_keys) != len(grouped_segments):
            derived_missing_scene_plan = VideoSegmentPlanSchema.model_validate(
                {"segments": [item.model_dump() for item in replacement_segments]}
            )
            for scene in derived_missing_scene_plan.scenes:
                scene_key = (scene.chapter_number, scene.scene_id)
                if scene_key in inserted_keys:
                    continue
                rebuilt_scenes.append(
                    scene.model_copy(
                        update={
                            "scene_bible": (
                                scene_bible_overrides.get(scene_key, scene.scene_bible)
                                if scene_bible_overrides is not None
                                else scene.scene_bible
                            )
                        }
                    )
                )

        return VideoSegmentPlanSchema.model_validate(
            {"scenes": [item.model_dump() for item in rebuilt_scenes]}
        )

    def _repair_character_visual_bible(
        self,
        visual_bible: CharacterVisualBibleSchema,
        novel_package: NovelPackage,
    ) -> CharacterVisualBibleSchema:
        canonical_characters = list(novel_package.outline.characters)
        canonical_names = [item.name for item in canonical_characters]
        role_map = {item.name: item.role for item in canonical_characters}
        gender_map = {item.name: item.gender for item in canonical_characters}
        repaired: dict[str, object] = {}

        for item in visual_bible.characters:
            resolved_name = self._resolve_character_name(
                raw_name=item.name,
                canonical_names=canonical_names,
                role_map=role_map,
            ) or self._resolve_character_name(
                raw_name=item.role,
                canonical_names=canonical_names,
                role_map=role_map,
            )
            if not resolved_name or resolved_name in repaired:
                continue
            repaired_item = item.model_copy(
                update={
                    "name": resolved_name,
                    "role": role_map.get(resolved_name, item.role),
                    "gender": gender_map.get(resolved_name, item.gender),
                    "portrait_prompt": self._replace_character_aliases(
                        item.portrait_prompt,
                        {item.name: resolved_name},
                    ),
                }
            )
            repaired[resolved_name] = repaired_item

        return CharacterVisualBibleSchema(
            characters=[repaired[name] for name in canonical_names]
        )

    def _resolve_character_name(
        self,
        raw_name: str,
        canonical_names: list[str],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token
        if len(canonical_names) == 1:
            return canonical_names[0]

        lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主角团",
            "神秘人",
            "录音师",
            "修复师",
            "告白者",
            "主动方",
            "发起者",
        }
        if token in lead_aliases:
            return canonical_names[0]

        counterpart_aliases = {
            "被告白的人",
            "被表白的人",
            "对方",
            "另一方",
            "回应方",
            "被回应的人",
        }
        if token in counterpart_aliases:
            return canonical_names[1] if len(canonical_names) >= 2 else canonical_names[0]

        fuzzy_matches = [
            name for name in canonical_names if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name for name, role in role_map.items() if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]
        return ""

    def _repair_segment_plan(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        valid_chapters = {chapter.number for chapter in novel_package.outline.chapters}
        repaired_segments = [
            item
            for item in plan.segments
            if item.chapter_number in valid_chapters
        ]
        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=repaired_segments,
        )

    def _repair_scene_bibles(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
    ) -> VideoSegmentPlanSchema:
        chapter_numbers = {
            item.number
            for item in novel_package.outline.chapters
        }
        repaired_by_scene: dict[tuple[int, str], SceneBibleSchema] = {}
        for scene in plan.scenes:
            if scene.chapter_number not in chapter_numbers:
                continue
            repaired_by_scene[(scene.chapter_number, scene.scene_id)] = self._repair_scene_bible(
                novel_package=novel_package,
                chapter_number=scene.chapter_number,
                scene_title=scene.title,
                scene_summary=scene.summary,
                scene_anchor=scene.scene_anchor,
                scene_bible=scene.scene_bible,
                involved_characters=scene.involved_characters,
            )

        repaired_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            repaired_scene_bible = repaired_by_scene.get((segment.chapter_number, segment.scene_id))
            if repaired_scene_bible is None:
                repaired_scene_bible = self._repair_scene_bible(
                    novel_package=novel_package,
                    chapter_number=segment.chapter_number,
                    scene_title=segment.scene_title or segment.title,
                    scene_summary=segment.scene_summary or segment.summary,
                    scene_anchor=segment.scene_anchor,
                    scene_bible=segment.scene_bible,
                    involved_characters=segment.involved_characters,
                )
            repaired_segments.append(
                segment.model_copy(update={"scene_bible": repaired_scene_bible})
            )

        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=repaired_segments,
            scene_bible_overrides=repaired_by_scene,
        )

    def _repair_shot_states(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
    ) -> VideoSegmentPlanSchema:
        repaired_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            repaired_segments.append(
                segment.model_copy(
                    update={
                        "shot_state": self._repair_shot_state(
                            novel_package=novel_package,
                            segment=segment,
                        )
                    }
                )
            )
        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=repaired_segments,
        )

    def _repair_continuity_links(
        self,
        plan: VideoSegmentPlanSchema,
    ) -> VideoSegmentPlanSchema:
        repaired_segments: list[VideoSegmentSchema] = []
        previous_segment: VideoSegmentSchema | None = None
        for segment in plan.segments:
            repaired_link = self._repair_continuity_link(
                segment=segment,
                previous_segment=previous_segment,
            )
            repaired_segment = segment.model_copy(
                update={
                    "continuity_link": repaired_link,
                }
            )
            repaired_segments.append(repaired_segment)
            previous_segment = repaired_segment
        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=repaired_segments,
        )

    def _repair_scene_bible(
        self,
        *,
        novel_package: NovelPackage,
        chapter_number: int,
        scene_title: str,
        scene_summary: str,
        scene_anchor: str,
        scene_bible: SceneBibleSchema,
        involved_characters: list[str],
    ) -> SceneBibleSchema:
        default_payload = self._derive_scene_bible_defaults(
            novel_package=novel_package,
            chapter_number=chapter_number,
            scene_title=scene_title or "场景",
            scene_summary=scene_summary or scene_title or "当前场景",
            scene_anchor=scene_anchor,
            focus_characters=involved_characters,
        )
        payload = scene_bible.model_dump()
        repaired: dict[str, object] = {}
        for key, default_value in default_payload.items():
            current_value = payload.get(key)
            repaired[key] = (
                current_value
                if self._scene_bible_value_has_signal(current_value)
                else default_value
            )
        return SceneBibleSchema.model_validate(repaired)

    def _repair_shot_state(
        self,
        *,
        novel_package: NovelPackage,
        segment: VideoSegmentSchema,
    ) -> ShotStateSchema:
        default_payload = self._derive_shot_state_defaults(
            summary=segment.summary,
            scene_anchor=segment.scene_anchor,
            scene_bible=segment.scene_bible,
            focus_characters=segment.involved_characters,
        )
        payload = segment.shot_state.model_dump()
        repaired: dict[str, object] = {}
        for key, default_value in default_payload.items():
            current_value = payload.get(key)
            repaired[key] = (
                current_value
                if self._shot_state_value_has_signal(current_value)
                else default_value
            )

        if not str(repaired.get("action_progression", "")).strip():
            repaired["action_progression"] = segment.summary
        if not str(repaired.get("end_state_lock", "")).strip():
            repaired["end_state_lock"] = (
                self._extract_beat_descriptions(segment.timed_beats)[-1]
                if self._extract_beat_descriptions(segment.timed_beats)
                else segment.summary
            )
        return ShotStateSchema.model_validate(repaired)

    def _repair_continuity_link(
        self,
        *,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema | None,
    ) -> ContinuityLinkSchema:
        payload = segment.continuity_link.model_dump()
        if previous_segment is None:
            return ContinuityLinkSchema.model_validate(
                {
                    "previous_segment_id": "",
                    "transition_mode": "start",
                    "opening_match": "",
                    "carry_over_elements": [],
                    "allowed_changes": (
                        str(payload.get("allowed_changes", "") or "")
                        or "作为当前故事或场景的起始片段建立新的连续性基线。"
                    ),
                    "transition_reason": (
                        str(payload.get("transition_reason", "") or "")
                        or "首段没有上一片段可承接。"
                    ),
                }
            )

        derived_mode = self._derive_continuity_mode(segment, previous_segment)
        raw_mode = str(payload.get("transition_mode", "") or "").strip().lower()
        transition_mode = raw_mode if raw_mode in {"start", "continue", "cut"} else derived_mode
        if transition_mode == "start":
            transition_mode = derived_mode

        opening_match = str(payload.get("opening_match", "") or "").strip()
        if transition_mode == "continue":
            derived_opening_match = self._derive_opening_match(previous_segment)
            if (
                not opening_match
                or self._continuity_statement_too_generic(opening_match)
                or self._text_overlap_ratio(
                    opening_match,
                    previous_segment.shot_state.end_state_lock or previous_segment.summary,
                ) < 0.22
            ):
                opening_match = derived_opening_match

        carry_over_elements = [
            str(item).strip()
            for item in payload.get("carry_over_elements", [])
            if str(item).strip()
        ]
        if transition_mode == "continue" and not carry_over_elements:
            carry_over_elements = self._derive_carry_over_elements(previous_segment)

        allowed_changes = str(payload.get("allowed_changes", "") or "").strip()
        if transition_mode == "continue":
            derived_allowed_changes = self._derive_allowed_changes(segment, previous_segment)
            if (
                not allowed_changes
                or self._continuity_statement_too_generic(allowed_changes)
                or self._text_overlap_ratio(
                    allowed_changes,
                    previous_segment.shot_state.end_state_lock or previous_segment.summary,
                ) >= 0.78
            ):
                allowed_changes = derived_allowed_changes
        elif not allowed_changes:
            allowed_changes = (
                "允许切换到新的时空、景别和动作状态。"
                if transition_mode == "cut"
                else "作为起始段建立新的连续性基线。"
            )

        transition_reason = str(payload.get("transition_reason", "") or "").strip()
        if not transition_reason:
            transition_reason = (
                "同一 scene 内连续推进当前动作链。"
                if transition_mode == "continue"
                else (
                    "发生了明确转场、时空切换或镜头切断。"
                    if transition_mode == "cut"
                    else "当前片段为起始段。"
                )
            )

        return ContinuityLinkSchema.model_validate(
            {
                "previous_segment_id": (
                    previous_segment.segment_id
                    if transition_mode == "continue"
                    else ""
                ),
                "transition_mode": transition_mode,
                "opening_match": opening_match,
                "carry_over_elements": (
                    carry_over_elements if transition_mode == "continue" else []
                ),
                "allowed_changes": allowed_changes,
                "transition_reason": transition_reason,
            }
        )

    def _derive_continuity_mode(
        self,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        explicit_previous_id = segment.continuity_link.previous_segment_id.strip()
        explicit_mode = segment.continuity_link.transition_mode.strip().lower()
        if explicit_mode == "continue" and explicit_previous_id == previous_segment.segment_id:
            return "continue"
        if explicit_mode == "cut":
            return "cut"

        transition_hint = self._normalize_transition_hint(segment.transition_hint)
        if transition_hint == "continue":
            return "continue"
        if transition_hint == "cut":
            return "cut"

        if segment.scene_id and previous_segment.scene_id and segment.scene_id == previous_segment.scene_id:
            return "continue"
        if (
            segment.source_segment_id
            and previous_segment.source_segment_id
            and segment.source_segment_id == previous_segment.source_segment_id
        ):
            return "continue"
        if self._contains_hard_cut_hint(
            previous_segment.model_copy(update={"narration": previous_segment.narration + " " + segment.narration})
        ):
            return "cut"
        return "cut"

    def _derive_carry_over_elements(
        self,
        previous_segment: VideoSegmentSchema,
    ) -> list[str]:
        carry_over: list[str] = []
        if previous_segment.shot_state.blocking:
            carry_over.append("角色站位")
        if previous_segment.shot_state.screen_direction:
            carry_over.append("视线与运动方向")
        if previous_segment.shot_state.prop_continuity:
            carry_over.append("关键道具与手部状态")
        if previous_segment.scene_bible.background_anchors:
            carry_over.append("背景锚点")
        if previous_segment.shot_state.end_state_lock:
            carry_over.append("上一段尾部动作定格")
        if not carry_over:
            carry_over.extend(["角色站位", "视线方向", "关键道具"])
        return carry_over

    def _derive_opening_match(
        self,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        previous_end = (
            previous_segment.shot_state.end_state_lock
            or previous_segment.shot_state.action_progression
            or previous_segment.summary
        )
        parts = [f"开场先严格承接上一段尾部：{previous_end}"]
        if previous_segment.shot_state.blocking:
            parts.append(f"保留站位/朝向：{previous_segment.shot_state.blocking}")
        if previous_segment.shot_state.prop_continuity:
            parts.append(f"保留持物/服装状态：{previous_segment.shot_state.prop_continuity}")
        if previous_segment.shot_state.screen_direction:
            parts.append(f"维持运动与视线方向：{previous_segment.shot_state.screen_direction}")
        return "；".join(part.strip() for part in parts if part.strip())

    def _derive_allowed_changes(
        self,
        segment: VideoSegmentSchema,
        previous_segment: VideoSegmentSchema,
    ) -> str:
        previous_end = (
            previous_segment.shot_state.end_state_lock
            or previous_segment.shot_state.action_progression
            or previous_segment.summary
        )
        beat_descriptions = self._extract_beat_descriptions(segment.timed_beats)
        target_progress = (
            segment.shot_state.action_progression
            or segment.summary
            or (beat_descriptions[0] if beat_descriptions else "")
        )
        if self._text_overlap_ratio(previous_end, target_progress) >= 0.78:
            target_progress = segment.summary or target_progress
        return (
            f"承接开场后，必须把动作从“{previous_end}”推进到“{target_progress}”，"
            "不能只是重复上一段的同一拍。"
        )

    def _group_segments_by_chapter(
        self,
        segments: list[VideoSegmentSchema],
    ) -> dict[int, list[VideoSegmentSchema]]:
        grouped: dict[int, list[VideoSegmentSchema]] = {}
        for item in segments:
            grouped.setdefault(item.chapter_number, []).append(item)
        return grouped

    def _normalize_segment_characters(
        self,
        plan: VideoSegmentPlanSchema,
        novel_package: NovelPackage,
        visual_bible: CharacterVisualBibleSchema,
    ) -> VideoSegmentPlanSchema:
        canonical_names = [item.name for item in novel_package.outline.characters] or [
            item.name for item in visual_bible.characters
        ]
        chapter_feature_map = {
            item.number: list(item.featured_characters)
            for item in novel_package.outline.chapters
        }
        role_map = {
            item.name: item.role
            for item in novel_package.outline.characters
        }

        normalized_segments: list[VideoSegmentSchema] = []
        for segment in plan.segments:
            alias_map: dict[str, str] = {}
            resolved_names: list[str] = []
            for raw_name in segment.involved_characters:
                resolved = self._resolve_character_alias(
                    raw_name=raw_name,
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                    role_map=role_map,
                )
                if resolved:
                    alias_map[raw_name] = resolved
                    if resolved not in resolved_names:
                        resolved_names.append(resolved)

            if not resolved_names:
                resolved_names = self._default_segment_characters(
                    chapter_number=segment.chapter_number,
                    canonical_names=canonical_names,
                    chapter_feature_map=chapter_feature_map,
                )
            resolved_names = self._augment_segment_characters_from_text(
                segment=segment,
                resolved_names=resolved_names,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )

            normalized_segments.append(
                segment.model_copy(
                    update={
                        "scene_title": self._replace_character_aliases(segment.scene_title, alias_map),
                        "scene_summary": self._replace_character_aliases(segment.scene_summary, alias_map),
                        "scene_anchor": self._replace_character_aliases(segment.scene_anchor, alias_map),
                        "scene_bible": self._replace_character_aliases_in_scene_bible(
                            segment.scene_bible,
                            alias_map,
                        ),
                        "shot_state": self._replace_character_aliases_in_shot_state(
                            segment.shot_state,
                            alias_map,
                        ),
                        "continuity_link": self._replace_character_aliases_in_continuity_link(
                            segment.continuity_link,
                            alias_map,
                        ),
                        "title": self._replace_character_aliases(segment.title, alias_map),
                        "involved_characters": resolved_names,
                        "summary": self._replace_character_aliases(segment.summary, alias_map),
                        "narration": self._replace_character_aliases(segment.narration, alias_map),
                        "dialogue_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.dialogue_lines
                        ],
                        "subtitle_lines": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.subtitle_lines
                        ],
                        "character_voice_notes": [
                            self._replace_character_aliases(line, alias_map)
                            for line in segment.character_voice_notes
                        ],
                        "sound_effects": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.sound_effects
                        ],
                        "music_direction": self._replace_character_aliases(
                            segment.music_direction,
                            alias_map,
                        ),
                        "timed_beats": [
                            self._replace_character_aliases(item, alias_map)
                            for item in segment.timed_beats
                        ],
                        "motion_plan": self._replace_character_aliases_in_motion_plan(
                            segment.motion_plan,
                            alias_map,
                        ),
                    }
                )
            )

        return self._rebuild_plan_preserving_scenes(
            source_plan=plan,
            replacement_segments=normalized_segments,
        )

    def _replace_character_aliases_in_motion_plan(self, motion_plan, alias_map: dict[str, str]):
        return motion_plan.model_copy(
            update={
                "scene_motion": self._replace_character_aliases(motion_plan.scene_motion, alias_map),
                "beat_progression": self._replace_character_aliases(motion_plan.beat_progression, alias_map),
                "camera_path": self._replace_character_aliases(motion_plan.camera_path, alias_map),
                "character_motion": self._replace_character_aliases(motion_plan.character_motion, alias_map),
                "continuity_guard": self._replace_character_aliases(motion_plan.continuity_guard, alias_map),
            }
        )

    def _resolve_character_alias(
        self,
        raw_name: str,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> str:
        token = raw_name.strip()
        if not token:
            return ""
        if token in canonical_names:
            return token

        generic_lead_aliases = {
            "主角",
            "主人公",
            "男主",
            "女主",
            "主人物",
            "lead",
            "hero",
            "protagonist",
            "告白者",
            "主动方",
            "发起者",
        }
        if token.lower() in generic_lead_aliases or token in generic_lead_aliases:
            featured = self._default_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            return featured[0] if featured else ""

        counterpart_aliases = {
            "被告白的人",
            "被表白的人",
            "对方",
            "另一方",
            "回应方",
            "被回应的人",
        }
        if token in counterpart_aliases:
            featured = self._default_segment_characters(
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
            )
            if len(featured) >= 2:
                return featured[1]
            return canonical_names[1] if len(canonical_names) >= 2 else ""

        fuzzy_matches = [
            name
            for name in canonical_names
            if token in name or name in token
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]

        role_matches = [
            name
            for name, role in role_map.items()
            if token in role or role in token
        ]
        if len(role_matches) == 1:
            return role_matches[0]

        return ""

    def _default_segment_characters(
        self,
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
    ) -> list[str]:
        featured = [
            name
            for name in chapter_feature_map.get(chapter_number, [])
            if name in canonical_names
        ]
        if featured:
            return featured
        return canonical_names[:1]

    def _augment_segment_characters_from_text(
        self,
        segment: VideoSegmentSchema,
        resolved_names: list[str],
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> list[str]:
        combined_text = " ".join(
            [
                segment.title,
                segment.summary,
                segment.narration,
                segment.scene_bible.location,
                segment.scene_bible.time_window,
                segment.scene_bible.weather,
                segment.scene_bible.lighting,
                segment.scene_bible.spatial_layout,
                segment.scene_bible.character_blocking,
                segment.scene_bible.continuity_notes,
                " ".join(segment.scene_bible.background_anchors),
                " ".join(segment.scene_bible.fixed_props),
                segment.shot_state.framing,
                segment.shot_state.camera_motion,
                segment.shot_state.blocking,
                segment.shot_state.action_progression,
                segment.shot_state.emotion_progression,
                segment.shot_state.prop_continuity,
                segment.shot_state.screen_direction,
                segment.shot_state.end_state_lock,
                segment.continuity_link.previous_segment_id,
                segment.continuity_link.opening_match,
                " ".join(segment.continuity_link.carry_over_elements),
                segment.continuity_link.allowed_changes,
                segment.continuity_link.transition_reason,
                segment.motion_plan.scene_motion,
                segment.motion_plan.beat_progression,
                segment.motion_plan.camera_path,
                segment.motion_plan.character_motion,
                segment.motion_plan.continuity_guard,
                " ".join(segment.dialogue_lines),
                " ".join(segment.subtitle_lines),
                " ".join(segment.timed_beats),
            ]
        )
        augmented = list(resolved_names)
        for name in canonical_names:
            if name in combined_text and name not in augmented:
                augmented.append(name)

        alias_candidates = list(segment.involved_characters)
        alias_candidates.extend(self._extract_dialogue_speakers(segment.dialogue_lines))
        for raw_name in alias_candidates:
            resolved = self._resolve_character_alias(
                raw_name=raw_name,
                chapter_number=segment.chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )
            if resolved and resolved not in augmented:
                augmented.append(resolved)

        if self._looks_like_two_person_scene(combined_text) and len(augmented) < 2:
            for name in chapter_feature_map.get(segment.chapter_number, []):
                if name not in augmented and name in canonical_names:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break
            for name in canonical_names:
                if len(augmented) >= 2:
                    break
                if name not in augmented:
                    augmented.append(name)

        if len(augmented) < 2 and self._dialogue_implies_two_speakers(segment.dialogue_lines):
            for name in canonical_names:
                if name not in augmented:
                    augmented.append(name)
                if len(augmented) >= 2:
                    break

        return augmented

    def _normalize_frame_characters_for_segment(
        self,
        *,
        frame_position: str,
        raw_names: list[str],
        prompt_text: str,
        frame_context_text: str,
        resolved_names: list[str],
        chapter_number: int,
        canonical_names: list[str],
        chapter_feature_map: dict[int, list[str]],
        role_map: dict[str, str],
    ) -> list[str]:
        frame_names: list[str] = []
        for raw_name in raw_names:
            resolved = self._resolve_character_alias(
                raw_name=raw_name,
                chapter_number=chapter_number,
                canonical_names=canonical_names,
                chapter_feature_map=chapter_feature_map,
                role_map=role_map,
            )
            if resolved and resolved in resolved_names and resolved not in frame_names:
                frame_names.append(resolved)

        context_names = self._extract_visible_frame_names(frame_context_text, resolved_names)
        if frame_position != "mid" and frame_names:
            return frame_names
        if context_names:
            return context_names

        prompt_names = self._extract_visible_frame_names(prompt_text, resolved_names)
        if prompt_names:
            return prompt_names

        if frame_names:
            return frame_names

        if len(resolved_names) == 1:
            return list(resolved_names)
        return []

    def _frame_context_text(
        self,
        segment: VideoSegmentSchema,
        frame_position: str,
    ) -> str:
        timed_context = self._select_timed_beat_for_frame(
            segment.timed_beats,
            segment.duration_seconds,
            frame_position,
        )
        if timed_context:
            return timed_context
        return segment.shot_state.end_state_lock or segment.shot_state.action_progression or segment.summary

    def _select_timed_beat_for_frame(
        self,
        timed_beats: list[str],
        duration_seconds: int,
        frame_position: str,
    ) -> str:
        if not timed_beats:
            return ""

        target_time = 0.0
        if frame_position == "mid":
            target_time = max(0.0, duration_seconds / 2)
        elif frame_position == "end":
            target_time = max(0.0, duration_seconds - 0.1)

        parsed_ranges: list[tuple[float, float, str]] = []
        for item in timed_beats:
            match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*[-~—–]\s*(\d+(?:\.\d+)?)",
                item,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            start = float(match.group(1))
            end = float(match.group(2))
            if end < start:
                start, end = end, start
            parsed_ranges.append((start, end, item))

        for start, end, item in parsed_ranges:
            if start <= target_time <= end:
                return item

        if frame_position == "start":
            return timed_beats[0]
        if frame_position == "end":
            return timed_beats[-1]
        return timed_beats[len(timed_beats) // 2]

    def _extract_visible_frame_names(
        self,
        text: str,
        candidate_names: list[str],
    ) -> list[str]:
        cleaned_text = self._remove_frame_character_roster_text(text)
        visible_names: list[str] = []
        for name in candidate_names:
            if name not in cleaned_text:
                continue
            if self._name_has_visible_frame_evidence(cleaned_text, name):
                visible_names.append(name)
        return visible_names

    def _remove_frame_character_roster_text(self, text: str) -> str:
        return re.sub(
            r"(?:当前帧出镜角色|角色)\s*[:：]\s*[^，。；;]*[，。；;]?",
            "",
            text,
        )

    def _name_has_visible_frame_evidence(self, text: str, name: str) -> bool:
        escaped_name = re.escape(name)
        visible_after = (
            "独自|在|站|坐|走|跑|转身|抬头|低头|背对|面对|看着|望着|凝视|拿着|握着|"
            "出现|走近|走来|靠近|停下|开口|说|回答|回应|微笑|哭|笑|伸手|牵|拥抱|亲吻|吻|进入|离开"
        )
        visible_before = (
            "镜头聚焦|画面聚焦|画面出现|看见|看到|只见|出现|走来|走近|靠近|站在|坐在|"
            "背对镜头|面对镜头|转向|拥抱|亲吻|牵着"
        )
        if re.search(rf"{escaped_name}.{{0,14}}(?:{visible_after})", text):
            return True
        if re.search(rf"(?:{visible_before}).{{0,14}}{escaped_name}", text):
            return True

        non_visible_object = (
            "等待|等着|等|想起|回忆|怀念|想念|寻找|找|期待|盼着|盼望|望向|看向|听到|听见"
        )
        if re.search(rf"(?:{non_visible_object}).{{0,8}}{escaped_name}", text):
            return False
        return True

    def _frame_text_requires_group(self, text: str) -> bool:
        group_keywords = (
            "两人",
            "双方",
            "彼此",
            "一起",
            "同时",
            "同框",
            "对视",
            "对话",
            "交谈",
            "争吵",
            "对峙",
            "拥抱",
            "牵手",
            "亲吻",
            "接吻",
            "并肩",
        )
        return any(keyword in text for keyword in group_keywords)

    def _extract_dialogue_speakers(self, dialogue_lines: list[str]) -> list[str]:
        speakers: list[str] = []
        for line in dialogue_lines:
            speaker, separator, _ = line.partition("：")
            if not separator:
                speaker, separator, _ = line.partition(":")
            if not separator:
                continue
            normalized = re.sub(r"[（(].*?[）)]", "", speaker).strip()
            if normalized and normalized not in speakers:
                speakers.append(normalized)
        return speakers

    def _looks_like_two_person_scene(self, text: str) -> bool:
        keywords = (
            "告白",
            "表白",
            "对视",
            "对话",
            "争吵",
            "质问",
            "审问",
            "谈判",
            "拥抱",
            "牵手",
            "亲吻",
            "并肩",
            "对峙",
        )
        return any(keyword in text for keyword in keywords)

    def _dialogue_implies_two_speakers(self, dialogue_lines: list[str]) -> bool:
        if len(dialogue_lines) >= 2:
            return True
        if not dialogue_lines:
            return False
        line = dialogue_lines[0]
        return "你" in line or "她" in line or "他" in line

    def _replace_character_aliases(self, text: str, alias_map: dict[str, str]) -> str:
        updated = text
        for alias, actual_name in alias_map.items():
            if alias and actual_name:
                updated = updated.replace(alias, actual_name)
        return updated

    def _replace_character_aliases_in_scene_bible(
        self,
        scene_bible: SceneBibleSchema,
        alias_map: dict[str, str],
    ) -> SceneBibleSchema:
        payload = scene_bible.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return SceneBibleSchema.model_validate(repaired_payload)

    def _replace_character_aliases_in_shot_state(
        self,
        shot_state: ShotStateSchema,
        alias_map: dict[str, str],
    ) -> ShotStateSchema:
        payload = shot_state.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return ShotStateSchema.model_validate(repaired_payload)

    def _replace_character_aliases_in_continuity_link(
        self,
        continuity_link: ContinuityLinkSchema,
        alias_map: dict[str, str],
    ) -> ContinuityLinkSchema:
        payload = continuity_link.model_dump()
        repaired_payload: dict[str, object] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                repaired_payload[key] = self._replace_character_aliases(value, alias_map)
                continue
            if isinstance(value, list):
                repaired_payload[key] = [
                    self._replace_character_aliases(str(item), alias_map)
                    for item in value
                ]
                continue
            repaired_payload[key] = value
        return ContinuityLinkSchema.model_validate(repaired_payload)

    def _scene_bible_value_has_signal(self, value: object) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(str(item).strip() for item in value)
        return value is not None

    def _shot_state_value_has_signal(self, value: object) -> bool:
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(str(item).strip() for item in value)
        return value is not None

    def _continuity_statement_too_generic(self, text: str) -> bool:
        normalized = self._normalize_similarity_text(text)
        if not normalized:
            return True
        reduced = normalized
        for token in (
            "开场",
            "开头",
            "继续",
            "承接",
            "延续",
            "上一段",
            "上一镜头",
            "上一片段",
            "尾部",
            "尾部",
            "状态",
            "镜头",
            "画面",
            "保持",
            "一致",
            "跟上",
        ):
            reduced = reduced.replace(token, "")
        return len(reduced) < 6

    def _normalize_similarity_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").strip().lower())

    def _text_ngrams(self, value: str) -> set[str]:
        normalized = self._normalize_similarity_text(value)
        if not normalized:
            return set()
        if len(normalized) <= 3:
            return {normalized}
        grams: set[str] = set()
        for size in (2, 3):
            if len(normalized) < size:
                continue
            grams.update(
                normalized[index : index + size]
                for index in range(len(normalized) - size + 1)
            )
        return grams

    def _text_overlap_ratio(self, left: str, right: str) -> float:
        left_grams = self._text_ngrams(left)
        right_grams = self._text_ngrams(right)
        if not left_grams or not right_grams:
            return 0.0
        return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))
