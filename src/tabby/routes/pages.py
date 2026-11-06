from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "app.html")


@router.get("/s", response_class=HTMLResponse)
@router.get("/s/{code}", response_class=HTMLResponse)
async def shared(request: Request, code: str | None = None):
    # The page fetches the split itself; for /s#... links the bill lives only in the URL fragment.
    return templates.TemplateResponse(request, "shared.html", {"code": (code or "").upper()})
