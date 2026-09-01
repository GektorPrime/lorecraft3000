"""Append-only database provenance table (Phase 3 Work Package 3).

The sidecar is a best-effort local mirror; this table is the authoritative,
never-updated, never-deleted record of which generation produced which stored
image, what it cost, and which references were attached.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # Do not use executescript here: it commits before running and can leave a
    # partially applied migration. The runner records the version and commits
    # this transaction only after every statement succeeds.
    conn.execute("BEGIN IMMEDIATE")
    statements = (
        """
        CREATE TABLE image_provenance (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256              TEXT NOT NULL,
            generation_id       INTEGER NOT NULL REFERENCES generation(id),
            interaction_id      TEXT,
            prompt_hash         TEXT NOT NULL,
            cost_cents          INTEGER NOT NULL
                                CHECK (cost_cents = CAST(cost_cents AS INTEGER)),
            price_table_version TEXT NOT NULL,
            input_images        TEXT NOT NULL DEFAULT '[]',
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (generation_id, sha256)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_image_provenance_sha256 "
        "ON image_provenance (sha256)",
        "CREATE INDEX IF NOT EXISTS idx_image_provenance_generation_id "
        "ON image_provenance (generation_id)",
    )
    try:
        for statement in statements:
            conn.execute(statement)
    except Exception:
        conn.rollback()
        raise