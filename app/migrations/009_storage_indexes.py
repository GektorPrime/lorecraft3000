"""Add indexes for frequently joined lookups.

These columns are queried on hot paths (candidate lookups by generation, and
reference/candidate hash lookups) and by the Phase 3 consistency scan that joins
database hashes to stored objects. All statements use IF NOT EXISTS so the
migration is safe to re-run and safe on databases that already have them.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # Do not use executescript here: it commits before running and can leave a
    # partially applied migration. The runner records the version and commits
    # this transaction only after every statement succeeds.
    conn.execute("BEGIN IMMEDIATE")
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_candidate_generation_id "
        "ON candidate (generation_id)",
        "CREATE INDEX IF NOT EXISTS idx_candidate_sha256 "
        "ON candidate (sha256)",
        "CREATE INDEX IF NOT EXISTS idx_ref_image_sha256 "
        "ON ref_image (sha256)",
        "CREATE INDEX IF NOT EXISTS idx_ref_image_ref_set_id "
        "ON ref_image (ref_set_id)",
    )
    try:
        for statement in statements:
            conn.execute(statement)
    except Exception:
        conn.rollback()
        raise
