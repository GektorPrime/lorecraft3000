from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.db import connect
from app.services.costs import (
    BaseStageChangedError,
    BudgetExceededError,
    CostError,
    CostLedger,
    GenerationPendingError,
    IdempotencyConflictError,
    SceneChangedError,
    UnknownPriceError,
)


def _scene(conn) -> int:
    cursor = conn.execute("INSERT INTO scene (cast_json) VALUES ('[]')")
    conn.commit()
    return int(cursor.lastrowid)


def _settings(tmp_path, cap=0.10):
    return Settings(
        daily_spend_cap_usd=cap,
        db_path=tmp_path / "db.sqlite",
        store_root=tmp_path / "store",
    )


def test_reservation_blocks_before_exceeding_cap(conn, tmp_path):
    first_scene_id = _scene(conn)
    second_scene_id = _scene(conn)
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, estimate = ledger.reserve(
        scene_id=first_scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={"safe": True},
    )
    assert estimate == 7
    assert generation_id > 0
    with pytest.raises(BudgetExceededError, match="daily budget"):
        ledger.reserve(
            scene_id=second_scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="b" * 64,
            request_json={},
        )
    assert ledger.spent_today() == 7


def test_independent_connections_cannot_bypass_cap(db_path, tmp_path):
    first = connect(db_path)
    second = connect(db_path)
    try:
        first_scene_id = _scene(first)
        second_scene_id = _scene(first)
        settings = _settings(tmp_path)
        CostLedger(first, settings).reserve(
            scene_id=first_scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="a" * 64,
            request_json={},
        )
        with pytest.raises(BudgetExceededError):
            CostLedger(second, settings).reserve(
                scene_id=second_scene_id,
                model="gemini-3.1-flash-image",
                image_size="1K",
                prompt_hash="b" * 64,
                request_json={},
            )
    finally:
        first.close()
        second.close()


def test_success_records_candidate_and_sanitized_response(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, _ = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={"prompt": "exact"},
    )
    candidate_id = ledger.succeed(
        generation_id,
        interaction_id="interaction-1",
        response_json={"safe": "metadata"},
        candidate_sha256="b" * 64,
    )
    generation = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (generation_id,)
    ).fetchone()
    assert generation["state"] == "succeeded"
    assert json.loads(generation["response_json"]) == {"safe": "metadata"}
    assert conn.execute(
        "SELECT generation_id FROM candidate WHERE id = ?", (candidate_id,)
    ).fetchone()["generation_id"] == generation_id


def test_failed_call_stays_in_conservative_spend_total(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, _ = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    ledger.fail(generation_id, "provider failed")
    row = conn.execute(
        "SELECT state, error_text, cost_usd_cents FROM generation WHERE id = ?",
        (generation_id,),
    ).fetchone()
    assert tuple(row) == ("failed", "provider failed", 7)
    assert ledger.spent_today() == 7


def test_known_non_billable_failure_releases_reservation(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, _ = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    ledger.fail(generation_id, "HTTP 400", charge_expected=False)
    row = conn.execute(
        "SELECT state, cost_usd_cents FROM generation WHERE id = ?",
        (generation_id,),
    ).fetchone()
    assert tuple(row) == ("failed", 0)
    assert ledger.spent_today() == 0


def test_unverified_price_is_rejected(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    with pytest.raises(UnknownPriceError):
        ledger.estimate("gemini-2.5-flash-image", "1K")


def test_generation_cannot_be_finalized_twice(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, _ = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    ledger.succeed(
        generation_id,
        interaction_id=None,
        response_json={},
        candidate_sha256="b" * 64,
    )
    from app.services.costs import CostError

    with pytest.raises(CostError, match="not pending"):
        ledger.succeed(
            generation_id,
            interaction_id=None,
            response_json={},
            candidate_sha256="c" * 64,
        )
    assert conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 1


def test_only_one_pending_generation_is_allowed_per_scene(conn, tmp_path):
    scene_id = _scene(conn)
    ledger = CostLedger(conn, _settings(tmp_path, cap=1.0))
    ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    with pytest.raises(GenerationPendingError):
        ledger.reserve(
            scene_id=scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="b" * 64,
            request_json={},
        )


def test_idempotency_key_replays_the_same_reservation(conn, tmp_path):
    scene_id = _scene(conn)
    ledger = CostLedger(conn, _settings(tmp_path))
    first = ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
        idempotency_key="request-1",
    )
    replay = ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
        idempotency_key="request-1",
    )
    assert first.created is True
    assert replay.created is False
    assert replay.generation_id == first.generation_id
    assert conn.execute("SELECT COUNT(*) FROM generation").fetchone()[0] == 1

    with pytest.raises(IdempotencyConflictError):
        ledger.reserve(
            scene_id=scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="b" * 64,
            request_json={},
            idempotency_key="request-1",
        )


def test_stale_pending_recovery_releases_lock_but_retains_cost(conn, tmp_path):
    scene_id = _scene(conn)
    ledger = CostLedger(conn, _settings(tmp_path))
    reservation = ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    conn.execute(
        "UPDATE generation SET created_at = datetime('now', '-1 day') WHERE id = ?",
        (reservation.generation_id,),
    )
    conn.commit()

    assert ledger.recover_stale_pending() == 1
    row = conn.execute(
        "SELECT state, cost_usd_cents, reserved_cost_usd_cents FROM generation"
    ).fetchone()
    assert tuple(row) == ("failed", 7, 7)


def test_actual_cost_is_recorded_separately(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    reservation = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    ledger.succeed(
        reservation.generation_id,
        interaction_id=None,
        response_json={},
        candidate_sha256="b" * 64,
        actual_cost_cents=5,
    )
    row = conn.execute(
        "SELECT cost_usd_cents, reserved_cost_usd_cents, actual_cost_usd_cents FROM generation"
    ).fetchone()
    assert tuple(row) == (5, 7, 5)
    assert ledger.spent_today() == 5


def test_actual_cost_over_cap_is_recorded_and_blocks_more_spend(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    reservation = ledger.reserve(
        scene_id=_scene(conn),
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
    )
    ledger.succeed(
        reservation.generation_id,
        interaction_id=None,
        response_json={},
        candidate_sha256="b" * 64,
        actual_cost_cents=11,
    )
    row = conn.execute(
        "SELECT state, cost_usd_cents, actual_cost_usd_cents, warning_text FROM generation"
    ).fetchone()
    assert tuple(row[:3]) == ("succeeded", 11, 11)
    assert "exceeded" in row["warning_text"]
    with pytest.raises(BudgetExceededError):
        ledger.reserve(
            scene_id=_scene(conn),
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="c" * 64,
            request_json={},
        )


def test_reservation_rejects_a_panel_changed_after_preview(conn, tmp_path):
    scene_id = _scene(conn)
    conn.execute("UPDATE scene SET revision = revision + 1 WHERE id = ?", (scene_id,))
    conn.commit()

    with pytest.raises(SceneChangedError, match="changed after preview"):
        CostLedger(conn, _settings(tmp_path)).reserve(
            scene_id=scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="a" * 64,
            request_json={},
            scene_revision=0,
        )


def _insert_reserved(conn, scene_id, cost, created_at):
    conn.execute(
        """
        INSERT INTO generation
            (scene_id, model, params_json, prompt_hash, request_json,
             cost_usd_cents, reserved_cost_usd_cents, state, price_table_version,
             scene_revision, created_at)
        VALUES (?, ?, '{}', ?, '{}', ?, ?, 'succeeded', 'test', 0, ?)
        """,
        (scene_id, "gemini-3.1-flash-image", "x" * 64, cost, cost, created_at),
    )
    conn.commit()


def test_budget_conversion_uses_supplied_timezone(conn, tmp_path):
    """spent_today(tz_name) converts UTC timestamps to the caller's calendar day,
    so the user-local daily boundary is correct regardless of the server timezone."""
    settings = Settings(
        daily_spend_cap_usd=1.0,
        db_path=tmp_path / "db.sqlite",
        store_root=tmp_path / "store",
    )
    ledger = CostLedger(conn, settings)

    # Fixed UTC-4 zone (Etc/GMT+4). At 01:00 UTC the local clock reads 21:00 on
    # the previous calendar day.
    assert ledger._local_date("2026-09-01 01:00:00", "Etc/GMT+4") == "2026-08-31"
    assert ledger._local_date("2026-09-01 04:00:00", "Etc/GMT+4") == "2026-09-01"
    # Without a timezone, the same UTC timestamp maps to its own UTC date.
    assert ledger._local_date("2026-09-01 01:00:00") == "2026-09-01"
    # An invalid timezone falls back to UTC rather than raising.
    assert ledger._local_date("2026-09-01 01:00:00", "Not/AZone") == "2026-09-01"


def test_spent_today_defaults_to_utc_not_server_local(conn, tmp_path):
    """Without a timezone, spent_today() uses the UTC boundary so behaviour is
    identical no matter the server's system timezone (important when hosted)."""
    settings = Settings(
        daily_spend_cap_usd=1.0,
        db_path=tmp_path / "db.sqlite",
        store_root=tmp_path / "store",
    )
    ledger = CostLedger(conn, settings)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    scene_id = _scene(conn)
    _insert_reserved(conn, scene_id, 42, now_utc)

    # Counts as today regardless of the host's local timezone.
    assert ledger.spent_today() == 42


def _base_stage(conn) -> int:
    """A generated draft is a valid, independent generation owner."""
    cursor = conn.execute(
        "INSERT INTO base_stage (origin, state, description, aspect_ratio) "
        "VALUES ('generated', 'draft', 'A ravine', '16:9')"
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_reserve_requires_exactly_one_owner(conn, tmp_path):
    ledger = CostLedger(conn, _settings(tmp_path))
    scene_id = _scene(conn)
    base_stage_id = _base_stage(conn)
    for kwargs in (
        {},
        {"scene_id": scene_id, "base_stage_id": base_stage_id},
    ):
        with pytest.raises(CostError, match="exactly one panel or base stage"):
            ledger.reserve(
                model="gemini-3.1-flash-image",
                image_size="1K",
                prompt_hash="a" * 64,
                request_json={},
                **kwargs,
            )


def test_base_stage_owner_scopes_pending_idempotency_and_revision(conn, tmp_path):
    """Owner-scoped rules must apply to base stages exactly as to panels."""
    ledger = CostLedger(conn, _settings(tmp_path, cap=1.0))
    base_stage_id = _base_stage(conn)
    scene_id = _scene(conn)

    reservation = ledger.reserve(
        base_stage_id=base_stage_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
        idempotency_key="stage-key",
        base_stage_revision=0,
    )
    row = conn.execute(
        "SELECT scene_id, base_stage_id FROM generation WHERE id = ?",
        (reservation.generation_id,),
    ).fetchone()
    assert (row["scene_id"], row["base_stage_id"]) == (None, base_stage_id)

    # Replay is scoped to the same owner and returns the same attempt.
    replay = ledger.reserve(
        base_stage_id=base_stage_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={},
        idempotency_key="stage-key",
        base_stage_revision=0,
    )
    assert replay.created is False
    assert replay.generation_id == reservation.generation_id

    # A pending stage attempt blocks only that stage, never a panel.
    with pytest.raises(GenerationPendingError, match="base stage"):
        ledger.reserve(
            base_stage_id=base_stage_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="b" * 64,
            request_json={},
        )
    assert ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="c" * 64,
        request_json={},
    ).created

    # An edited composition invalidates the reviewed preview.
    conn.execute(
        "UPDATE base_stage SET revision = revision + 1 WHERE id = ?", (base_stage_id,)
    )
    conn.commit()
    ledger.fail(reservation.generation_id, "done", charge_expected=False)
    with pytest.raises(BaseStageChangedError, match="changed after preview"):
        ledger.reserve(
            base_stage_id=base_stage_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="d" * 64,
            request_json={},
            base_stage_revision=0,
        )
