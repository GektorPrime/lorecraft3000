"""Seed the default Victorian oil-painting style (Milestone 4).

Seeding mechanism decision: a MIGRATION, not a startup seed.

Why: the migration runner (app/migrate.py) applies each version exactly once
per database and records it in schema_migrations, so this seed is inherently
idempotent with zero startup ordering concerns. Every database — including
every test database created via run_migrations() — gets the default style for
free, and the seed values live in one place (app/services/styles.py).

INSERT OR IGNORE: if a database somehow already contains a style with the
default name, the user's row wins and the seed is skipped (never clobber user
data).
"""

from __future__ import annotations

import sqlite3

from app.services.styles import DEFAULT_STYLE_CONTRACT, DEFAULT_STYLE_NAME


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO style (name, style_contract, ref_image_ids) "
        "VALUES (?, ?, '[]')",
        (DEFAULT_STYLE_NAME, DEFAULT_STYLE_CONTRACT),
    )