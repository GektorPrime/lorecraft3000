"""Base Stage persistence and future scene association."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE base_stage (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            origin                TEXT NOT NULL
                                  CHECK (origin IN ('generated', 'upload')),
            state                 TEXT NOT NULL
                                  CHECK (state IN ('draft', 'ready')),
            description           TEXT NOT NULL
                                  CHECK (length(trim(description)) > 0),
            beat_text             TEXT,
            camera                TEXT,
            framing               TEXT,
            mood                  TEXT,
            aspect_ratio          TEXT NOT NULL,
            style_id              INTEGER REFERENCES style(id),
            model                 TEXT,
            image_size            TEXT,
            uploaded_sha256       TEXT,
            selected_candidate_id INTEGER REFERENCES candidate(id),
            image_width           INTEGER,
            image_height          INTEGER,
            revision              INTEGER NOT NULL DEFAULT 0
                                  CHECK (revision >= 0),
            created_at            TEXT NOT NULL DEFAULT (datetime('now')),
            archived_at           TEXT,
            CHECK (
                (image_width IS NULL AND image_height IS NULL)
                OR (image_width > 0 AND image_height > 0)
            ),
            CHECK (
                uploaded_sha256 IS NULL
                OR (
                    length(uploaded_sha256) = 64
                    AND uploaded_sha256 NOT GLOB '*[^0-9a-f]*'
                )
            ),
            CHECK (
                origin != 'upload'
                OR (
                    state = 'ready'
                    AND uploaded_sha256 IS NOT NULL
                    AND selected_candidate_id IS NULL
                    AND beat_text IS NULL
                    AND camera IS NULL
                    AND framing IS NULL
                    AND mood IS NULL
                    AND style_id IS NULL
                    AND model IS NULL
                    AND image_size IS NULL
                    AND image_width IS NOT NULL
                )
            ),
            CHECK (
                origin != 'generated'
                OR (
                    uploaded_sha256 IS NULL
                    AND (state != 'ready' OR selected_candidate_id IS NOT NULL)
                )
            ),
            CHECK (state != 'draft' OR selected_candidate_id IS NULL),
            CHECK (state != 'ready' OR image_width IS NOT NULL)
        )
        """,
        """
        CREATE TABLE base_stage_target (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            base_stage_id INTEGER NOT NULL
                          REFERENCES base_stage(id) ON DELETE CASCADE,
            position      INTEGER NOT NULL CHECK (position >= 0),
            description   TEXT NOT NULL CHECK (length(trim(description)) > 0),
            UNIQUE (base_stage_id, position)
        )
        """,
        "CREATE INDEX idx_base_stage_archived_at ON base_stage (archived_at)",
        "CREATE INDEX idx_base_stage_target_stage ON base_stage_target (base_stage_id)",
        "ALTER TABLE scene ADD COLUMN base_stage_id INTEGER REFERENCES base_stage(id)",
        "CREATE INDEX idx_scene_base_stage_id ON scene (base_stage_id)",
    )
    for statement in statements:
        conn.execute(statement)
