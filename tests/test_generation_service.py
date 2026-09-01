from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.providers.base import ProviderResult
from app.services.characters import CharacterService
from app.services.generation import GenerationError, GenerationService
from app.services.costs import CostLedger, IdempotencyConflictError
from app.services.ref_sets import RefSetService
from app.services.styles import StyleService
from tests.conftest import make_png_bytes


class FakeProvider:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((20, 40, 80)),
            "interaction-fake",
            {"provider": "fake"},
        )


def _settings(tmp_path):
    return Settings(
        daily_spend_cap_usd=3.0,
        db_path=tmp_path / "db.sqlite",
        store_root=tmp_path / "store",
    )


def _character_with_canon(conn, storage, name, slug, color):
    character = CharacterService(conn).create(
        name=name,
        slug=slug,
        lore_md=f"SECRET LORE FOR {name}",
        visual_contract=f"Distinctive face of {name}.",
        negative_traits="identity blending",
    )
    refs = RefSetService(conn, storage)
    ref_set = refs.create_draft(character.id)
    image = refs.add_image(
        ref_set.id, make_png_bytes(color), "face_front", source_name=f"{slug}.png"
    )
    refs.promote(ref_set.id)
    return character, ref_set, image


def _scene(conn, cast):
    style = StyleService(conn).get_default()
    cursor = conn.execute(
        """
        INSERT INTO scene
            (beat_text, camera, framing, mood, aspect_ratio, cast_json, style_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "Elias and Mara compare the map beside the fire.",
            "eye level",
            "medium two-shot",
            "tense",
            "3:2",
            json.dumps(cast),
            style.id,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_two_character_fake_generation_captures_complete_provenance(
    conn, storage, tmp_path
):
    elias, elias_set, elias_image = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    mara, mara_set, mara_image = _character_with_canon(
        conn, storage, "MARA", "mara", (20, 100, 20)
    )
    scene_id = _scene(
        conn,
        [
            {"character_id": elias.id, "role": "holds the map", "prominence": 2},
            {"character_id": mara.id, "role": "points to the route", "prominence": 1},
        ],
    )
    provider = FakeProvider()
    outcome = GenerationService(
        conn, storage, _settings(tmp_path), provider
    ).generate(scene_id)

    assert outcome.cost_cents == 7
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert [ref.sha256 for ref in request.references] == [
        elias_image.sha256, mara_image.sha256
    ]
    assert "SECRET LORE" not in request.prompt
    assert "Image 1 is a canonical reference for ELIAS" in request.prompt
    assert "Image 2 is a canonical reference for MARA" in request.prompt

    generation = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (outcome.generation_id,)
    ).fetchone()
    capture = json.loads(generation["request_json"])
    assert generation["state"] == "succeeded"
    assert generation["interaction_id"] == "interaction-fake"
    assert capture["cast"][0]["ref_set_version"] == elias_set.version
    assert capture["cast"][1]["ref_set_version"] == mara_set.version
    assert [item["character_name"] for item in capture["attachments"]] == [
        "ELIAS", "MARA"
    ]
    assert "data" not in json.dumps(capture)

    _, sidecar = storage.read(outcome.candidate_sha256)
    provenance = sidecar["provenance"][0]
    assert provenance["generation_id"] == outcome.generation_id
    assert provenance["prompt_hash"] == outcome.prompt_hash
    assert provenance["interaction_id"] == "interaction-fake"
    assert provenance["cost_cents"] == 7
    assert provenance["created_at"]
    assert len(provenance["input_images"]) == 2
    assert "SECRET" not in json.dumps(provenance)


def test_provider_failure_marks_generation_failed_and_keeps_reservation(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    service = GenerationService(
        conn, storage, _settings(tmp_path), FakeProvider(error=RuntimeError("boom"))
    )
    with pytest.raises(GenerationError, match="boom"):
        service.generate(scene_id)
    row = conn.execute("SELECT state, cost_usd_cents FROM generation").fetchone()
    assert tuple(row) == ("failed", 7)
    assert conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 0


def test_idempotent_replay_does_not_call_provider_twice(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)

    first = service.generate(scene_id, idempotency_key="request-1")
    replay = service.generate(scene_id, idempotency_key="request-1")

    assert replay.replayed is True
    assert replay.generation_id == first.generation_id
    assert replay.candidate_id == first.candidate_id
    assert len(provider.requests) == 1


def test_storage_failure_records_known_actual_provider_cost(
    conn, storage, tmp_path, monkeypatch
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])

    class BilledProvider:
        def generate(self, request):
            return ProviderResult(
                make_png_bytes(), "interaction", {}, billed_cost_cents=11
            )

    def fail_store(*args, **kwargs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(storage, "store", fail_store)
    with pytest.raises(GenerationError, match="disk unavailable"):
        GenerationService(
            conn, storage, _settings(tmp_path), BilledProvider()
        ).generate(scene_id)

    row = conn.execute(
        "SELECT state, cost_usd_cents, actual_cost_usd_cents FROM generation"
    ).fetchone()
    assert tuple(row) == ("failed", 11, 11)


def test_idempotency_key_cannot_be_reused_after_panel_edit(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider(error=RuntimeError("provider unavailable"))
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    with pytest.raises(GenerationError):
        service.generate(scene_id, idempotency_key="request-1")

    conn.execute("UPDATE scene SET revision = revision + 1 WHERE id = ?", (scene_id,))
    conn.commit()
    with pytest.raises(IdempotencyConflictError, match="different request"):
        service.generate(scene_id, idempotency_key="request-1")
    assert len(provider.requests) == 1


def test_idempotency_key_detects_changed_style_prompt(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider(error=RuntimeError("provider unavailable"))
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    with pytest.raises(GenerationError):
        service.generate(scene_id, idempotency_key="request-1")

    styles = StyleService(conn)
    style = styles.get_default()
    styles.update(
        style.id,
        name=style.name,
        style_contract=f"{style.style_contract}\nChanged after the first attempt.",
    )
    with pytest.raises(IdempotencyConflictError, match="different request"):
        service.generate(scene_id, idempotency_key="request-1")
    assert len(provider.requests) == 1


def test_stale_idempotent_attempt_is_recovered_before_replay(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider()
    settings = _settings(tmp_path)
    service = GenerationService(conn, storage, settings, provider)
    preview = service.preview(scene_id, check_budget=False)
    reservation = CostLedger(conn, settings).reserve(
        scene_id=scene_id,
        model=preview.model,
        image_size=preview.image_size,
        prompt_hash=preview.prompt_hash,
        request_json=preview.request_capture,
        idempotency_key="request-1",
        scene_revision=preview.scene_revision,
    )
    conn.execute(
        "UPDATE generation SET created_at = datetime('now', '-1 day') WHERE id = ?",
        (reservation.generation_id,),
    )
    conn.commit()

    replay = service.generate(scene_id, idempotency_key="request-1")
    assert replay.replayed is True
    row = conn.execute(
        "SELECT state FROM generation WHERE id = ?", (reservation.generation_id,)
    ).fetchone()
    assert row["state"] == "failed"
    assert provider.requests == []


def test_accounting_warning_is_returned_for_new_and_replayed_outcome(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])

    class BilledProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            return ProviderResult(
                make_png_bytes(), "interaction", {}, billed_cost_cents=301
            )

    provider = BilledProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    first = service.generate(scene_id, idempotency_key="request-1")
    replay = service.generate(scene_id, idempotency_key="request-1")

    assert any("exceeded" in warning for warning in first.warnings)
    assert any("exceeded" in warning for warning in replay.warnings)
    assert provider.calls == 1


def test_missing_canonical_fails_before_provider_or_ledger(conn, storage, tmp_path):
    character = CharacterService(conn).create(name="ELIAS", slug="elias")
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider()
    with pytest.raises(GenerationError, match="no canonical reference set"):
        GenerationService(conn, storage, _settings(tmp_path), provider).generate(scene_id)
    assert provider.requests == []
    assert conn.execute("SELECT COUNT(*) FROM generation").fetchone()[0] == 0


def test_duplicate_cast_member_fails_before_spend(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(
        conn,
        [{"character_id": character.id}, {"character_id": character.id}],
    )
    with pytest.raises(GenerationError, match="appears twice"):
        GenerationService(conn, storage, _settings(tmp_path), FakeProvider()).generate(
            scene_id
        )


def test_duplicate_cast_names_fail_as_ambiguous(conn, storage, tmp_path):
    first, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias-one", (100, 20, 20)
    )
    second, _, _ = _character_with_canon(
        conn, storage, "elias", "elias-two", (20, 100, 20)
    )
    scene_id = _scene(
        conn,
        [{"character_id": first.id}, {"character_id": second.id}],
    )
    with pytest.raises(GenerationError, match="ambiguous"):
        GenerationService(conn, storage, _settings(tmp_path), FakeProvider()).generate(
            scene_id
        )
