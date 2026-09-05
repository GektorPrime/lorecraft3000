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
    "app.migrations.005_repair_canonical_trigger",
    "app.migrations.006_reconcile_high_demand_failures",
    "app.migrations.007_phase1_safety",
    "app.migrations.008_phase1_reconciliation",
    "app.migrations.009_storage_indexes",
    "app.migrations.010_image_provenance",
    "app.migrations.011_repair_generation_scene_revision",
    "app.migrations.012_archive_character_style",
    "app.migrations.013_face_embedding",
    "app.migrations.014_candidate_identity",
    "app.migrations.015_preserve_retired_ref_sets",
    "app.migrations.016_base_stages",
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


def run_migrations(
    db_path: Path | str,
    *,
    journal_mode: str = "wal",
    busy_timeout_ms: int = 5000,
    synchronous: str = "normal",
) -> list[str]:
    """Apply all pending migrations. Returns the list of versions applied.

    The whole run executes inside one BEGIN IMMEDIATE transaction, so a second
    process starting concurrently either waits within the busy timeout or joins
    after this run commits (and observes the versions already applied). Because
    the transaction is committed only after every pending migration and its
    schema_migrations insert succeeds, an interrupted or failed run leaves no
    partially applied migration: re-running resumes cleanly from the same state.
    """
    conn = connect(
        db_path,
        journal_mode=journal_mode,
        busy_timeout_ms=busy_timeout_ms,
        synchronous=synchronous,
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        raise
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
            applied.append(version)
        conn.commit()
        return applied
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
