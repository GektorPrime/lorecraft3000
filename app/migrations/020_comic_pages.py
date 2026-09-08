"""Template-based comic pages and their immutable render revisions."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE comic_page (
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
            template_key        TEXT NOT NULL CHECK (template_key IN (
                                    'full', 'two_rows', 'two_columns',
                                    'feature_top', 'feature_bottom', 'three_rows',
                                    'four_grid', 'feature_left', 'six_grid'
                                )),
            template_version    INTEGER NOT NULL DEFAULT 1
                                    CHECK (template_version = 1),
            divider_values_json TEXT NOT NULL DEFAULT '[]' CHECK (
                                    json_valid(divider_values_json)
                                    AND json_type(divider_values_json) = 'array'
                                    AND json_array_length(divider_values_json) = CASE
                                        WHEN template_key = 'full' THEN 0
                                        WHEN template_key IN (
                                            'two_rows', 'two_columns'
                                        ) THEN 1
                                        WHEN template_key = 'six_grid' THEN 3
                                        ELSE 2
                                    END
                                    AND (
                                        json_array_length(divider_values_json) = 0
                                        OR (
                                            json_type(divider_values_json, '$[0]')
                                                IN ('integer', 'real')
                                            AND json_extract(divider_values_json, '$[0]')
                                                BETWEEN 0.2 AND 0.8
                                        )
                                    )
                                    AND (
                                        json_array_length(divider_values_json) < 2
                                        OR (
                                            json_type(divider_values_json, '$[1]')
                                                IN ('integer', 'real')
                                            AND json_extract(divider_values_json, '$[1]')
                                                BETWEEN 0.2 AND 0.8
                                        )
                                    )
                                    AND (
                                        json_array_length(divider_values_json) < 3
                                        OR (
                                            json_type(divider_values_json, '$[2]')
                                                IN ('integer', 'real')
                                            AND json_extract(divider_values_json, '$[2]')
                                                BETWEEN 0.2 AND 0.8
                                        )
                                    )
                                    AND (
                                        template_key NOT IN ('three_rows', 'six_grid')
                                         OR json_extract(divider_values_json, '$[1]')
                                            - json_extract(divider_values_json, '$[0]') >= 0.1
                                    )
                                ),
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
        CREATE TABLE comic_page_panel (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id      INTEGER NOT NULL REFERENCES comic_page(id) ON DELETE CASCADE,
            candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE RESTRICT,
            slot_index   INTEGER NOT NULL CHECK (slot_index >= 0),
            focal_x      REAL NOT NULL DEFAULT 0.5 CHECK (focal_x BETWEEN 0.0 AND 1.0),
            focal_y      REAL NOT NULL DEFAULT 0.5 CHECK (focal_y BETWEEN 0.0 AND 1.0),
            zoom         REAL NOT NULL DEFAULT 1.0 CHECK (zoom BETWEEN 1.0 AND 3.0),
            UNIQUE (page_id, slot_index),
            UNIQUE (page_id, candidate_id)
        )
        """,
        "CREATE INDEX idx_comic_page_panel_candidate ON comic_page_panel (candidate_id)",
        """
        CREATE TABLE page_render (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id       INTEGER NOT NULL REFERENCES comic_page(id) ON DELETE CASCADE,
            page_revision INTEGER NOT NULL CHECK (page_revision >= 1),
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
            UNIQUE (page_id, page_revision)
        )
        """,
        "CREATE INDEX idx_page_render_sha256 ON page_render (sha256)",
    )
    for statement in statements:
        conn.execute(statement)
