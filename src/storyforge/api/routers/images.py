from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from storyforge.api.schemas import CreateImageGenerationRequest, JobAcceptedResponse
from storyforge.application.tasks import utc_now


router = APIRouter(prefix="/v1/images", tags=["images"])

IMAGE_PROJECT_KIND = "image_generation"


@router.post("/generations", response_model=JobAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_image_generation_job(
    payload: CreateImageGenerationRequest,
    request: Request,
) -> JobAcceptedResponse:
    container = request.app.state.container
    project = container.project_store.create(_image_generation_brief(payload))
    task_payload = payload.model_dump()
    record = await container.task_queue.submit(
        project_id=project.project_id,
        task_type="image.generate",
        payload=task_payload,
    )
    container.project_store.attach_task(project.project_id, record.task_id, project.brief)
    return JobAcceptedResponse(
        project_id=project.project_id,
        task_id=record.task_id,
        status=record.status,
    )


@router.get("/capabilities")
async def get_image_generation_capabilities(request: Request) -> dict[str, object]:
    container = request.app.state.container
    gpt_provider = container.config.gpt_image.provider.strip().lower()
    return {
        "models": [
            {
                "label": "GPT Image 2",
                "value": container.config.gpt_image.model,
                "size_options": _gpt_image_size_options(gpt_provider),
            },
            {
                "label": "Seedream 4.5",
                "value": container.config.seedream.model,
                "size_options": [
                    {
                        "label": "2K",
                        "value": "2K",
                        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
                    },
                    {
                        "label": "4K",
                        "value": "4K",
                        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
                    },
                ],
            },
        ],
    }


@router.post("/generations/{task_id}/save", response_model=JobAcceptedResponse)
async def save_image_generation_job(task_id: str, request: Request) -> JobAcceptedResponse:
    container = request.app.state.container
    task = container.task_queue.store.get(task_id)
    if task is None or task.task_type != "image.generate":
        raise HTTPException(status_code=404, detail=f"Image generation task {task_id} not found")
    if task.status != "completed" or not task.result:
        raise HTTPException(status_code=409, detail="Image generation is not completed yet.")
    project = container.project_store.get(task.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {task.project_id} not found")

    brief = dict(project.brief)
    brief["project_kind"] = IMAGE_PROJECT_KIND
    brief["image_saved"] = True
    container.project_store.attach_task(project.project_id, task.task_id, brief)
    container.task_queue.store.update_result(
        task.task_id,
        {
            **task.result,
            "image_saved": True,
            "artifact_revision": utc_now(),
        },
    )
    return JobAcceptedResponse(
        project_id=project.project_id,
        task_id=task.task_id,
        status=task.status,
    )


def _image_generation_brief(payload: CreateImageGenerationRequest) -> dict[str, object]:
    title = _image_generation_title(payload)
    return {
        "title_hint": title,
        "idea": payload.prompt,
        "genre": "图像生成",
        "tone": "清新科技感",
        "target_audience": "创作者",
        "chapter_count": 1,
        "total_word_target": 300,
        "must_include": [],
        "style_keywords": [_image_generation_model_label(payload.model)],
        "project_kind": IMAGE_PROJECT_KIND,
        "image_saved": False,
        "image_mode": payload.mode,
        "image_model": payload.model or "",
        "image_size": payload.size or "",
        "image_aspect_ratio": payload.aspect_ratio or "",
    }


def _image_generation_title(payload: CreateImageGenerationRequest) -> str:
    prefix = "图生图" if payload.mode == "image_to_image" else "文生图"
    compact_prompt = " ".join(payload.prompt.split())
    if not compact_prompt:
        return prefix
    return f"{prefix} · {compact_prompt[:24]}"


def _image_generation_model_label(model: str | None) -> str:
    if model == "doubao-seedream-4-5-251128":
        return "Seedream 4.5"
    return "GPT Image 2"


def _gpt_image_size_options(provider: str) -> list[dict[str, object]]:
    if provider == "openai":
        return [
            {"label": "自动", "value": "auto", "aspect_ratios": ["auto"]},
            {"label": "1K", "value": "1K", "aspect_ratios": ["1:1", "3:2", "2:3"]},
        ]
    return [
        {"label": "1K", "value": "1K", "aspect_ratios": ["auto", "1:1", "9:16", "16:9", "4:3", "3:4"]},
        {"label": "2K", "value": "2K", "aspect_ratios": ["1:1", "9:16", "16:9", "4:3", "3:4"]},
        {"label": "4K", "value": "4K", "aspect_ratios": ["9:16", "16:9", "4:3", "3:4"]},
        {"label": "自动", "value": "auto", "aspect_ratios": ["auto"]},
    ]
