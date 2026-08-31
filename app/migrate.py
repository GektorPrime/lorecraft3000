"""Migration runner.

Applies migrations in order, tracking applied versions in a schema_migrations
table. Idempotent: running it against an already-migrated DB is a no-op.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

from app.db import connect

# Ordered list of migration modules. Each module must expose `upgrade(conn)`.
MIGRATIONS: list[str] = [
    "app.migrations.001_initial",
    "app.migrations.002_default_style",
    "app.migrations.003_generation_core",
    "app.migrations.004_scene_generation_settings",
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r["version"] for r in rows}


def run_migrations(db_path: Path | str) -> list[str]:
    """Apply all pending migrations. Returns the list of versions applied."""
    conn = connect(db_path)
    try:
        _ensure_migrations_table(conn)
        done = applied_versions(conn)
        applied: list[str] = []
        for module_name in MIGRATIONS:
            version = module_name.rsplit(".", 1)[-1]
            if version in done:
                continue
            module = importlib.import_module(module_name)
            module.upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
        return applied
    finally:
        conn.close()
