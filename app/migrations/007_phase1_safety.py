"""Phase 1 safety invariants for generation, budgets, and reference canon."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # Do not use executescript here: it commits before running and can leave a
    # partially applied migration. The runner records the version and commits
    # this transaction only after every statement succeeds.
    conn.execute("BEGIN IMMEDIATE")
    statements = (
        """
        ALTER TABLE scene ADD COLUMN revision INTEGER NOT NULL DEFAULT 0
            CHECK (revision >= 0)
        """,
        "ALTER TABLE generation ADD COLUMN idempotency_key TEXT",
        """
        ALTER TABLE generation ADD COLUMN scene_revision INTEGER NOT NULL DEFAULT 0
            CHECK (scene_revision >= 0)
        """,
        """
        ALTER TABLE generation ADD COLUMN reserved_cost_usd_cents INTEGER NOT NULL DEFAULT 0
            CHECK (reserved_cost_usd_cents >= 0)
        """,
        """
        ALTER TABLE generation ADD COLUMN actual_cost_usd_cents INTEGER
            CHECK (actual_cost_usd_cents IS NULL OR actual_cost_usd_cents >= 0)
        """,
        # Older schema versions accepted negative integer costs. Treat those as
        # corrupt zero-cost records instead of making this migration unrepeatable.
        "UPDATE generation SET cost_usd_cents = MAX(cost_usd_cents, 0)",
        """
        UPDATE generation
           SET reserved_cost_usd_cents = cost_usd_cents,
               actual_cost_usd_cents = CASE
                   WHEN state = 'succeeded' THEN cost_usd_cents
                   WHEN state = 'failed' AND cost_usd_cents = 0 THEN 0
                   ELSE NULL
               END
        """,
        # Keep the newest legacy in-flight request and conservatively account
        # older duplicates before adding the uniqueness rule.
        """
        UPDATE generation
           SET state = 'failed',
               error_text = COALESCE(error_text || ' ', '') ||
                   'Recovered duplicate pending generation during migration.',
               completed_at = COALESCE(completed_at, datetime('now'))
         WHERE state = 'pending'
           AND EXISTS (
               SELECT 1
                 FROM generation AS newer
                WHERE newer.scene_id = generation.scene_id
                  AND newer.state = 'pending'
                  AND newer.id > generation.id
           )
        """,
        """
        CREATE UNIQUE INDEX idx_generation_one_pending_per_scene
            ON generation (scene_id)
            WHERE state = 'pending' AND scene_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX idx_generation_scene_idempotency
            ON generation (scene_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """,
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
    try:
        for statement in statements:
            conn.execute(statement)
    except Exception:
        conn.rollback()
        raise
