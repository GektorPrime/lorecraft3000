"""Shared FastAPI dependencies: settings, templates, DB connection, storage.

Routes declare `conn: sqlite3.Connection = Depends(get_conn)` and
`storage: ImageStorage = Depends(get_storage)`; tests override these via
`app.dependency_overrides` to isolate against temp databases/stores.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.db import connect
from app.providers.gemini import GeminiProvider
from app.storage import ImageStorage

# Single Settings instance for the whole app (env/.env loaded in app.config).
settings = Settings.from_env()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_conn():
    """Yield a SQLite connection (FK integrity on) for the request's lifetime."""
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_storage() -> ImageStorage:
    """Return the content-addressed image store rooted at settings.store_root."""
    return ImageStorage(settings.store_root)


def get_provider():
    """Construct the real provider only for an explicit generation request."""
    return GeminiProvider(timeout_seconds=settings.provider_timeout_seconds)
