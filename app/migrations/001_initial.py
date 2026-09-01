"""Initial schema: character, ref_set, ref_image, style, scene, generation, candidate.

The `verification` table is deferred to Phase 2 and is intentionally NOT created
here.

Invariants enforced in-schema:
  - character.slug is UNIQUE
  - ref_set version is UNIQUE per character (UNIQUE(character_id, version))
  - EXACTLY ONE canonical ref_set per character is enforced via a partial
    UNIQUE index on (character_id) WHERE status = 'canonical'
  - canonical ref_sets are immutable EXCEPT for a status transition to
    'retired' (needed for Milestone 5: promoting a new canonical set retires
    the prior one). During that transition ONLY the status column may change;
    every other column must remain identical. Any other update to a canonical
    row, and deletion of a canonical row, is blocked by triggers.
  - foreign-key integrity is enabled per-connection (see app/db.py)
  - monetary values are stored as INTEGER minor units (cost_usd_cents)
  - generation.state distinguishes pending/succeeded/failed via CHECK
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction: the whole run runs inside BEGIN IMMEDIATE
    # and commits only after every statement succeeds, so a failure rolls back
    # this entire migration. Each statement executes individually (no
    # executescript, which would issue an implicit COMMIT first and could leave
    # a partially applied, unrecorded schema).
    statements = (
        """
        CREATE TABLE character (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL,
            slug              TEXT NOT NULL UNIQUE,
            lore_md           TEXT NOT NULL DEFAULT '',
            visual_contract   TEXT NOT NULL DEFAULT '',
            negative_traits   TEXT NOT NULL DEFAULT '',
            default_style_id  INTEGER REFERENCES style(id),
            created_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE ref_set (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id  INTEGER NOT NULL REFERENCES character(id),
            version       INTEGER NOT NULL,
            status        TEXT NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'canonical', 'retired')),
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (character_id, version)
        );
        """,
        """
        CREATE UNIQUE INDEX idx_ref_set_one_canonical
            ON ref_set (character_id)
            WHERE status = 'canonical';
        """,
        """
        CREATE TRIGGER trg_ref_set_no_update_canonical
        BEFORE UPDATE ON ref_set
        FOR EACH ROW
        WHEN OLD.status = 'canonical'
          AND NOT (NEW.status = 'retired'
                   AND NEW.id = OLD.id
                   AND NEW.character_id = OLD.character_id
                   AND NEW.version = OLD.version
                   AND NEW.created_at = OLD.created_at)
        BEGIN
            SELECT RAISE(ABORT, 'canonical ref_set is immutable except status->retired');
        END;
        """,
        """
        CREATE TRIGGER trg_ref_set_no_delete_canonical
        BEFORE DELETE ON ref_set
        FOR EACH ROW
        WHEN OLD.status = 'canonical'
        BEGIN
            SELECT RAISE(ABORT, 'canonical ref_set cannot be deleted');
        END;
        """,
        """
        CREATE TABLE ref_image (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_set_id     INTEGER NOT NULL REFERENCES ref_set(id),
            sha256         TEXT NOT NULL,
            role           TEXT NOT NULL
                           CHECK (role IN (
                               'face_front', 'face_3q', 'face_profile',
                               'full_body', 'expression', 'outfit'
                           )),
            weight         REAL NOT NULL DEFAULT 1.0,
            embedding      BLOB,
            quality_flags  TEXT NOT NULL DEFAULT '[]',
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE style (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            style_contract  TEXT NOT NULL DEFAULT '',
            ref_image_ids   TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE scene (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id    INTEGER,
            page          INTEGER,
            panel_no      INTEGER,
            beat_text     TEXT NOT NULL DEFAULT '',
            camera        TEXT NOT NULL DEFAULT '',
            framing       TEXT NOT NULL DEFAULT '',
            mood          TEXT NOT NULL DEFAULT '',
            aspect_ratio  TEXT NOT NULL DEFAULT '3:2',
            cast_json     TEXT NOT NULL DEFAULT '[]',
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE generation (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            scene_id               INTEGER REFERENCES scene(id),
            model                  TEXT NOT NULL,
            params_json            TEXT NOT NULL DEFAULT '{}',
            prompt_hash            TEXT NOT NULL DEFAULT '',
            request_json           TEXT NOT NULL DEFAULT '{}',
            cost_usd_cents         INTEGER NOT NULL DEFAULT 0
                                   CHECK (cost_usd_cents = CAST(cost_usd_cents AS INTEGER)),
            parent_generation_id   INTEGER REFERENCES generation(id),
            interaction_id         TEXT,
            state                  TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (state IN ('pending', 'succeeded', 'failed')),
            created_at             TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
        """
        CREATE TABLE candidate (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id  INTEGER NOT NULL REFERENCES generation(id),
            sha256         TEXT NOT NULL,
            idx            INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    )
    for statement in statements:
        conn.execute(statement)
