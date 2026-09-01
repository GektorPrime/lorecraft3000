"""Repair old empty canon and store accounting warnings separately."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade).
    statements = (
        "ALTER TABLE generation ADD COLUMN warning_text TEXT",
        """
        UPDATE generation
           SET warning_text = error_text,
               error_text = NULL
         WHERE state = 'succeeded'
           AND error_text = 'Provider-reported actual cost exceeded the reserved daily budget. The charge is recorded and further generation is blocked.'
        """,
        "DROP TRIGGER trg_ref_set_no_update_canonical",
        # Older versions allowed an empty draft to become canonical. Return
        # those unusable sets to draft so they can be repaired in the UI.
        """
        UPDATE ref_set
           SET status = 'draft'
         WHERE status = 'canonical'
           AND NOT EXISTS (
               SELECT 1 FROM ref_image WHERE ref_image.ref_set_id = ref_set.id
           )
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
        END
        """,
    )
    for statement in statements:
        conn.execute(statement)
