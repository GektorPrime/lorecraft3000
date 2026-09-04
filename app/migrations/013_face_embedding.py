"""Face-embedding sidecar table keyed by content hash.

Stores the InsightFace ArcFace 512-d unit vector for any image whose face
was detected.  Keyed by sha256 so the embedding survives ref_image row
lifecycle events (promote freezes the ref_image via trigger, but the
embedding must remain updatable if the user re-uploads the same content).

The ref_image.embedding column from 001_initial.py is vestigial and left
untouched.  This table is the single source of truth for face vectors.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE face_embedding (
            sha256      TEXT PRIMARY KEY,
            embedding   BLOB NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_face_embedding_created_at "
        "ON face_embedding (created_at)"
    )
