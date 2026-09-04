"""Prevent deletion of retired canonical reference-set versions."""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TRIGGER trg_ref_set_no_delete_retired
        BEFORE DELETE ON ref_set
        FOR EACH ROW
        WHEN OLD.status = 'retired'
        BEGIN
            SELECT RAISE(ABORT, 'retired ref_set cannot be deleted');
        END
        """
    )
