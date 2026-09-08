"""Flexible panels and their immutable render revisions."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE panel (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            title               TEXT NOT NULL CHECK (
                                    length(trim(title)) BETWEEN 1 AND 120
                                ),
            format              TEXT NOT NULL
                                    CHECK (format IN ('portrait', 'square', 'landscape')),
            width_px            INTEGER NOT NULL CHECK (width_px > 0),
            height_px           INTEGER NOT NULL CHECK (height_px > 0),
            background_color    TEXT NOT NULL DEFAULT '#FFFFFF'
                                    CHECK (
                                        length(background_color) = 7
                                        AND substr(background_color, 1, 1) = '#'
                                        AND substr(background_color, 2) NOT GLOB '*[^0-9A-F]*'
                                    ),
            gutter_px           INTEGER NOT NULL DEFAULT 20
                                    CHECK (gutter_px BETWEEN 0 AND 80),
            frame_px            INTEGER NOT NULL DEFAULT 0
                                    CHECK (frame_px BETWEEN 0 AND 80),
            revision            INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (
                (format = 'portrait' AND width_px = 1200 AND height_px = 1800)
                OR (format = 'square' AND width_px = 1600 AND height_px = 1600)
                OR (format = 'landscape' AND width_px = 1800 AND height_px = 1200)
            )
        )
        """,
        """
        CREATE TABLE panel_slot (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id     INTEGER NOT NULL REFERENCES panel(id) ON DELETE CASCADE,
            candidate_id INTEGER REFERENCES candidate(id) ON DELETE RESTRICT,
            slot_index   INTEGER NOT NULL CHECK (slot_index >= 0),
            x0           REAL NOT NULL CHECK (x0 BETWEEN 0.0 AND 1.0),
            y0           REAL NOT NULL CHECK (y0 BETWEEN 0.0 AND 1.0),
            x1           REAL NOT NULL CHECK (x1 BETWEEN 0.0 AND 1.0),
            y1           REAL NOT NULL CHECK (y1 BETWEEN 0.0 AND 1.0),
            focal_x      REAL NOT NULL DEFAULT 0.5 CHECK (focal_x BETWEEN 0.0 AND 1.0),
            focal_y      REAL NOT NULL DEFAULT 0.5 CHECK (focal_y BETWEEN 0.0 AND 1.0),
            zoom         REAL NOT NULL DEFAULT 1.0 CHECK (zoom BETWEEN 1.0 AND 3.0),
            CHECK (x1 - x0 >= 0.04),
            CHECK (y1 - y0 >= 0.04),
            UNIQUE (panel_id, slot_index)
        )
        """,
        "CREATE INDEX idx_panel_slot_candidate ON panel_slot (candidate_id)",
        """
        CREATE TABLE panel_render (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            panel_id       INTEGER NOT NULL REFERENCES panel(id) ON DELETE CASCADE,
            panel_revision INTEGER NOT NULL CHECK (panel_revision >= 1),
            sha256         TEXT NOT NULL CHECK (
                               length(sha256) = 64
                               AND sha256 NOT GLOB '*[^0-9a-f]*'
                           ),
            width          INTEGER NOT NULL CHECK (width > 0),
            height         INTEGER NOT NULL CHECK (height > 0),
            layout_json    TEXT NOT NULL CHECK (
                               json_valid(layout_json)
                               AND json_type(layout_json) = 'object'
                           ),
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (panel_id, panel_revision)
        )
        """,
        "CREATE INDEX idx_panel_render_sha256 ON panel_render (sha256)",
    )
    for statement in statements:
        conn.execute(statement)
