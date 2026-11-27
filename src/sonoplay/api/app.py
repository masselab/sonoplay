"""FastAPI application factory for Sonoplay."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Resolve paths relative to project root (where templates/ and static/ live)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI instance with routes and middleware
    """
    from sonoplay.api.routes.health import router as health_router, set_startup_time

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        set_startup_time(time.time())
        yield

    app = FastAPI(
        title="Sonoplay",
        description="Plex DLNA Player - Bridge Plex to DLNA/UPnP speakers",
        version="1.0.0",
        lifespan=lifespan,
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health_router)

    return app


# Templates instance for use by route handlers
templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None
