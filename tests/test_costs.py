from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.db import connect
from app.services.costs import BudgetExceededError, CostLedger, UnknownPriceError


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
    scene_id = _scene(conn)
    ledger = CostLedger(conn, _settings(tmp_path))
    generation_id, estimate = ledger.reserve(
        scene_id=scene_id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        prompt_hash="a" * 64,
        request_json={"safe": True},
    )
    assert estimate == 7
    assert generation_id > 0
    with pytest.raises(BudgetExceededError, match="daily budget"):
        ledger.reserve(
            scene_id=scene_id,
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
        scene_id = _scene(first)
        settings = _settings(tmp_path)
        CostLedger(first, settings).reserve(
            scene_id=scene_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            prompt_hash="a" * 64,
            request_json={},
        )
        with pytest.raises(BudgetExceededError):
            CostLedger(second, settings).reserve(
                scene_id=scene_id,
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
