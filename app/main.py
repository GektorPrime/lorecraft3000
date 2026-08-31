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
  - app/providers/     provider adapters
  - app/assembler/     multi-character prompt assembler
  - app/templates/     server-rendered Jinja2 templates
  - app/static/        static assets (CSS, vendored htmx)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.deps import settings, templates
from app.migrate import run_migrations
from app.routes import api_v1
from app.routes import characters as character_routes
from app.routes import ref_sets as ref_set_routes
from app.routes import scenes as scene_routes
from app.routes import styles as style_routes

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The built React frontend (`npm run build` in frontend/, issue #15). Serving
# it is entirely optional: with no build present, the app falls back to the
# legacy server-rendered Jinja UI (app/templates/), kept for compatibility.
# When frontend/dist exists it becomes the primary UI at "/". The frontend
# uses hash-based client-side routing (e.g. "/#/characters") specifically so
# its internal routes never collide with the legacy Jinja routes registered
# below at the same-looking paths (e.g. GET /characters) — a hash fragment is
# never sent to the server, so a browser refresh on any React route still
# resolves to "/" and re-renders client-side. In dev, Vite's dev server
# proxies /api to this backend instead (see frontend/vite.config.ts).
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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
app.include_router(scene_routes.router)
app.include_router(api_v1.router)

if (FRONTEND_DIST_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")),
        name="frontend-assets",
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Landing page for the library-to-panel workflow.

    Serves the built React app (see frontend/) when present; otherwise falls
    back to the legacy server-rendered Jinja landing page so the app still
    runs without a frontend build.
    """
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return templates.TemplateResponse(request, "home.html", {})


@app.get("/health")
def health() -> dict:
    """Health check."""
    return {"status": "ok"}
