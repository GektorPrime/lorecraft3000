"""Tests for append-only database provenance (Phase 3 Work Package 3).

The ``image_provenance`` table is the authoritative provenance record; the
sidecar ``provenance`` list is a best-effort mirror.
"""

from __future__ import annotations

import json
import threading

import pytest

from app.services.generation import GenerationError, GenerationService
from tests.test_generation_service import (
    FakeProvider,
    _character_with_canon,
    _scene,
    _settings,
)


def _rows(conn):
    return list(conn.execute("SELECT * FROM image_provenance ORDER BY id"))


def test_successful_generation_records_database_provenance(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    outcome = GenerationService(
        conn, storage, _settings(tmp_path), FakeProvider()
    ).generate(scene_id)

    rows = _rows(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["generation_id"] == outcome.generation_id
    assert row["sha256"] == outcome.candidate_sha256
    assert row["interaction_id"] == "interaction-fake"
    assert row["prompt_hash"] == outcome.prompt_hash
    assert row["cost_cents"] == 7
    assert row["price_table_version"] == _settings(tmp_path).price_table_version
    assert len(json.loads(row["input_images"])) == 1
    # No secret material ever reaches the record.
    assert "SECRET" not in json.dumps(dict(row))

    # The sidecar mirror matches the authoritative record for the same fields.
    _, sidecar = storage.read(outcome.candidate_sha256)
    mirror = sidecar["provenance"][0]
    assert mirror["generation_id"] == row["generation_id"]
    assert mirror["prompt_hash"] == row["prompt_hash"]
    assert mirror["cost_cents"] == row["cost_cents"]


def test_provenance_and_candidate_commit_roll_back_together(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])

    # Force the candidate insert to fail inside the succeed transaction.
    conn.execute(
        "CREATE TRIGGER trg_block_candidate BEFORE INSERT ON candidate "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )
    conn.commit()

    with pytest.raises(GenerationError, match="blocked"):
        GenerationService(
            conn, storage, _settings(tmp_path), FakeProvider()
        ).generate(scene_id)

    conn.execute("DROP TRIGGER trg_block_candidate")
    conn.commit()

    # The whole succeed transaction rolled back: no candidate, no provenance,
    # and the generation was subsequently marked failed.
    row = conn.execute("SELECT state FROM generation").fetchone()
    assert row["state"] == "failed"
    assert conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 0
    assert len(_rows(conn)) == 0


def test_two_generations_same_image_bytes_record_both_provenance_rows(
    conn, storage, tmp_path
):
    """Byte-identical outcomes share the sidecar but each keeps its DB record."""
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])

    class SameImageProvider:
        def generate(self, request):
            return FakeProvider().generate(request)

    service = GenerationService(conn, storage, _settings(tmp_path), SameImageProvider())
    first = service.generate(scene_id)
    second = service.generate(scene_id)

    assert first.candidate_sha256 == second.candidate_sha256
    rows = _rows(conn)
    assert [set(r.keys()) for r in rows]  # sanity: rows exist
    assert len(rows) == 2
    assert rows[0]["generation_id"] != rows[1]["generation_id"]
    assert {r["sha256"] for r in rows} == {first.candidate_sha256}

    # Both sidecar mirror entries are present (dedup shares one sidecar).
    _, sidecar = storage.read(first.candidate_sha256)
    assert len(sidecar["provenance"]) == 2


def test_concurrent_sidecar_appends_to_same_hash_are_not_lost(storage, png_bytes):
    meta = storage.store(png_bytes)
    records = [{"generation_id": i, "note": f"record-{i}"} for i in range(1, 21)]
    errors: list[Exception] = []

    def append(record: dict) -> None:
        try:
            storage.append_provenance(meta.sha256, record)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=append, args=(record,)) for record in records
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    _, sidecar = storage.read(meta.sha256)
    assert len(sidecar["provenance"]) == len(records)
    generation_ids = {
        record["generation_id"] for record in sidecar["provenance"]
    }
    assert generation_ids == {record["generation_id"] for record in records}