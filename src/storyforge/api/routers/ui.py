from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from storyforge.api.artifacts import build_ui_bootstrap
from storyforge.api.schemas import UiBootstrapResponse
from storyforge.api.template_renderer import render_template


router = APIRouter(tags=["ui"])


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
@router.get("/ui", include_in_schema=False, response_class=HTMLResponse)
async def serve_console(request: Request) -> HTMLResponse:
    project_root = request.app.state.container.project_root
    template_root = project_root / "src" / "storyforge" / "api" / "templates"
    return HTMLResponse(render_template(template_root, "console.html"))


@router.get("/v1/ui/bootstrap", response_model=UiBootstrapResponse)
async def get_ui_bootstrap(request: Request) -> UiBootstrapResponse:
    config = request.app.state.container.config
    return build_ui_bootstrap(config)
