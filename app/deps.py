"""Shared FastAPI dependencies: settings, DB connection, storage.

Routes declare `conn: sqlite3.Connection = Depends(get_conn)` and
`storage: ImageStorage = Depends(get_storage)`; tests override these via
`app.dependency_overrides` to isolate against temp databases/stores.
"""

from __future__ import annotations

from app.config import Settings, provider_for_model
from app.db import connect
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider
from app.storage import ImageStorage

# Single Settings instance for the whole app (env/.env loaded in app.config).
settings = Settings.from_env()


def get_conn():
    """Yield a SQLite connection (FK integrity on) for the request's lifetime."""
    conn = connect(
        settings.db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )
    try:
        yield conn
    finally:
        conn.close()


def get_storage() -> ImageStorage:
    """Return the content-addressed image store rooted at settings.store_root."""
    return ImageStorage(settings.store_root)


class ProviderRegistry:
    """Resolve the concrete image provider for a model.

    Selection keys on the model string (see app/config.py::MODEL_PROVIDERS) so a
    panel may freely choose a Gemini or OpenAI model, and an edit stays on the
    same provider that produced the source image. Providers are constructed
    lazily and memoized so an unused vendor's SDK/client is never initialized.
    """

    def __init__(self, *, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self._cache: dict[str, object] = {}

    def _build(self, provider_key: str):
        if provider_key == "gemini":
            return GeminiProvider(timeout_seconds=self.timeout_seconds)
        if provider_key == "openai":
            # OpenAI high-quality edits with 4-5 refs can exceed 120s;
            # give it a longer bound and keep retries non-billable.
            return OpenAIProvider(timeout_seconds=max(180, self.timeout_seconds))
        raise KeyError(f"unknown provider {provider_key!r}")

    def for_model(self, model: str):
        provider_key = provider_for_model(model)
        if provider_key not in self._cache:
            self._cache[provider_key] = self._build(provider_key)
        return self._cache[provider_key]


def get_provider() -> ProviderRegistry:
    """Construct the provider registry only for an explicit generation request."""
    return ProviderRegistry(timeout_seconds=settings.provider_timeout_seconds)
