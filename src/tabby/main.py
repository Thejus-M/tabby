import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tabby.config import get_settings
from tabby.routes import api, pages
from tabby.scan.ocr import load_engine
from tabby.share.store import ShareStore

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.store = ShareStore(settings.database_path, settings.share_ttl_days * 86400)
    await app.state.store.init()
    if not hasattr(app.state, "ocr"):  # tests inject a fake engine
        app.state.ocr = await asyncio.to_thread(load_engine, settings.ocr_threads)
    app.state.scan_slots = asyncio.Semaphore(settings.ocr_max_concurrency)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Tabby", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(api.router)
    app.include_router(pages.router)

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        # Served from the root so its scope covers the whole app.
        return FileResponse(STATIC / "js" / "sw.js", media_type="text/javascript")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    return app


app = create_app()
