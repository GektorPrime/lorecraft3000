"""Add turnaround and head-back character reference image roles."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # SQLite cannot alter a CHECK constraint, so preserve the rows while
    # replacing the table and then restore its indexes and safety triggers.
    statements = (
        "DROP TRIGGER trg_ref_image_insert_draft_only",
        "DROP TRIGGER trg_ref_image_update_draft_only",
        "DROP TRIGGER trg_ref_image_delete_draft_only",
        "ALTER TABLE ref_image RENAME TO ref_image_old",
        """
        CREATE TABLE ref_image (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_set_id     INTEGER NOT NULL REFERENCES ref_set(id),
            sha256         TEXT NOT NULL,
            role           TEXT NOT NULL
                           CHECK (role IN (
                               'turnaround', 'full_body', 'outfit',
                               'face_front', 'face_3q', 'face_profile',
                               'head_back', 'expression'
                           )),
            weight         REAL NOT NULL DEFAULT 1.0,
            embedding      BLOB,
            quality_flags  TEXT NOT NULL DEFAULT '[]',
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        INSERT INTO ref_image
            (id, ref_set_id, sha256, role, weight, embedding, quality_flags, created_at)
        SELECT id, ref_set_id, sha256, role, weight, embedding, quality_flags, created_at
          FROM ref_image_old
        """,
        "DROP TABLE ref_image_old",
        "CREATE INDEX idx_ref_image_sha256 ON ref_image (sha256)",
        "CREATE INDEX idx_ref_image_ref_set_id ON ref_image (ref_set_id)",
        """
        CREATE TRIGGER trg_ref_image_insert_draft_only
        BEFORE INSERT ON ref_image
        FOR EACH ROW
        WHEN (SELECT status FROM ref_set WHERE id = NEW.ref_set_id) != 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'images can only be added to draft ref_sets');
        END
        """,
        """
        CREATE TRIGGER trg_ref_image_update_draft_only
        BEFORE UPDATE ON ref_image
        FOR EACH ROW
        WHEN (SELECT status FROM ref_set WHERE id = OLD.ref_set_id) != 'draft'
          OR (SELECT status FROM ref_set WHERE id = NEW.ref_set_id) != 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'images in canonical or retired ref_sets are immutable');
        END
        """,
        """
        CREATE TRIGGER trg_ref_image_delete_draft_only
        BEFORE DELETE ON ref_image
        FOR EACH ROW
        WHEN (SELECT status FROM ref_set WHERE id = OLD.ref_set_id) != 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'images in canonical or retired ref_sets are immutable');
        END
        """,
    )
    for statement in statements:
        conn.execute(statement)
