"""Allow multiple face embeddings for a multi-view reference image."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    statements = (
        "ALTER TABLE face_embedding RENAME TO face_embedding_old",
        """
        CREATE TABLE face_embedding (
            sha256      TEXT NOT NULL,
            face_index  INTEGER NOT NULL CHECK (face_index >= 0),
            embedding   BLOB NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (sha256, face_index)
        ) WITHOUT ROWID
        """,
        """
        INSERT INTO face_embedding (sha256, face_index, embedding, created_at)
        SELECT sha256, 0, embedding, created_at FROM face_embedding_old
        """,
        "DROP TABLE face_embedding_old",
        "CREATE INDEX idx_face_embedding_created_at ON face_embedding (created_at)",
    )
    for statement in statements:
        conn.execute(statement)
