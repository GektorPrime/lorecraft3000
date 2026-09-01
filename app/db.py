"""SQLite connection helpers.

Uses the stdlib sqlite3 module (no ORM needed at this size). Every connection
enables foreign-key integrity and is tuned for safe concurrent use: WAL journal
mode (readers and one writer proceed without blocking), a busy timeout (a second
writer waits briefly instead of failing immediately), and synchronous=NORMAL
(the standard safe pairing with WAL).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Defaults mirror app.config.Settings so every caller (including tests that pass
# only a path) gets safe concurrency behavior. Real entrypoints pass the
# configured values explicitly.
DEFAULT_JOURNAL_MODE = "wal"
DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_SYNCHRONOUS = "normal"


def connect(
    db_path: Path | str,
    *,
    journal_mode: str = DEFAULT_JOURNAL_MODE,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    synchronous: str = DEFAULT_SYNCHRONOUS,
) -> sqlite3.Connection:
    """Open a SQLite connection tuned for safe concurrent use.

    Enables foreign-key integrity and applies the journal mode, busy timeout,
    and synchronous PRAGMAs. When WAL is requested, the connection is verified
    to actually be in WAL mode and raises if the database rejected it (for
    example, an in-memory database).
    """
    # FastAPI may create a sync dependency in a worker thread and consume it
    # from an async route on the event-loop thread. Each request still owns one
    # connection exclusively, so cross-thread handoff is safe here.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout must be set before any contended statement so a second writer
    # waits rather than failing immediately with "database is locked".
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    applied_mode = conn.execute(
        f"PRAGMA journal_mode = {journal_mode}"
    ).fetchone()[0]
    if journal_mode.lower() == "wal" and applied_mode.lower() != "wal":
        conn.close()
        raise RuntimeError(
            f"requested WAL journal mode but database reported {applied_mode!r}"
        )
    conn.execute(f"PRAGMA synchronous = {synchronous}")
    return conn
