"""SQLite connection helpers.

Uses the stdlib sqlite3 module (no ORM needed at this size). Foreign-key
integrity is enabled on every connection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key integrity enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
