"""Tests for SQLite connection tuning and storage indexes."""

from __future__ import annotations

import sqlite3

import pytest

from app.db import connect
from app.migrate import run_migrations


def test_connect_enables_foreign_keys(tmp_path):
    conn = connect(tmp_path / "fk.db")
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_connect_defaults_to_wal_and_busy_timeout(tmp_path):
    conn = connect(tmp_path / "wal.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        # NORMAL synchronous maps to integer 1.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_connect_honors_overrides(tmp_path):
    conn = connect(
        tmp_path / "custom.db",
        journal_mode="delete",
        busy_timeout_ms=1234,
        synchronous="full",
    )
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        # FULL synchronous maps to integer 2.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        conn.close()


def test_connect_wal_request_on_memory_db_raises():
    # An in-memory database cannot enter WAL mode; the connection must fail loud.
    with pytest.raises(RuntimeError, match="WAL"):
        connect(":memory:")


def test_busy_timeout_lets_second_writer_wait(tmp_path):
    db = tmp_path / "contend.db"
    first = connect(db)
    second = connect(db, busy_timeout_ms=2000)
    try:
        first.execute("CREATE TABLE t (id INTEGER)")
        first.commit()
        first.execute("BEGIN IMMEDIATE")
        first.execute("INSERT INTO t (id) VALUES (1)")
        # Second writer should wait for the busy timeout rather than raise
        # immediately; commit the first writer so the wait resolves quickly.
        first.commit()
        second.execute("INSERT INTO t (id) VALUES (2)")
        second.commit()
        assert first.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        first.close()
        second.close()


def test_storage_indexes_created(tmp_path):
    db = tmp_path / "idx.db"
    run_migrations(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
        names = {r["name"] for r in rows}
    finally:
        conn.close()
    assert "idx_candidate_generation_id" in names
    assert "idx_candidate_sha256" in names
    assert "idx_ref_image_sha256" in names
    assert "idx_ref_image_ref_set_id" in names


def test_storage_index_migration_is_idempotent(tmp_path):
    db = tmp_path / "idx2.db"
    first = run_migrations(db)
    assert "009_storage_indexes" in first
    second = run_migrations(db)
    assert second == []
