"""LoreCraft3000 FastAPI application.

Organized by responsibility:
  - app/main.py        app startup + route wiring
  - app/config.py      settings from .env
  - app/deps.py        shared dependencies (settings, conn, storage)
  - app/db.py          SQLite connection helpers
  - app/migrate.py     migration runner
  - app/storage.py     content-addressed image storage
  - app/maintenance.py storage consistency scan + repair CLI
  - app/domain/        domain models
  - app/models.py      model capability and pricing registry
  - app/services/      business services (characters, styles, ref_sets, ...)
  - app/routes/        /api/v1 resource routers
  - app/providers/     provider adapters
  - app/assembler/     multi-character prompt assembler

The React frontend (frontend/) is the only UI. Serving it is fully optional at
runtime: with no build present, "/" returns a short notice pointing at
`npm run build` instead of a second interface.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.deps import settings
from app.db import connect
from app.health import readiness_report
from app.middleware import LocalRequestGuardMiddleware
from app.migrate import run_migrations
from app.routes import api_v1
from app.services.costs import CostLedger

logger = logging.getLogger("lorecraft")

# The built React frontend (`npm run build` in frontend/). The app serves it at
# "/" when present. If it is absent, "/" returns a short notice instructing the
# operator to build it.
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database (idempotent) and ensure store root exists."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.store_root.mkdir(parents=True, exist_ok=True)
    run_migrations(
        settings.db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )
    conn = connect(
        settings.db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )
    try:
        CostLedger(conn, settings).recover_stale_pending()
        if settings.consistency_check_on_startup:
            # Optional, off by default, and separated from the stale-pending
            # recovery above. A consistency problem must never block startup:
            # log a summary and continue.
            from app.maintenance import run_check
            from app.storage import ImageStorage

            try:
                report = run_check(conn, ImageStorage(settings.store_root))
                if report.issue_count:
                    logger.warning(
                        "startup consistency check found %d issue(s); run "
                        "`python -m app.maintenance` to inspect and repair",
                        report.issue_count,
                    )
                else:
                    logger.info("startup consistency check: clean")
            except Exception:
                logger.exception("startup consistency check failed")
        # Face-model availability is reported but never blocks startup: identity
        # scoring degrades gracefully, so a fresh environment is told how to
        # enable it rather than being refused service.
        try:
            from app.services.identity import model_status

            status = model_status()
            if status["state"] == "ok":
                logger.info("face model ready (%s)", status["path"])
            else:
                logger.warning(
                    "face model pack is %s (%s); run `python -m app.maintenance "
                    "models install` to enable identity scoring",
                    status["state"],
                    status["path"],
                )
        except Exception:
            logger.exception("face model check failed")
    finally:
        conn.close()
    yield


app = FastAPI(title="LoreCraft3000", lifespan=lifespan)
app.add_middleware(LocalRequestGuardMiddleware)

app.include_router(api_v1.router)

if (FRONTEND_DIST_DIR / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")),
        name="frontend-assets",
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Landing page for the library-to-scene workflow.

    Serves the built React app (frontend/). The frontend is the only UI: when
    it has not been built, "/" returns a short notice pointing at `npm run
    build` instead of a second interface.
    """
    index_path = FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>LoreCraft3000</h1>"
        "<p>The React frontend has not been built yet. Run "
        "<code>npm run build</code> in <code>frontend/</code> and restart "
        "this server, or use the JSON API under <code>/api/v1</code>.</p>"
    )


@app.get("/health/live")
def health_live() -> dict:
    """Liveness: the process is up and answering. No subsystem checks."""
    return {"status": "ok"}


@app.get("/health")
def health() -> JSONResponse:
    """Readiness: verify database, migrations, and storage are ready.

    Returns 200 with a per-check breakdown when the app can serve requests, and
    503 with the failing checks named otherwise. The report is read-only and
    never runs the full storage consistency scan.
    """
    report = readiness_report(settings)
    body = report.as_dict()
    body["status"] = "ok" if report.ok else "not_ready"
    return JSONResponse(body, status_code=200 if report.ok else 503)
