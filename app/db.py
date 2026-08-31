"""SQLite connection helpers.

Uses the stdlib sqlite3 module (no ORM needed at this size). Foreign-key
integrity is enabled on every connection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key integrity enabled."""
    # FastAPI may create a sync dependency in a worker thread and consume it
    # from an async route on the event-loop thread. Each request still owns one
    # connection exclusively, so cross-thread handoff is safe here.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
