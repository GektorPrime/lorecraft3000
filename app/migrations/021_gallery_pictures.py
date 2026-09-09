"""Uploaded gallery pictures and mixed panel-slot sources."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE gallery_picture (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256            TEXT NOT NULL CHECK (
                                  length(sha256) = 64
                                  AND sha256 NOT GLOB '*[^0-9a-f]*'
                              ),
            title             TEXT NOT NULL CHECK (
                                  title = trim(title)
                                  AND length(title) BETWEEN 1 AND 120
                              ),
            original_filename TEXT CHECK (
                                  original_filename IS NULL
                                  OR length(original_filename) BETWEEN 1 AND 1024
                              ),
            image_width       INTEGER NOT NULL CHECK (image_width BETWEEN 1 AND 8192),
            image_height      INTEGER NOT NULL CHECK (image_height BETWEEN 1 AND 8192),
            created_at        TEXT NOT NULL DEFAULT (datetime('now'))
                                  CHECK (length(created_at) > 0),
            archived_at       TEXT CHECK (archived_at IS NULL OR length(archived_at) > 0),
            CHECK (image_width * image_height <= 40000000)
        )
        """
    )
    conn.execute("CREATE INDEX idx_gallery_picture_sha256 ON gallery_picture (sha256)")
    conn.execute(
        "CREATE INDEX idx_gallery_picture_active_created "
        "ON gallery_picture (created_at DESC, id DESC) WHERE archived_at IS NULL"
    )

    # SQLite cannot add a checked foreign-key column in place. Rebuilding also
    # preserves existing slot ids, geometry, and the candidate lookup index.
    conn.execute("ALTER TABLE panel_slot RENAME TO panel_slot_old")
    conn.execute(
        """
        CREATE TABLE panel_slot (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id           INTEGER NOT NULL REFERENCES panel(id) ON DELETE CASCADE,
            candidate_id       INTEGER REFERENCES candidate(id) ON DELETE RESTRICT,
            gallery_picture_id INTEGER REFERENCES gallery_picture(id) ON DELETE RESTRICT,
            slot_index         INTEGER NOT NULL CHECK (slot_index >= 0),
            x0                 REAL NOT NULL CHECK (x0 BETWEEN 0.0 AND 1.0),
            y0                 REAL NOT NULL CHECK (y0 BETWEEN 0.0 AND 1.0),
            x1                 REAL NOT NULL CHECK (x1 BETWEEN 0.0 AND 1.0),
            y1                 REAL NOT NULL CHECK (y1 BETWEEN 0.0 AND 1.0),
            focal_x            REAL NOT NULL DEFAULT 0.5 CHECK (focal_x BETWEEN 0.0 AND 1.0),
            focal_y            REAL NOT NULL DEFAULT 0.5 CHECK (focal_y BETWEEN 0.0 AND 1.0),
            zoom               REAL NOT NULL DEFAULT 1.0 CHECK (zoom BETWEEN 1.0 AND 5.0),
            CHECK (x1 - x0 >= 0.04),
            CHECK (y1 - y0 >= 0.04),
            CHECK (candidate_id IS NULL OR gallery_picture_id IS NULL),
            UNIQUE (panel_id, slot_index)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO panel_slot
            (id, panel_id, candidate_id, gallery_picture_id, slot_index,
             x0, y0, x1, y1, focal_x, focal_y, zoom)
        SELECT id, panel_id, candidate_id, NULL, slot_index,
               x0, y0, x1, y1, focal_x, focal_y, zoom
          FROM panel_slot_old
        """
    )
    conn.execute("DROP TABLE panel_slot_old")
    conn.execute("CREATE INDEX idx_panel_slot_candidate ON panel_slot (candidate_id)")
    conn.execute(
        "CREATE INDEX idx_panel_slot_gallery_picture ON panel_slot (gallery_picture_id)"
    )
