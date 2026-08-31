"""LoreCraft3000 FastAPI application.

Organized by responsibility:
  - app/main.py        app startup + route wiring
  - app/config.py      settings from .env
  - app/deps.py        shared dependencies (settings, templates, conn, storage)
  - app/db.py          SQLite connection helpers
  - app/migrate.py     migration runner
  - app/storage.py     content-addressed image storage
  - app/domain/        domain models
  - app/services/      business services (characters, styles, ref_sets)
  - app/routes/        route modules (characters, styles, ref_sets)
  - app/providers/     (later: provider adapters)
  - app/assembler/     (later: prompt assembler)
  - app/templates/     server-rendered Jinja2 templates
  - app/static/        static assets (CSS, vendored htmx)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.deps import settings
from app.migrate import run_migrations
from app.routes import characters as character_routes
from app.routes import ref_sets as ref_set_routes
from app.routes import styles as style_routes

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database (idempotent) and ensure store root exists."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.store_root.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.db_path)
    yield


app = FastAPI(title="LoreCraft3000", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(character_routes.router)
app.include_router(style_routes.router)
app.include_router(ref_set_routes.router)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Home route — a working landing page."""
    return (
        "<html><head><title>LoreCraft3000</title></head>"
        "<body><h1>LoreCraft3000</h1>"
        "<p>Local comic-panel generator with persistent character identity.</p>"
        "</body></html>"
    )


@app.get("/health")
def health() -> dict:
    """Health check."""
    return {"status": "ok"}
