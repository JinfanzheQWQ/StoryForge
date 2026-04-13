from __future__ import annotations

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
    build_writer_system_prompt,
    build_writer_user_prompt,
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
        major_character_count: int = 3,
        structured_retry_attempts: int = 3,
    ) -> None:
        self.backend = backend or UnavailableAgentBackend(
            "NovelGeneratorService requires a live LLM backend."
        )
        self.chapter_scene_count = chapter_scene_count
        self.major_character_count = major_character_count
        self.structured_retry_attempts = max(1, structured_retry_attempts)

    def build_novel_package(self, brief: StoryBrief) -> NovelPackage:
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
        story_draft_context = build_story_draft_context(story_draft_chapters)

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
        chapters = self._build_chapters(
            brief,
            outline,
            cast_analysis,
            seed_chapters=story_draft_chapters,
        )
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
                "story_drafter": story_draft_set.model_dump(),
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

    def _build_chapters(
        self,
        brief: StoryBrief,
        outline: StoryOutline,
        cast_analysis: CastAnalysisSchema,
        seed_chapters: list[DraftChapter] | None = None,
    ) -> list[DraftChapter]:
        drafted: list[DraftChapter] = []
        seed_by_number = {item.number: item for item in (seed_chapters or [])}
        for chapter in outline.chapters:
            source_chapter = seed_by_number.get(chapter.number)
            chapter_payload = self._run_structured_agent(
                schema=ChapterDraftSchema,
                request=PromptRequest(
                    system_prompt=build_writer_system_prompt(),
                    user_prompt=build_writer_user_prompt(
                        brief=brief,
                        outline=outline,
                        chapter=chapter,
                        previous_chapters=drafted,
                        cast_analysis=cast_analysis,
                        source_chapter=source_chapter,
                    ),
                    metadata={"task": f"chapter-writer-{chapter.number:02d}"},
                ),
                fallback=(
                    self._chapter_schema_from_seed(source_chapter)
                    if source_chapter is not None
                    else self._fallback_chapter_draft(brief, outline, chapter)
                ),
            )
            drafted.append(
                DraftChapter(
                    number=chapter_payload.number,
                    title=chapter_payload.title,
                    markdown=chapter_payload.markdown,
                    summary=chapter_payload.summary,
                    agent_notes=f"goal={chapter.goal}",
                    visual_hooks=chapter_payload.visual_hooks,
                    continuity_refs=chapter_payload.continuity_refs,
                )
            )
        return drafted

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
    ) -> StructuredModelT:
        # Dry-run remains deterministic for tests and demos. Live LLM execution is
        # fail-fast: invalid structured output is retried, then raised explicitly.
        if isinstance(self.backend, DryRunAgentBackend):
            return fallback
        last_error: Exception | None = None
        for attempt in range(1, self.structured_retry_attempts + 1):
            attempt_request = self._build_retry_request(request, schema, attempt)
            try:
                response = self.backend.generate_structured(attempt_request, schema)
                if isinstance(response, schema):
                    return response
                return schema.model_validate(response)
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
    ) -> PromptRequest:
        if attempt <= 1:
            return request

        retry_note = (
            "\n\n上一次输出未通过结构化校验。"
            f"这是第 {attempt} 次尝试。"
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
