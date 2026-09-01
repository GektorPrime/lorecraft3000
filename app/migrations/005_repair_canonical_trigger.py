"""Repair the canonical ref_set immutability trigger on legacy databases.

Some already-deployed databases still carry an OLDER, unconditional version of
``trg_ref_set_no_update_canonical`` — created before the ``status -> retired``
carve-out existed. That older trigger body aborts on *every* UPDATE of a
canonical row, including the one legitimate transition
(``promote()`` retiring the prior canonical), which breaks promotion on any
database created before the carve-out shipped.

This migration is defensive and idempotent: it drops WHATEVER trigger
definition is currently installed (old, unconditional; already-correct; or
missing) and recreates it from the current, correct definition — the same one
in ``001_initial.py``. Running this against a fresh database that already has
the correct trigger is a no-op in effect (drop + recreate the same body).
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    # The runner owns the transaction (see 001_initial.upgrade).
    statements = (
        "DROP TRIGGER IF EXISTS trg_ref_set_no_update_canonical",
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
    )
    for statement in statements:
        conn.execute(statement)
