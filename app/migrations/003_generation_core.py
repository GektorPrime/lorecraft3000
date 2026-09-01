"""Generation-core fields for scenes, provenance, and manual review."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade).
    statements = (
        "ALTER TABLE scene ADD COLUMN style_id INTEGER REFERENCES style(id)",
        "ALTER TABLE generation ADD COLUMN price_table_version TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE generation ADD COLUMN response_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE generation ADD COLUMN error_text TEXT",
        "ALTER TABLE generation ADD COLUMN completed_at TEXT",
        """
        ALTER TABLE candidate ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'
            CHECK (review_status IN ('pending', 'accepted', 'rejected'))
        """,
    )
    for statement in statements:
        conn.execute(statement)
