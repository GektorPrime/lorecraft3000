"""Generation ownership for generated Base Stages.

Phase 3 generations always belonged to a scene (``scene_id``). Generated Base
Stages need their own paid attempts, so a generation now belongs to exactly one
owner: a scene or a Base Stage. Ownership is immutable once written, and the
per-owner "one pending attempt" and idempotency rules mirror the scene indexes
added in 007_phase1_safety.

SQLite cannot add a table-level CHECK with ALTER TABLE, so the XOR rule is
enforced with triggers. Only INSERTs are checked; pre-existing rows (including
any legacy ownerless generation) stay readable and can still be reconciled by
succeed()/fail(), which never touch the ownership columns.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade): the whole run
    # executes inside BEGIN IMMEDIATE and commits only after every statement
    # here succeeds, so a failure rolls back this migration cleanly.
    statements = (
        "ALTER TABLE generation ADD COLUMN base_stage_id INTEGER "
        "REFERENCES base_stage(id)",
        """
        ALTER TABLE generation ADD COLUMN base_stage_revision INTEGER NOT NULL
            DEFAULT 0 CHECK (base_stage_revision >= 0)
        """,
        # One in-flight attempt per Base Stage, mirroring
        # idx_generation_one_pending_per_scene.
        """
        CREATE UNIQUE INDEX idx_generation_one_pending_per_base_stage
            ON generation (base_stage_id)
            WHERE state = 'pending' AND base_stage_id IS NOT NULL
        """,
        # Scene idempotency keys are scoped by scene_id; Base Stage attempts
        # have a NULL scene_id, so they need their own scoped uniqueness.
        """
        CREATE UNIQUE INDEX idx_generation_base_stage_idempotency
            ON generation (base_stage_id, idempotency_key)
            WHERE base_stage_id IS NOT NULL AND idempotency_key IS NOT NULL
        """,
        "CREATE INDEX idx_generation_base_stage_id ON generation (base_stage_id)",
        """
        CREATE TRIGGER trg_generation_insert_single_owner
        BEFORE INSERT ON generation
        FOR EACH ROW
        WHEN (NEW.scene_id IS NULL) = (NEW.base_stage_id IS NULL)
        BEGIN
            SELECT RAISE(
                ABORT,
                'a generation must belong to exactly one panel or base stage'
            );
        END
        """,
        """
        CREATE TRIGGER trg_generation_owner_immutable
        BEFORE UPDATE ON generation
        FOR EACH ROW
        WHEN NEW.scene_id IS NOT OLD.scene_id
          OR NEW.base_stage_id IS NOT OLD.base_stage_id
        BEGIN
            SELECT RAISE(ABORT, 'generation ownership is immutable');
        END
        """,
    )
    for statement in statements:
        conn.execute(statement)
