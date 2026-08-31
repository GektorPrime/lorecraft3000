"""Tests for the migration runner: fresh init + idempotency."""

from __future__ import annotations

from app.db import connect
from app.migrate import MIGRATIONS, applied_versions, run_migrations


def test_fresh_init_creates_all_tables(tmp_path):
    db = tmp_path / "fresh.db"
    applied = run_migrations(db)
    assert applied == [m.rsplit(".", 1)[-1] for m in MIGRATIONS]

    conn = connect(db)
    try:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    expected = {
        "character",
        "ref_set",
        "ref_image",
        "style",
        "scene",
        "generation",
        "candidate",
        "schema_migrations",
    }
    assert expected <= tables
    # verification is deferred to Phase 2 — must NOT exist.
    assert "verification" not in tables


def test_idempotent_second_run(tmp_path):
    db = tmp_path / "idem.db"
    first = run_migrations(db)
    assert first  # applied something

    second = run_migrations(db)
    assert second == []  # nothing new to apply

    conn = connect(db)
    try:
        assert applied_versions(conn) == {m.rsplit(".", 1)[-1] for m in MIGRATIONS}
    finally:
        conn.close()


def test_migrations_table_tracks_versions(tmp_path):
    db = tmp_path / "track.db"
    run_migrations(db)
    conn = connect(db)
    try:
        versions = {
            r["version"]
            for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
    finally:
        conn.close()
    assert versions == {m.rsplit(".", 1)[-1] for m in MIGRATIONS}


def test_generation_core_columns_are_migrated(conn):
    scene_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(scene)").fetchall()
    }
    generation_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(generation)").fetchall()
    }
    candidate_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(candidate)").fetchall()
    }
    assert {"style_id", "model", "image_size"} <= scene_columns
    assert {
        "price_table_version", "response_json", "error_text", "completed_at"
    } <= generation_columns
    assert "review_status" in candidate_columns
