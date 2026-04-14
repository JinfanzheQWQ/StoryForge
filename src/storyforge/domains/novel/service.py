from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel

from storyforge.agents.base import (
    AgentBackend,
    AgentBackendUnavailableError,
    DryRunAgentBackend,
    PromptRequest,
    UnavailableAgentBackend,
)
from storyforge.domains.novel.contracts import (
    ChapterPlan,
    CharacterProfile,
    CharacterVoiceProfile,
    DraftChapter,
    EditorialReview,
    NovelPackage,
    StoryBrief,
    StorySourcePackage,
    StoryOutline,
)
from storyforge.domains.novel.errors import NovelStructuredGenerationError
from storyforge.domains.novel.fallbacks import NovelFallbackMixin
from storyforge.domains.novel.prompts import (
    build_architect_system_prompt,
    build_architect_user_prompt,
    build_story_drafter_system_prompt,
    build_story_drafter_user_prompt,
    build_story_draft_context,
    build_cast_system_prompt,
    build_cast_user_prompt,
    build_character_system_prompt,
    build_character_user_prompt,
    build_chapter_planner_system_prompt,
    build_chapter_planner_user_prompt,
    build_editor_system_prompt,
    build_editor_user_prompt,
)
from storyforge.domains.novel.repair import NovelRepairMixin
from storyforge.domains.novel.rules import NovelRuleMixin
from storyforge.domains.novel.schemas import (
    CastAnalysisSchema,
    ChapterDraftSchema,
    ChapterPlanSetSchema,
    CharacterRosterSchema,
    EditorialReviewSchema,
    StoryDraftSetSchema,
    StoryArchitectureSchema,
)


StructuredModelT = TypeVar("StructuredModelT", bound=BaseModel)


class NovelGeneratorService(
    NovelRepairMixin,
    NovelFallbackMixin,
    NovelRuleMixin,
):
    def __init__(
        self,
        backend: AgentBackend | None = None,
        chapter_scene_count: int = 3,
        structured_retry_attempts: int = 3,
    ) -> None:
        self.backend = backend or UnavailableAgentBackend(
            "NovelGeneratorService requires a live LLM backend."
        )
        self.chapter_scene_count = chapter_scene_count
        self.structured_retry_attempts = max(1, structured_retry_attempts)

    def build_novel_package(self, brief: StoryBrief) -> NovelPackage:
        story_source = self.build_story_source(brief)
        return self.build_novel_package_from_story_source(story_source)

    def build_story_source(self, brief: StoryBrief) -> StorySourcePackage:
        architecture = self._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt=build_architect_system_prompt(),
                user_prompt=build_architect_user_prompt(brief),
                metadata={"task": "story-architect"},
            ),
            fallback=self._fallback_architecture(brief),
        )

        story_draft_set = self._run_structured_agent(
            schema=StoryDraftSetSchema,
            request=PromptRequest(
                system_prompt=build_story_drafter_system_prompt(),
                user_prompt=build_story_drafter_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                ),
                metadata={"task": "story-drafter"},
            ),
            fallback=self._fallback_story_draft_set(brief, architecture),
        )
        story_draft_set = self._repair_story_draft_set(
            story_draft_set,
            brief,
            architecture,
        )
        story_draft_chapters = self._assemble_seed_chapters(story_draft_set)
        return StorySourcePackage(
            brief=brief,
            title=architecture.title.strip() or brief.title_hint,
            chapters=story_draft_chapters,
        )

    def build_novel_package_from_story_source(
        self,
        story_source: StorySourcePackage,
    ) -> NovelPackage:
        brief = story_source.brief
        story_draft_set = StoryDraftSetSchema(
            chapters=[self._chapter_schema_from_seed(item) for item in story_source.chapters]
        )
        story_draft_context = build_story_draft_context(story_source.chapters)

        architecture = self._run_structured_agent(
            schema=StoryArchitectureSchema,
            request=PromptRequest(
                system_prompt=build_architect_system_prompt(),
                user_prompt=build_architect_user_prompt(
                    brief,
                    story_draft_context=story_draft_context,
                ),
                metadata={"task": "story-architect-analysis"},
            ),
            fallback=self._fallback_architecture(brief),
        )

        # Agreement: LLM-based cast analysis is the primary source of truth
        # for role structure. Heuristics only remain as repair and fallback backstops.
        cast_analysis = self._run_structured_agent(
            schema=CastAnalysisSchema,
            request=PromptRequest(
                system_prompt=build_cast_system_prompt(),
                user_prompt=build_cast_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                    story_draft_context=story_draft_context,
                ),
                metadata={"task": "cast-analyzer"},
            ),
            fallback=self._fallback_cast_analysis(
                brief,
                architecture,
                story_draft_set=story_draft_set,
            ),
            validator=lambda value: self._validate_cast_analysis_output(
                value,
                story_draft_set=story_draft_set,
            ),
        )
        cast_analysis = self._repair_cast_analysis(
            cast_analysis,
            brief,
            architecture,
            story_draft_set=story_draft_set,
        )

        character_roster = self._run_structured_agent(
            schema=CharacterRosterSchema,
            request=PromptRequest(
                system_prompt=build_character_system_prompt(),
                user_prompt=build_character_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                    cast_analysis=cast_analysis,
                    story_draft_context=story_draft_context,
                ),
                metadata={"task": "character-designer"},
            ),
            fallback=self._fallback_character_roster(
                brief,
                architecture,
                cast_analysis=cast_analysis,
            ),
            validator=lambda value: self._validate_character_roster_output(
                value,
                cast_analysis=cast_analysis,
            ),
        )
        character_roster = self._repair_character_roster(
            character_roster,
            brief,
            architecture,
            cast_analysis=cast_analysis,
        )

        chapter_plan_set = self._run_structured_agent(
            schema=ChapterPlanSetSchema,
            request=PromptRequest(
                system_prompt=build_chapter_planner_system_prompt(),
                user_prompt=build_chapter_planner_user_prompt(
                    brief=brief,
                    architecture_summary=architecture.model_dump_json(ensure_ascii=False),
                    character_summary=character_roster.model_dump_json(ensure_ascii=False),
                    cast_analysis=cast_analysis,
                    story_draft_context=story_draft_context,
                ),
                metadata={"task": "chapter-planner"},
            ),
            fallback=self._fallback_chapter_plan_set(
                brief,
                character_roster,
                cast_analysis=cast_analysis,
                story_draft_set=story_draft_set,
            ),
        )
        chapter_plan_set = self._repair_chapter_plan_set(
            chapter_plan_set,
            brief,
            character_roster,
            cast_analysis=cast_analysis,
            story_draft_set=story_draft_set,
        )

        outline = self._assemble_outline(architecture, character_roster, chapter_plan_set)
        chapters = list(story_source.chapters)
        review = self._run_structured_agent(
            schema=EditorialReviewSchema,
            request=PromptRequest(
                system_prompt=build_editor_system_prompt(),
                user_prompt=build_editor_user_prompt(brief, outline, chapters),
                metadata={"task": "editor-review"},
            ),
            fallback=self._fallback_editorial_review(outline, chapters),
        )

        return NovelPackage(
            brief=brief,
            outline=outline,
            chapters=chapters,
            review=EditorialReview(
                overall_verdict=review.overall_verdict,
                strengths=review.strengths,
                continuity_risks=review.continuity_risks,
                revision_notes=review.revision_notes,
            ),
            workflow_trace={
                "story_architect": architecture.model_dump(),
                "story_drafter": {
                    "source": "story_source",
                    "title": story_source.title,
                    "chapter_count": len(story_source.chapters),
                },
                "story_source": {
                    "title": story_source.title,
                    "chapter_count": len(story_source.chapters),
                },
                "cast_analyzer": cast_analysis.model_dump(),
                "character_designer": character_roster.model_dump(),
                "chapter_planner": chapter_plan_set.model_dump(),
                "editor_review": review.model_dump(),
            },
        )

    def _assemble_outline(
        self,
        architecture: StoryArchitectureSchema,
        roster: CharacterRosterSchema,
        chapter_plan_set: ChapterPlanSetSchema,
    ) -> StoryOutline:
        return StoryOutline(
            title=architecture.title,
            premise=architecture.premise,
            theme=architecture.theme,
            visual_motifs=architecture.visual_motifs,
            characters=[
                CharacterProfile(
                    cast_slot_id=item.cast_slot_id,
                    name=item.name,
                    role=item.role,
                    gender=item.gender,
                    desire=item.desire,
                    conflict=item.conflict,
                    arc=item.arc,
                    visual_signature=item.visual_signature,
                    voice_style=item.voice_style or item.voice_profile.voice_style,
                    voice_profile=CharacterVoiceProfile.from_dict(
                        item.voice_profile.model_dump()
                    ),
                    image_prompt=item.image_prompt,
                )
                for item in roster.characters
            ],
            chapters=[
                ChapterPlan(
                    number=item.number,
                    title=item.title,
                    summary=item.summary,
                    key_conflict=item.key_conflict,
                    beats=item.beats,
                    cliffhanger=item.cliffhanger,
                    goal=item.goal,
                    featured_characters=item.featured_characters,
                )
                for item in chapter_plan_set.chapters
            ],
            agent_notes=(
                f"setting={architecture.setting}\n"
                f"story_engine={architecture.story_engine}\n"
                f"tone_notes={', '.join(architecture.tone_notes)}"
            ),
        )

    def _assemble_seed_chapters(
        self,
        story_draft_set: StoryDraftSetSchema,
    ) -> list[DraftChapter]:
        return [
            DraftChapter(
                number=item.number,
                title=item.title,
                markdown=item.markdown,
                summary=item.summary,
                agent_notes="seed-draft",
                visual_hooks=item.visual_hooks,
                continuity_refs=item.continuity_refs,
            )
            for item in story_draft_set.chapters
        ]

    def _chapter_schema_from_seed(
        self,
        source_chapter: DraftChapter,
    ) -> ChapterDraftSchema:
        return ChapterDraftSchema(
            number=source_chapter.number,
            title=source_chapter.title,
            summary=source_chapter.summary,
            markdown=source_chapter.markdown,
            visual_hooks=source_chapter.visual_hooks,
            continuity_refs=source_chapter.continuity_refs,
        )

    def _run_structured_agent(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        fallback: StructuredModelT,
        validator: Callable[[StructuredModelT], StructuredModelT] | None = None,
    ) -> StructuredModelT:
        # Dry-run remains deterministic for tests and demos. Live LLM execution is
        # fail-fast: invalid structured output is retried, then raised explicitly.
        if isinstance(self.backend, DryRunAgentBackend):
            return fallback
        last_error: Exception | None = None
        for attempt in range(1, self.structured_retry_attempts + 1):
            attempt_request = self._build_retry_request(
                request,
                schema,
                attempt,
                last_error,
            )
            try:
                response = self.backend.generate_structured(attempt_request, schema)
                candidate = response if isinstance(response, schema) else schema.model_validate(response)
                if validator is not None:
                    return validator(candidate)
                return candidate
            except AgentBackendUnavailableError:
                raise
            except Exception as exc:
                last_error = exc

        raise NovelStructuredGenerationError(
            task=str(request.metadata.get("task", "structured-agent")),
            schema_name=schema.__name__,
            attempts=self.structured_retry_attempts,
            cause=last_error or RuntimeError("unknown structured generation failure"),
        )

    def _build_retry_request(
        self,
        request: PromptRequest,
        schema: type[StructuredModelT],
        attempt: int,
        last_error: Exception | None = None,
    ) -> PromptRequest:
        if attempt <= 1:
            return request

        error_text = ""
        if last_error is not None:
            normalized_error = " ".join(str(last_error).split())
            if normalized_error:
                error_text = f"失败原因：{normalized_error}。"
        retry_note = (
            "\n\n上一次输出未通过结构化校验。"
            f"这是第 {attempt} 次尝试。"
            f"{error_text}"
            f"请严格按 {schema.__name__} 对应结构返回，不要输出解释，不要输出 Markdown 代码块，"
            "不要遗漏字段。"
        )
        metadata = dict(request.metadata)
        metadata["structured_retry_attempt"] = attempt
        return PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt + retry_note,
            metadata=metadata,
        )

    def _validate_cast_analysis_output(
        self,
        analysis: CastAnalysisSchema,
        *,
        story_draft_set: StoryDraftSetSchema,
    ) -> CastAnalysisSchema:
        story_text = self._normalize_story_evidence_text(
            self._story_draft_text(story_draft_set)
        )
        if not story_text:
            return analysis

        unsupported_slots: list[str] = []
        for slot in analysis.slots:
            evidence_tokens = [
                item.strip()
                for item in slot.source_evidence
                if item.strip()
            ]
            if not evidence_tokens:
                unsupported_slots.append(f"{slot.slot_id}:{slot.brief_label}")
                continue
            if not any(self._story_evidence_supported(token, story_text) for token in evidence_tokens):
                unsupported_slots.append(f"{slot.slot_id}:{slot.brief_label}")

        if unsupported_slots:
            raise ValueError(
                "以下 cast slot 缺少可在小说正文中定位的 source_evidence："
                + "、".join(unsupported_slots)
            )
        return analysis

    def _validate_character_roster_output(
        self,
        roster: CharacterRosterSchema,
        *,
        cast_analysis: CastAnalysisSchema,
    ) -> CharacterRosterSchema:
        expected_slots = [
            item.slot_id
            for item in cast_analysis.primary_slots(
                max(1, cast_analysis.recommended_core_cast_count)
            )
        ]
        actual_slots = [item.cast_slot_id.strip() for item in roster.characters]

        if len(actual_slots) != len(expected_slots):
            raise ValueError(
                f"角色数量必须与目标 slots 数一致。期望 {len(expected_slots)} 个，实际 {len(actual_slots)} 个。"
            )
        if actual_slots != expected_slots:
            raise ValueError(
                "角色 cast_slot_id 必须与上游 slots 完全一致且顺序一致。"
                f"期望：{expected_slots}；实际：{actual_slots}。"
            )
        return roster

    def _normalize_story_evidence_text(self, text: str) -> str:
        return "".join(text.split())

    def _story_evidence_supported(
        self,
        evidence: str,
        normalized_story_text: str,
    ) -> bool:
        normalized_evidence = self._normalize_story_evidence_text(evidence)
        if len(normalized_evidence) < 2:
            return False
        return normalized_evidence in normalized_story_text
