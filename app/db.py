"""SQLite connection helpers.

Uses the stdlib sqlite3 module (no ORM needed at this size). Every connection
enables foreign-key integrity and is tuned for safe concurrent use: WAL journal
mode (readers and one writer proceed without blocking), a busy timeout (a second
writer waits briefly instead of failing immediately), and synchronous=NORMAL
(the standard safe pairing with WAL).
"""

from __future__ import annotations

import sqlite3
import time
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
    # Reading journal_mode is lock-free; setting it acquires a database lock
    # that IGNORES the busy handler (a WAL conversion needs more than a normal
    # lock). Only set when the database actually differs, and retry briefly so
    # two connections racing to initialize a fresh database do not fail with a
    # spurious "database is locked".
    current_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    if current_mode.lower() != journal_mode.lower():
        _set_journal_mode(conn, journal_mode)
    conn.execute(f"PRAGMA synchronous = {synchronous}")
    return conn


def _set_journal_mode(conn: sqlite3.Connection, journal_mode: str) -> None:
    """Set journal_mode, retrying while another connection owns the write lock.

    ``PRAGMA journal_mode`` does not respect ``busy_timeout`` when converting an
    existing database, so without retry a concurrent initializer can fail with
    "database is locked". The retry target is small: the racing connection (for
    example, a concurrent migration run on a fresh database) releases within
    milliseconds.
    """
    deadline = time.monotonic() + 5.0
    while True:
        try:
            applied_mode = conn.execute(
                f"PRAGMA journal_mode = {journal_mode}"
            ).fetchone()[0]
            break
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "busy" not in message and "locked" not in message:
                conn.close()
                raise
            if time.monotonic() >= deadline:
                conn.close()
                raise
            time.sleep(0.02)
    if journal_mode.lower() == "wal" and applied_mode.lower() != "wal":
        conn.close()
        raise RuntimeError(
            f"requested WAL journal mode but database reported {applied_mode!r}"
        )
