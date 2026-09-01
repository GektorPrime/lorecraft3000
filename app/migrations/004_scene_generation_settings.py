"""Persist scene-level model and output-size choices."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade).
    statements = (
        "ALTER TABLE scene ADD COLUMN model TEXT NOT NULL DEFAULT 'gemini-3.1-flash-image'",
        "ALTER TABLE scene ADD COLUMN image_size TEXT NOT NULL DEFAULT '1K'",
    )
    for statement in statements:
        conn.execute(statement)
