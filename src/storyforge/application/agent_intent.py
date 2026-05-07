from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from storyforge.agents.base import AgentBackend, AgentBackendUnavailableError, PromptRequest
from storyforge.core.config import AppConfig
from storyforge.integrations.llm import build_agent_backend


DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "2K"
DEFAULT_IMAGE_ASPECT_RATIO = "16:9"
DEFAULT_VIDEO_MODE = "grid_storyboard"
DEFAULT_CHAPTER_COUNT = 1
DEFAULT_TOTAL_WORD_TARGET = 1200


class AgentIntentPlanningError(RuntimeError):
    pass


@dataclass(slots=True)
class AgentIntentPlan:
    brief: dict[str, Any]
    settings: dict[str, Any]
    plan: dict[str, Any]
    assistant_message: str


class AgentIntentBriefSchema(BaseModel):
    title_hint: str = Field(min_length=1, max_length=80, description="项目标题建议")
    idea: str = Field(min_length=1, max_length=20000, description="忠实保留并整理后的用户核心创意")
    genre: str = Field(min_length=1, max_length=80, description="由 LLM 判断的题材/类型，不使用代码枚举")
    tone: str = Field(min_length=1, max_length=160, description="由 LLM 判断的整体基调、风格和气质")
    target_audience: str = Field(min_length=1, max_length=120, description="目标观众")
    chapter_count: int = Field(ge=1, le=12, description="小说章节数")
    total_word_target: int = Field(ge=300, le=50000, description="小说正文总字数目标")
    must_include: list[str] = Field(min_length=1, max_length=12, description="用户明确或隐含要求必须包含的内容")
    style_keywords: list[str] = Field(min_length=1, max_length=12, description="由 LLM 提取的风格关键词")

    @model_validator(mode="after")
    def normalize_text_fields(self) -> "AgentIntentBriefSchema":
        self.title_hint = _clean_text(self.title_hint)[:80]
        self.idea = _clean_text(self.idea)
        self.genre = _clean_text(self.genre)[:80]
        self.tone = _clean_text(self.tone)[:160]
        self.target_audience = _clean_text(self.target_audience)[:120]
        self.must_include = _clean_list(self.must_include, limit=12, item_limit=120)
        self.style_keywords = _clean_list(self.style_keywords, limit=12, item_limit=80)
        if not all(
            [
                self.title_hint,
                self.idea,
                self.genre,
                self.tone,
                self.target_audience,
                self.must_include,
                self.style_keywords,
            ]
        ):
            raise ValueError("Agent intent brief contains empty semantic fields.")
        return self


class AgentIntentSettingsSchema(BaseModel):
    video_mode: Literal["direct_motion", "grid_storyboard"] = DEFAULT_VIDEO_MODE
    image_model: str = Field(default=DEFAULT_IMAGE_MODEL, max_length=120)
    image_size: str = Field(default=DEFAULT_IMAGE_SIZE, max_length=32)
    image_aspect_ratio: str = Field(default=DEFAULT_IMAGE_ASPECT_RATIO, max_length=16)
    seedream_watermark: bool = False
    seedance_watermark: bool = False

    @model_validator(mode="after")
    def normalize_values(self) -> "AgentIntentSettingsSchema":
        self.image_model = _clean_text(self.image_model) or DEFAULT_IMAGE_MODEL
        self.image_size = _clean_text(self.image_size) or DEFAULT_IMAGE_SIZE
        self.image_aspect_ratio = _clean_text(self.image_aspect_ratio) or DEFAULT_IMAGE_ASPECT_RATIO
        return self


class AgentIntentStructuredPlanSchema(BaseModel):
    brief: AgentIntentBriefSchema
    settings: AgentIntentSettingsSchema = Field(description="受控生产设置")
    plan_summary: str = Field(min_length=1, max_length=500, description="给用户看的计划摘要")
    steps: list[str] = Field(min_length=8, max_length=12, description="计划执行步骤")
    assistant_message: str = Field(min_length=1, max_length=1000, description="等待确认时展示的 Agent 回复")

    @model_validator(mode="after")
    def normalize_plan(self) -> "AgentIntentStructuredPlanSchema":
        self.plan_summary = _clean_text(self.plan_summary)[:500]
        self.steps = _clean_list(self.steps, limit=12, item_limit=80)
        self.assistant_message = _clean_text(self.assistant_message)[:1000]
        if len(self.steps) < 8:
            raise ValueError("Agent intent plan must include the full production pipeline steps.")
        return self


class AgentIntentPlanner:
    def __init__(
        self,
        *,
        config: AppConfig,
        backend: AgentBackend | None = None,
        structured_retry_attempts: int = 3,
    ) -> None:
        self._config = config
        self._backend = backend
        self._structured_retry_attempts = max(1, structured_retry_attempts)

    def build_plan(self, prompt: str, settings: dict[str, Any] | None = None) -> AgentIntentPlan:
        clean_prompt = _clean_text(prompt)
        if not clean_prompt:
            raise ValueError("创意内容不能为空。")

        explicit_settings = dict(settings or {})
        default_settings = self._resolve_settings(explicit_settings)
        structured = self._generate_structured_plan(clean_prompt, default_settings, explicit_settings)
        resolved_settings = self._resolve_settings(
            {
                **structured.settings.model_dump(),
                **_explicit_setting_overrides(explicit_settings),
            }
        )
        brief = {
            **structured.brief.model_dump(),
            "video_mode": resolved_settings["video_mode"],
            "image_model": resolved_settings["image_model"],
            "image_size": resolved_settings["image_size"],
            "image_aspect_ratio": resolved_settings["image_aspect_ratio"],
            "storyboard_image_model": resolved_settings["image_model"],
            "storyboard_size": resolved_settings["image_size"],
            "storyboard_aspect_ratio": resolved_settings["image_aspect_ratio"],
        }
        plan = {
            "steps": structured.steps,
            "summary": structured.plan_summary,
        }
        return AgentIntentPlan(
            brief=brief,
            settings=resolved_settings,
            plan=plan,
            assistant_message=structured.assistant_message,
        )

    def _generate_structured_plan(
        self,
        prompt: str,
        default_settings: dict[str, Any],
        explicit_settings: dict[str, Any],
    ) -> AgentIntentStructuredPlanSchema:
        request = PromptRequest(
            system_prompt=_AGENT_INTENT_SYSTEM_PROMPT,
            user_prompt=_build_agent_intent_user_prompt(
                prompt=prompt,
                default_settings=default_settings,
                explicit_settings=explicit_settings,
            ),
            metadata={"task": "agent-intent-planner"},
        )
        last_error: Exception | None = None
        for attempt in range(1, self._structured_retry_attempts + 1):
            attempt_request = _build_retry_request(request, attempt, last_error)
            try:
                response = self._backend_or_build(explicit_settings).generate_structured(
                    attempt_request,
                    AgentIntentStructuredPlanSchema,
                )
                if isinstance(response, AgentIntentStructuredPlanSchema):
                    return response
                return AgentIntentStructuredPlanSchema.model_validate(response)
            except AgentBackendUnavailableError as exc:
                raise AgentIntentPlanningError(str(exc)) from exc
            except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
                last_error = exc
        raise AgentIntentPlanningError(
            "Agent 意图解析结构化失败："
            f"{last_error or 'LLM did not return a valid structured plan.'}"
        )

    def _backend_or_build(self, settings: dict[str, Any]) -> AgentBackend:
        if self._backend is not None:
            return self._backend
        return build_agent_backend(
            self._config,
            use_llm=True,
            provider=_clean_text(settings.get("llm_provider")) or None,
            model=_clean_text(settings.get("llm_model")) or None,
        )

    def _resolve_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        resolved = {
            "video_mode": _clean_text(settings.get("video_mode")) or DEFAULT_VIDEO_MODE,
            "image_model": _clean_text(settings.get("image_model")) or DEFAULT_IMAGE_MODEL,
            "image_size": _clean_text(settings.get("image_size")) or DEFAULT_IMAGE_SIZE,
            "image_aspect_ratio": _clean_text(settings.get("image_aspect_ratio")) or DEFAULT_IMAGE_ASPECT_RATIO,
            "seedream_watermark": bool(settings.get("seedream_watermark", False)),
            "seedance_watermark": bool(settings.get("seedance_watermark", False)),
        }
        llm_provider = _clean_text(settings.get("llm_provider"))
        llm_model = _clean_text(settings.get("llm_model"))
        if llm_provider:
            resolved["llm_provider"] = llm_provider
        if llm_model:
            resolved["llm_model"] = llm_model
        return resolved


_AGENT_INTENT_SYSTEM_PROMPT = """你是 StoryForge 的 Agent 生产计划解析器。
你的唯一任务：把用户的自然语言创意结构化为小说转视频生产计划。

硬性规则：
- 必须根据用户原文理解题材、风格、人物、地点、情绪和必须包含内容。
- 不要套用固定题材模板，不要把未提及的风格强加给用户。
- 用户没有明确指定的生产参数，使用后端提供的默认值。
- 只输出结构化对象，不要执行工具，不要编造文件路径，不要承诺已经生成产物。
- 计划步骤必须覆盖：小说正文、场景结构、分段合同、角色图、场景母图、九宫格分镜图、分段视频、合并成片。
- assistant_message 用简洁中文告诉用户你理解的题材、风格、画面比例、生图模型，并询问是否开始。
"""


def _build_agent_intent_user_prompt(
    *,
    prompt: str,
    default_settings: dict[str, Any],
    explicit_settings: dict[str, Any],
) -> str:
    return (
        "请把下面用户创意解析为 StoryForge 自动创作计划。\n\n"
        f"用户创意：\n{prompt}\n\n"
        "后端默认生产参数：\n"
        f"{json.dumps(default_settings, ensure_ascii=False, indent=2)}\n\n"
        "用户显式选择的生产参数，必须优先遵守：\n"
        f"{json.dumps(_explicit_setting_overrides(explicit_settings), ensure_ascii=False, indent=2)}\n\n"
        "默认语义建议：若用户没有指定章节数，chapter_count=1；"
        "若用户没有指定字数，total_word_target=1200。"
        "genre、tone、must_include、style_keywords 必须来自你对用户创意的理解。"
    )


def _build_retry_request(
    request: PromptRequest,
    attempt: int,
    last_error: Exception | None,
) -> PromptRequest:
    if attempt <= 1:
        return request
    return PromptRequest(
        system_prompt=request.system_prompt,
        user_prompt=(
            f"{request.user_prompt}\n\n"
            "上一次结构化输出不符合 schema 或业务约束，请重新输出完整合法对象。\n"
            f"错误：{_clean_text(last_error)}"
        ),
        metadata={**request.metadata, "structured_retry_attempt": attempt},
    )


def _explicit_setting_overrides(settings: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "video_mode",
        "image_model",
        "image_size",
        "image_aspect_ratio",
        "seedream_watermark",
        "seedance_watermark",
        "llm_provider",
        "llm_model",
    }
    return {key: value for key, value in settings.items() if key in allowed_keys and value is not None}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_list(values: list[str], *, limit: int, item_limit: int) -> list[str]:
    cleaned: list[str] = []
    for raw_item in values:
        item = _clean_text(raw_item)[:item_limit]
        if item and item not in cleaned:
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned
