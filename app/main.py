"""LoreCraft3000 FastAPI application.

Organized by responsibility:
  - app/main.py        app startup + routes
  - app/config.py      settings from .env
  - app/db.py          SQLite connection helpers
  - app/migrate.py     migration runner
  - app/storage.py     content-addressed image storage
  - app/domain/        (later: domain models/services)
  - app/services/      (later: business services)
  - app/providers/     (later: provider adapters)
  - app/assembler/     (later: prompt assembler)
  - app/templates/     (later: server-rendered templates)
  - app/static/        (later: static assets)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.migrate import run_migrations

settings = Settings.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database (idempotent) and ensure store root exists."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.store_root.mkdir(parents=True, exist_ok=True)
    run_migrations(settings.db_path)
    yield


app = FastAPI(title="LoreCraft3000", lifespan=lifespan)


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
