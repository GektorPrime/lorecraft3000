"""Tests for the migration runner: fresh init + idempotency."""

from __future__ import annotations

import importlib
import sqlite3

import pytest

from app.db import connect
from app.migrate import MIGRATIONS, _ensure_migrations_table, applied_versions, run_migrations


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


def test_005_repairs_legacy_unconditional_canonical_trigger(tmp_path):
    """Regression test for issue #15: some already-deployed databases carry an
    OLDER, unconditional ``trg_ref_set_no_update_canonical`` that predates the
    ``status -> retired`` carve-out and aborts on every UPDATE of a canonical
    row — including the one legitimate transition promotion depends on.

    This simulates that legacy state (migrations 001-004 applied, then the
    trigger body downgraded to the old unconditional form, matching a real
    pre-fix production database) and asserts that running the full migration
    runner applies 005 and repairs the trigger: the legitimate
    status->retired transition starts working again, while illegal updates to
    a canonical row remain blocked.
    """
    db = tmp_path / "legacy.db"
    conn = connect(db)
    try:
        # Apply only migrations 001-004, as a legacy pre-005 database would
        # have (each applied directly, bypassing the runner's version list so
        # this test does not depend on 005 already existing).
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS:
            version = module_name.rsplit(".", 1)[-1]
            if version == "005_repair_canonical_trigger":
                continue
            module = importlib.import_module(module_name)
            module.upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        conn.commit()

        # Downgrade the trigger to the OLD, unconditional legacy definition
        # (no carve-out for the status->retired transition at all).
        conn.executescript(
            """
            DROP TRIGGER trg_ref_set_no_update_canonical;
            CREATE TRIGGER trg_ref_set_no_update_canonical
            BEFORE UPDATE ON ref_set
            FOR EACH ROW
            WHEN OLD.status = 'canonical'
            BEGIN
                SELECT RAISE(ABORT, 'canonical ref_set is immutable');
            END;
            """
        )
        conn.execute("INSERT INTO character (name, slug) VALUES ('Elias', 'elias')")
        conn.execute(
            "INSERT INTO ref_set (character_id, version, status) VALUES (1, 1, 'canonical')"
        )
        conn.commit()

        # Confirm the legacy bug: even the legitimate retire transition is
        # blocked before 005 is applied.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ref_set SET status = 'retired' WHERE id = 1")
        conn.rollback()
    finally:
        conn.close()

    applied = run_migrations(db)
    assert "005_repair_canonical_trigger" in applied

    conn = connect(db)
    try:
        # The legitimate status->retired transition now succeeds.
        conn.execute("UPDATE ref_set SET status = 'retired' WHERE id = 1")
        conn.commit()
        row = conn.execute("SELECT status FROM ref_set WHERE id = 1").fetchone()
        assert row["status"] == "retired"

        # The trigger still blocks any other update to a canonical row.
        conn.execute("UPDATE ref_set SET status = 'canonical' WHERE id = 1")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ref_set SET version = 99 WHERE id = 1")
        conn.rollback()

        # And deletion of a canonical row is still blocked.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM ref_set WHERE id = 1")
        conn.rollback()
    finally:
        conn.close()


def test_006_reconciles_only_explicit_high_demand_failures(conn):
    migration = importlib.import_module(
        "app.migrations.006_reconcile_high_demand_failures"
    )
    style_id = conn.execute("SELECT id FROM style ORDER BY id LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO character (name, slug) VALUES ('Elias', 'elias')")
    scene_id = conn.execute(
        """
        INSERT INTO scene
            (beat_text, camera, framing, mood, aspect_ratio, cast_json,
             style_id, model, image_size)
        VALUES ('beat', 'eye level', 'medium', '', '3:2',
                '[{"character_id": 1}]', ?, 'gemini-3-pro-image', '1K')
        """,
        (style_id,),
    ).lastrowid
    explicit = conn.execute(
        """
        INSERT INTO generation
            (scene_id, model, params_json, prompt_hash, request_json,
             cost_usd_cents, state, price_table_version, error_text)
        VALUES (?, 'gemini-3-pro-image', '{}', 'busy', '{}', 20, 'failed',
                'test', 'Model is experiencing high demand. Please try again later.')
        """,
        (scene_id,),
    ).lastrowid
    unknown = conn.execute(
        """
        INSERT INTO generation
            (scene_id, model, params_json, prompt_hash, request_json,
             cost_usd_cents, state, price_table_version, error_text)
        VALUES (?, 'gemini-3-pro-image', '{}', 'unknown', '{}', 20, 'failed',
                'test', 'Unknown provider failure')
        """,
        (scene_id,),
    ).lastrowid
    conn.commit()

    migration.upgrade(conn)
    conn.commit()

    costs = {
        row["id"]: row["cost_usd_cents"]
        for row in conn.execute(
            "SELECT id, cost_usd_cents FROM generation WHERE id IN (?, ?)",
            (explicit, unknown),
        ).fetchall()
    }
    assert costs[explicit] == 0
    assert costs[unknown] == 20
