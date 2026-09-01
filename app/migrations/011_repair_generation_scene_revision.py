"""Repair generation.scene_revision missing on legacy databases.

Some databases were migrated by an earlier revision of 007_phase1_safety that
predates the ``scene_revision`` column. Because 007 is already recorded in
schema_migrations it never re-runs, so the column stays absent forever and any
generation reservation INSERT that references it fails with
``table generation has no column named scene_revision``.

This migration converges such databases to the current schema by adding the
column exactly as 007 defines it, and is a no-op on databases that already
have it.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade): the whole run
    # runs inside BEGIN IMMEDIATE and commits only after every statement here
    # and in the schema_migrations insert succeeds.
    has_scene_revision = any(
        row["name"] == "scene_revision"
        for row in conn.execute("PRAGMA table_info(generation)")
    )
    if has_scene_revision:
        return
    conn.execute(
        "ALTER TABLE generation ADD COLUMN scene_revision INTEGER NOT NULL DEFAULT 0 "
        "CHECK (scene_revision >= 0)"
    )