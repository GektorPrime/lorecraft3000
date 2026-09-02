"""Tests for the migration runner: fresh init + idempotency."""

from __future__ import annotations

import importlib
import sqlite3
import threading

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
        "image_provenance",
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


def test_fresh_initial_migration_rolls_back_completely_and_can_retry(tmp_path):
    """A failure partway through the initial migration leaves nothing behind."""
    db = tmp_path / "initial-retry.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        # Force CREATE TABLE character to collide.
        conn.execute("CREATE TABLE character (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        run_migrations(db)

    conn = connect(db)
    try:
        # The whole run rolled back: nothing recorded and the other fresh-schema
        # tables must not exist, so the migration can be re-run cleanly.
        assert applied_versions(conn) == set()
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ref_set" not in tables
        assert "generation" not in tables
        assert "candidate" not in tables
    finally:
        conn.close()

    conn = connect(db)
    try:
        conn.execute("DROP TABLE character")
        conn.commit()
    finally:
        conn.close()

    applied = run_migrations(db)
    assert applied == [m.rsplit(".", 1)[-1] for m in MIGRATIONS]


def test_concurrent_migration_runs_converge(tmp_path):
    """Two processes starting migrations at once settle on one consistent set."""
    db = tmp_path / "concurrent.db"
    results: list[list[str]] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(run_migrations(db))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    conn = connect(db)
    try:
        assert applied_versions(conn) == {m.rsplit(".", 1)[-1] for m in MIGRATIONS}
        # The whole run is one transaction, so exactly one runner applied the
        # full set (in some order); the other applied nothing. No version can
        # ever be applied twice or partially.
        expected = [m.rsplit(".", 1)[-1] for m in MIGRATIONS]
        assert results[0] + results[1] == expected
    finally:
        conn.close()


def test_full_schema_matches_direct_upgrade_chain(tmp_path):
    """A fresh DB built by the runner has an identical schema to one built by
    chaining every migration module directly.

    This guards against drift between the runner and the modules it executes:
    whichever path constructs a fresh database, the resulting schema — tables,
    columns, indexes, and triggers — must be byte-for-byte the same.
    """
    runner_db = tmp_path / "runner.db"
    run_migrations(runner_db)

    direct_db = tmp_path / "direct.db"
    conn = connect(direct_db)
    try:
        for module_name in MIGRATIONS:
            importlib.import_module(module_name).upgrade(conn)
        conn.commit()
    finally:
        conn.close()

    def schema_objects(db: object):
        c = connect(db)
        try:
            return {
                (r["type"], r["name"], r["tbl_name"], r["sql"])
                for r in c.execute(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"
                ).fetchall()
            }
        finally:
            c.close()

    assert schema_objects(runner_db) == schema_objects(direct_db)


def test_provenance_migration_rolls_back_completely_and_can_retry(tmp_path):
    """The newest non-idempotent migration (010) is interrupt-and-retry safe:
    a mid-run collision rolls back the whole run, and resuming after cleaning
    up converges to a fully applied, intact schema."""
    db = tmp_path / "provenance-retry.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS[:9]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        # A pre-existing image_provenance table with a divergent definition
        # forces 010's CREATE TABLE to collide mid-run.
        conn.execute(
            "CREATE TABLE image_provenance (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        run_migrations(db)

    conn = connect(db)
    try:
        assert "010_image_provenance" not in applied_versions(conn)
        # The whole run rolled back: the migration's schema_migrations insert
        # is gone and only the pre-existing stub table remains.
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM pragma_table_info('image_provenance')"
        ).fetchone()
        assert count["n"] == 1
        conn.execute("DROP TABLE image_provenance")
        conn.commit()
    finally:
        conn.close()

    assert run_migrations(db) == [
        "010_image_provenance",
        "011_repair_generation_scene_revision",
        "012_archive_character_style",
    ]
    conn = connect(db)
    try:
        assert "010_image_provenance" in applied_versions(conn)
    finally:
        conn.close()


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
        for module_name in MIGRATIONS[:4]:
            version = module_name.rsplit(".", 1)[-1]
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


def test_phase1_safety_columns_and_indexes_are_migrated(conn):
    scene_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(scene)").fetchall()
    }
    generation_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(generation)").fetchall()
    }
    indexes = {
        row["name"]
        for row in conn.execute("PRAGMA index_list(generation)").fetchall()
    }
    assert "revision" in scene_columns
    assert {
        "idempotency_key",
        "scene_revision",
        "reserved_cost_usd_cents",
        "actual_cost_usd_cents",
        "warning_text",
    } <= generation_columns
    assert {
        "idx_generation_one_pending_per_scene",
        "idx_generation_scene_idempotency",
    } <= indexes


def test_011_repairs_legacy_generation_missing_scene_revision(tmp_path):
    """Some databases were migrated by an earlier lineage of 007 phase1 safety
    that predates the generation.scene_revision column. 007 is still recorded
    as applied, so the runner never re-adds it and every reservation INSERT
    fails with ``table generation has no column named scene_revision``. 011
    must detect the drift and heal the column.
    """
    from app.config import Settings
    from app.services.costs import CostLedger

    db = tmp_path / "legacy-scene-revision.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS[:6]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        # Apply everything through 010, then drop the scene_revision column to
        # reproduce the legacy schema drift: 007 stays recorded, the column
        # vanishes (008-010 never reference the column, so they apply cleanly).
        for module_name in MIGRATIONS[6:10]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        conn.execute("ALTER TABLE generation DROP COLUMN scene_revision")
        style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
        scene_id = conn.execute(
            "INSERT INTO scene (style_id) VALUES (?)", (style_id,)
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    # The drift is invisible to the pre-011 runner: everything is recorded.
    assert run_migrations(db) == [
        "011_repair_generation_scene_revision",
        "012_archive_character_style",
    ]
    assert run_migrations(db) == []  # and healing is idempotent

    conn = connect(db)
    try:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(generation)")
        }
        assert "scene_revision" in columns
        # The healed column unblocks reservation, which previously raised
        # OperationalError on the INSERT.
        ledger = CostLedger(conn, Settings.from_env())
        reservation = ledger.reserve(
            scene_id=scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="probe",
            request_json={"aspect_ratio": "3:2"},
        )
        assert reservation.created
        conn.rollback()
    finally:
        conn.close()


def test_phase1_migration_recovers_old_duplicate_pending_rows(tmp_path):
    db = tmp_path / "duplicate-pending.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS[:6]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
        scene_id = conn.execute(
            "INSERT INTO scene (style_id) VALUES (?)", (style_id,)
        ).lastrowid
        for prompt_hash in ("old", "new"):
            conn.execute(
                """
                INSERT INTO generation
                    (scene_id, model, prompt_hash, cost_usd_cents, state)
                VALUES (?, 'gemini-3.1-flash-image', ?, 7, 'pending')
                """,
                (scene_id, prompt_hash),
            )
        conn.commit()
    finally:
        conn.close()

    assert run_migrations(db) == [
        m.rsplit(".", 1)[-1] for m in MIGRATIONS[6:]
    ]
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT state, reserved_cost_usd_cents, error_text FROM generation ORDER BY id"
        ).fetchall()
        assert rows[0]["state"] == "failed"
        assert "duplicate pending" in rows[0]["error_text"]
        assert rows[1]["state"] == "pending"
        assert [row["reserved_cost_usd_cents"] for row in rows] == [7, 7]
    finally:
        conn.close()


def test_phase1_migration_rolls_back_completely_and_can_retry(tmp_path):
    db = tmp_path / "phase1-retry.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS[:6]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        conn.execute(
            """
            CREATE TRIGGER trg_ref_image_insert_draft_only
            BEFORE INSERT ON ref_image BEGIN SELECT 1; END
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        run_migrations(db)

    conn = connect(db)
    try:
        scene_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(scene)").fetchall()
        }
        generation_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(generation)").fetchall()
        }
        assert "revision" not in scene_columns
        assert "reserved_cost_usd_cents" not in generation_columns
        assert "007_phase1_safety" not in applied_versions(conn)
        conn.execute("DROP TRIGGER trg_ref_image_insert_draft_only")
        conn.commit()
    finally:
        conn.close()

    assert run_migrations(db) == [
        m.rsplit(".", 1)[-1] for m in MIGRATIONS[6:]
    ]


def test_phase1_reconciliation_returns_legacy_empty_canon_to_draft(tmp_path):
    db = tmp_path / "empty-canon.db"
    conn = connect(db)
    try:
        _ensure_migrations_table(conn)
        for module_name in MIGRATIONS[:6]:
            version = module_name.rsplit(".", 1)[-1]
            importlib.import_module(module_name).upgrade(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
        conn.execute("INSERT INTO character (name, slug) VALUES ('Elias', 'elias')")
        conn.execute(
            "INSERT INTO ref_set (character_id, version, status) VALUES (1, 1, 'canonical')"
        )
        conn.commit()

        migration_007 = MIGRATIONS[6]
        importlib.import_module(migration_007).upgrade(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (migration_007.rsplit(".", 1)[-1],),
        )
        style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
        scene_id = conn.execute(
            "INSERT INTO scene (style_id) VALUES (?)", (style_id,)
        ).lastrowid
        warning = (
            "Provider-reported actual cost exceeded the reserved daily budget. "
            "The charge is recorded and further generation is blocked."
        )
        conn.execute(
            """
            INSERT INTO generation
                (scene_id, model, state, cost_usd_cents,
                 reserved_cost_usd_cents, actual_cost_usd_cents, error_text)
            VALUES (?, 'gemini-3.1-flash-image', 'succeeded', 301, 7, 301, ?)
            """,
            (scene_id, warning),
        )
        conn.commit()
    finally:
        conn.close()

    assert run_migrations(db) == [
        m.rsplit(".", 1)[-1] for m in MIGRATIONS[7:]
    ]
    conn = connect(db)
    try:
        row = conn.execute("SELECT status FROM ref_set WHERE id = 1").fetchone()
        assert row["status"] == "draft"
        generation = conn.execute(
            "SELECT error_text, warning_text FROM generation"
        ).fetchone()
        assert generation["error_text"] is None
        assert "exceeded" in generation["warning_text"]
    finally:
        conn.close()
