"""Release reservations for explicit Gemini high-demand rejections.

These provider-capacity responses produce no image and explicitly ask the
caller to try again later. Older app versions conservatively retained their
estimated cost. Reconcile only this known response; unknown 5xx failures stay
reserved because their billing status is uncertain.
"""

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE generation
           SET cost_usd_cents = 0
         WHERE state = 'failed'
           AND lower(error_text) LIKE '%high demand%'
           AND lower(error_text) LIKE '%try again later%'
        """
    )
