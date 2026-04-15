from __future__ import annotations

from collections.abc import Callable
import re
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
    build_character_slot_contract,
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
COMMON_CHINESE_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费"
    "廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和"
    "穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜"
    "阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞"
    "万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程"
    "嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧"
    "隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶"
    "幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻"
    "莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温"
    "别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡"
    "国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾"
    "沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公仉督岳帅缑亢况郈有琴"
    "归海晋楚闫法汝鄢涂钦岳帅哈墨"
)
NAME_LIKE_PATTERN = re.compile(rf"[{COMMON_CHINESE_SURNAMES}][\u4e00-\u9fff]{{1,2}}")
EVIDENCE_SPLIT_PATTERN = re.compile(r"[，、/|；;,.。！？!?\s]+")
EVIDENCE_PREFIX_PATTERN = re.compile(
    r"^(?:一名|一个|一位|这位|那位|这个|那个|年轻|年少|年长|青年|中年|少年|少女|成年|新来的|刚来的|普通的|某个)+"
)


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
                metadata={
                    "task": "character-designer",
                    "expected_character_count": len(
                        cast_analysis.primary_slots(
                            max(1, cast_analysis.recommended_core_cast_count)
                        )
                    ),
                    "expected_cast_slot_ids": [
                        item.slot_id
                        for item in cast_analysis.primary_slots(
                            max(1, cast_analysis.recommended_core_cast_count)
                        )
                    ],
                    "character_slot_contract": build_character_slot_contract(
                        cast_analysis.primary_slots(
                            max(1, cast_analysis.recommended_core_cast_count)
                        )
                    ),
                },
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
                candidate = self._coerce_structured_response(response, schema)
                if validator is not None:
                    try:
                        return validator(candidate)
                    except Exception as exc:
                        supplemental = self._attempt_structured_completion(
                            schema=schema,
                            request=attempt_request,
                            candidate=candidate,
                            validator=validator,
                            error=exc,
                        )
                        if supplemental is not None:
                            return supplemental
                        raise
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
        if request.metadata.get("task") == "character-designer":
            expected_count = request.metadata.get("expected_character_count")
            expected_slot_ids = request.metadata.get("expected_cast_slot_ids") or []
            slot_contract = str(request.metadata.get("character_slot_contract") or "").strip()
            retry_note += (
                "\n\n角色表修复合同：本次必须重新输出完整 characters 数组，"
                "不要沿用上一次的角色数量。"
            )
            if expected_count:
                retry_note += f" characters 数组长度必须恰好等于 {expected_count}。"
            if expected_slot_ids:
                retry_note += (
                    " cast_slot_id 必须按这个顺序逐项输出："
                    + "、".join(str(item) for item in expected_slot_ids)
                    + "。"
                )
            if slot_contract:
                retry_note += "\n固定索引合同如下，必须逐行满足：\n" + slot_contract
        metadata = dict(request.metadata)
        metadata["structured_retry_attempt"] = attempt
        return PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt + retry_note,
            metadata=metadata,
        )

    def _attempt_structured_completion(
        self,
        schema: type[StructuredModelT],
        request: PromptRequest,
        candidate: StructuredModelT,
        validator: Callable[[StructuredModelT], StructuredModelT],
        error: Exception,
    ) -> StructuredModelT | None:
        if schema is not CharacterRosterSchema:
            return None
        if request.metadata.get("task") != "character-designer":
            return None
        error_text = str(error)
        if "角色数量必须与目标 slots 数一致" not in error_text and "角色 cast_slot_id 必须与上游 slots 完全一致且顺序一致" not in error_text:
            return None
        return self._complete_character_roster_from_partial(
            request=request,
            candidate=candidate,
            validator=validator,
        )

    def _complete_character_roster_from_partial(
        self,
        request: PromptRequest,
        candidate: StructuredModelT,
        validator: Callable[[StructuredModelT], StructuredModelT],
    ) -> StructuredModelT | None:
        if not isinstance(candidate, CharacterRosterSchema):
            return None

        expected_slot_ids = [
            str(item).strip()
            for item in request.metadata.get("expected_cast_slot_ids", [])
            if str(item).strip()
        ]
        if not expected_slot_ids:
            return None

        existing_by_slot = {
            item.cast_slot_id.strip(): item
            for item in candidate.characters
            if item.cast_slot_id.strip() in expected_slot_ids
        }
        if all(slot_id in existing_by_slot for slot_id in expected_slot_ids):
            reordered = CharacterRosterSchema(
                characters=[existing_by_slot[slot_id] for slot_id in expected_slot_ids]
            )
            return validator(reordered)  # type: ignore[return-value]

        missing_slot_ids = [
            slot_id for slot_id in expected_slot_ids
            if slot_id not in existing_by_slot
        ]
        if not missing_slot_ids:
            return None

        slot_contract = str(request.metadata.get("character_slot_contract", "")).strip()
        missing_contract_lines = [
            line
            for line in slot_contract.splitlines()
            if any(f"\"{slot_id}\"" in line for slot_id in missing_slot_ids)
        ]
        existing_summary = "\n".join(
            f"- {item.cast_slot_id} -> {item.name} | {item.role} | {item.gender}"
            for item in candidate.characters
        ) or "- 无"
        missing_contract = "\n".join(missing_contract_lines) or (
            "- 缺失 slots：" + "、".join(missing_slot_ids)
        )
        follow_up_request = PromptRequest(
            system_prompt=request.system_prompt,
            user_prompt=(
                f"{request.user_prompt}\n\n"
                "上一次你只成功输出了部分角色。以下角色已经成功输出，请不要重写它们，也不要改它们的名字和 cast_slot_id：\n"
                f"{existing_summary}\n\n"
                "现在只补全缺失角色。"
                f"\n缺失 slots：{'、'.join(missing_slot_ids)}。"
                f"\n这次返回的 characters 数组长度必须恰好等于 {len(missing_slot_ids)}，"
                "并且 characters 数组里只能包含缺失角色，不要包含已经完成的 slots。"
                "\n缺失 slot 固定索引合同如下：\n"
                f"{missing_contract}"
            ),
            metadata={
                **request.metadata,
                "task": "character-designer-backfill",
            },
        )
        supplemental = self.backend.generate_structured(follow_up_request, CharacterRosterSchema)
        supplemental_roster = self._coerce_structured_response(supplemental, CharacterRosterSchema)

        combined_by_slot = dict(existing_by_slot)
        for item in supplemental_roster.characters:
            slot_id = item.cast_slot_id.strip()
            if slot_id not in missing_slot_ids:
                continue
            combined_by_slot[slot_id] = item

        if not all(slot_id in combined_by_slot for slot_id in expected_slot_ids):
            unresolved = [
                slot_id for slot_id in expected_slot_ids
                if slot_id not in combined_by_slot
            ]
            raise ValueError(
                "角色补全后仍然缺少目标 slots："
                + "、".join(unresolved)
            )

        completed = CharacterRosterSchema(
            characters=[combined_by_slot[slot_id] for slot_id in expected_slot_ids]
        )
        return validator(completed)  # type: ignore[return-value]

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
        candidates = self._story_evidence_candidates(evidence)
        if not candidates:
            return False
        return any(candidate in normalized_story_text for candidate in candidates)

    def _story_evidence_candidates(self, evidence: str) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        def append(token: str) -> None:
            normalized = self._normalize_story_evidence_text(token)
            if len(normalized) < 2 or normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        append(evidence)
        for fragment in EVIDENCE_SPLIT_PATTERN.split(evidence):
            if not fragment.strip():
                continue
            append(fragment)
            simplified = self._strip_story_evidence_prefix(fragment)
            append(simplified)

            for name_like in NAME_LIKE_PATTERN.findall(fragment):
                append(name_like)
                without_name = simplified.replace(name_like, "")
                append(without_name)
                append(self._strip_story_evidence_prefix(without_name))
        return candidates

    def _strip_story_evidence_prefix(self, text: str) -> str:
        normalized = self._normalize_story_evidence_text(text)
        if not normalized:
            return ""
        previous = normalized
        current = EVIDENCE_PREFIX_PATTERN.sub("", previous)
        while current != previous:
            previous = current
            current = EVIDENCE_PREFIX_PATTERN.sub("", previous)
        return current
