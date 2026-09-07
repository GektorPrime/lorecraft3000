from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.providers.base import ProviderResult
from app.providers.base import ProviderEditRequest
from app.services.base_stages import (
    BaseStageLockedError,
    BaseStageNotReadyError,
    BaseStageService,
    BaseStageValidationError,
)
from app.services.characters import CharacterService
from app.services.generation import GenerationError, GenerationService, PreviewChangedError
from tests.conftest import FakeEmbedder
from app.services.costs import CostLedger, IdempotencyConflictError
from app.services.ref_sets import RefSetService
from app.services.styles import StyleService
from tests.conftest import make_png_bytes


class FakeProvider:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.requests = []
        self.edits = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((20, 40, 80)),
            "interaction-fake",
            {"provider": "fake"},
        )

    def edit(self, request):
        self.edits.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((90, 10, 60)),
            "interaction-edit",
            {"provider": "fake", "edited": True},
        )


class FakeProviderRegistry:
    def __init__(self, provider):
        self.provider = provider
        self.models = []

    def for_model(self, model):
        self.models.append(model)
        return self.provider


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


def _staged_scene(conn, storage, tmp_path, character_id):
    stage = BaseStageService(conn, storage).upload(
        make_png_bytes((4, 5, 6)), "A figure stands at the gate.", ["figure at gate"]
    )
    from app.services.scenes import SceneService

    style = StyleService(conn).create(
        name="Selected Scene Style",
        style_contract="SELECTED SCENE STYLE CONTRACT",
    )

    scene = SceneService(conn, _settings(tmp_path)).create(
        beat_text=None,
        camera=None,
        framing=None,
        mood=None,
        aspect_ratio="1:1",
        cast=[
            {
                "character_id": character_id,
                "base_stage_target_id": stage.targets[0].id,
            }
        ],
        style_id=style.id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        base_stage_id=stage.id,
    )
    return stage, scene


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
    assert capture["schema_version"] == 2
    assert capture["operation"] == "direct_scene_generate"
    assert [item["sha256"] for item in capture["input_images"]] == [
        elias_image.sha256, mara_image.sha256
    ]
    assert capture["cast"][0]["ref_set_version"] == elias_set.version
    assert capture["cast"][1]["ref_set_version"] == mara_set.version
    assert [item["character_name"] for item in capture["attachments"]] == [
        "ELIAS", "MARA"
    ]
    assert "data" not in json.dumps(capture)

    _, sidecar = storage.read(outcome.candidate_sha256)
    provenance = sidecar["provenance"][0]
    assert provenance["schema_version"] == 2
    assert provenance["operation"] == "direct_scene_generate"
    assert provenance["input_images"][0]["sha256"] == elias_image.sha256
    assert provenance["input_images"][1]["sha256"] == mara_image.sha256
    assert provenance["generation_id"] == outcome.generation_id
    assert provenance["prompt_hash"] == outcome.prompt_hash
    assert provenance["interaction_id"] == "interaction-fake"
    assert provenance["cost_cents"] == 7
    assert provenance["created_at"]
    assert len(provenance["input_images"]) == 2
    assert "SECRET" not in json.dumps(provenance)


def test_staged_preview_and_generation_use_edit_with_source_aware_provenance(
    conn, storage, tmp_path, monkeypatch
):
    character, _, ref_image = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    stage, scene = _staged_scene(conn, storage, tmp_path, character.id)
    scoring_calls = []
    monkeypatch.setattr("app.services.generation.get_embedder", lambda: object())
    monkeypatch.setattr(
        "app.services.generation.load_gallery_for_attachments",
        lambda _conn, _att: {character.id: [("sha-ref", object())]},
    )
    monkeypatch.setattr(
        "app.services.generation.score_generated_image",
        lambda embedder, gallery, data, cast_ids: scoring_calls.append(cast_ids),
    )
    provider = FakeProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)

    preview = service.preview(scene.id)
    assert isinstance(preview.provider_request, ProviderEditRequest)
    assert preview.provider_request.source_image == make_png_bytes((4, 5, 6))
    assert preview.provider_request.source_interaction_id is None
    assert [ref.image_number for ref in preview.provider_request.references] == [2]
    assert preview.request_capture["operation"] == "base_stage_scene_generate"
    assert preview.request_capture["base_stage"]["id"] == stage.id
    assert preview.request_capture["base_stage"]["content_sha256"]
    assert "SELECTED SCENE STYLE CONTRACT" in preview.provider_request.prompt
    assert [item["image_number"] for item in preview.request_capture["input_images"]] == [1, 2]
    assert preview.request_capture["input_images"][1]["sha256"] == ref_image.sha256

    outcome = service.generate(scene.id, expected_prompt_hash=preview.prompt_hash)
    assert provider.requests == []
    assert len(provider.edits) == 1
    assert scoring_calls == [(character.id,)]
    provenance = conn.execute(
        "SELECT input_images FROM image_provenance WHERE generation_id = ?",
        (outcome.generation_id,),
    ).fetchone()
    inputs = json.loads(provenance["input_images"])
    assert [item["image_number"] for item in inputs] == [1, 2]
    assert inputs[0]["base_stage_id"] == stage.id


def _generated_stage(conn, storage, tmp_path, **overrides):
    fields = {
        "description": "Four figures haul a machine up a muddy ravine.",
        "beat_text": "They strain against the rope as the machine slips.",
        "camera": "twenty metres away, slightly elevated",
        "framing": "wide environmental shot",
        "mood": "strenuous and apprehensive",
        "aspect_ratio": "16:9",
        "style_id": StyleService(conn).get_default().id,
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
        "targets": ["figure above the slope", "figure beside the oak"],
    }
    fields.update(overrides)
    return BaseStageService(conn, storage, _settings(tmp_path)).create_generated(**fields)


def test_base_stage_preview_is_identity_neutral_and_uses_the_generate_path(
    conn, storage, tmp_path, monkeypatch
):
    """A Base Stage carries no cast: no references, no edit, no identity scoring."""
    stage = _generated_stage(conn, storage, tmp_path)
    scored = []
    monkeypatch.setattr("app.services.generation.get_embedder", lambda: object())
    monkeypatch.setattr(
        "app.services.generation.load_gallery_for_attachments",
        lambda _conn, _att: {},
    )
    monkeypatch.setattr(
        "app.services.generation.score_generated_image",
        lambda embedder, gallery, data, cast_ids: scored.append(cast_ids),
    )
    provider = FakeProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)

    preview = service.preview_base_stage(stage.id)
    assert preview.scene_id is None
    assert preview.base_stage_id == stage.id
    assert preview.provider_request.references == ()
    assert preview.attachments == ()
    assert preview.request_capture["operation"] == "base_stage_generate"
    assert preview.request_capture["cast"] == []
    assert "figure above the slope" in preview.prompt
    assert "IDENTITY TARGETS" in preview.prompt

    outcome = service.generate_base_stage(
        stage.id, expected_prompt_hash=preview.prompt_hash
    )
    assert provider.edits == []
    assert len(provider.requests) == 1
    assert scored == []  # no cast -> never identity-scored

    row = conn.execute(
        "SELECT scene_id, base_stage_id FROM generation WHERE id = ?",
        (outcome.generation_id,),
    ).fetchone()
    assert (row["scene_id"], row["base_stage_id"]) == (None, stage.id)


def test_base_stage_generation_enforces_drift_pending_and_idempotency(
    conn, storage, tmp_path
):
    stage = _generated_stage(conn, storage, tmp_path)
    provider = FakeProvider()
    settings = _settings(tmp_path)
    service = GenerationService(conn, storage, settings, provider)
    stages = BaseStageService(conn, storage, settings)

    reviewed = service.preview_base_stage(stage.id)
    stages.update(
        stage.id,
        description="A different composition entirely.",
        beat_text="They stand still.",
        camera="close",
        framing="tight",
        mood="calm",
        aspect_ratio="16:9",
        style_id=StyleService(conn).get_default().id,
        model="gemini-3.1-flash-image",
        image_size="1K",
        targets=["only figure"],
    )
    with pytest.raises(PreviewChangedError):
        service.generate_base_stage(
            stage.id, expected_prompt_hash=reviewed.prompt_hash
        )
    assert provider.requests == []

    first = service.generate_base_stage(stage.id, idempotency_key="stage-1")
    replay = service.generate_base_stage(stage.id, idempotency_key="stage-1")
    assert replay.replayed is True
    assert replay.generation_id == first.generation_id
    assert len(provider.requests) == 1

    # A successful attempt locks the composition; duplicate to change it.
    assert stages.is_editable(stage.id) is False


def test_publish_promotes_one_candidate_and_freezes_the_stage(
    conn, storage, tmp_path
):
    stage = _generated_stage(conn, storage, tmp_path)
    settings = _settings(tmp_path)
    service = GenerationService(conn, storage, settings, FakeProvider())
    stages = BaseStageService(conn, storage, settings)

    with pytest.raises(BaseStageNotReadyError):
        stages.content_sha(stage.id)

    outcome = service.generate_base_stage(stage.id)
    published = stages.publish(stage.id, outcome.candidate_id)
    assert published.state == "ready"
    assert published.selected_candidate_id == outcome.candidate_id
    assert (published.image_width, published.image_height) == (8, 8)
    assert stages.content_sha(stage.id) == outcome.candidate_sha256

    # Promotion is one-way: the source image any scene generates from is frozen.
    with pytest.raises(BaseStageLockedError):
        stages.publish(stage.id, outcome.candidate_id)
    with pytest.raises(BaseStageLockedError):
        stages.update(
            stage.id,
            description="d",
            beat_text="b",
            camera="c",
            framing="f",
            mood="",
            aspect_ratio="16:9",
            style_id=StyleService(conn).get_default().id,
            model="gemini-3.1-flash-image",
            image_size="1K",
            targets=["t"],
        )
    with pytest.raises(GenerationError, match="already published"):
        service.preview_base_stage(stage.id)


def test_publish_rejects_candidates_from_another_owner(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id, "prominence": 1}])
    settings = _settings(tmp_path)
    service = GenerationService(conn, storage, settings, FakeProvider())
    scene_outcome = service.generate(scene_id)

    stage = _generated_stage(conn, storage, tmp_path)
    stages = BaseStageService(conn, storage, settings)
    with pytest.raises(BaseStageValidationError, match="not a succeeded candidate"):
        stages.publish(stage.id, scene_outcome.candidate_id)
    assert stages.get(stage.id).state == "draft"


def test_duplicate_copies_composition_without_attempts_or_image(
    conn, storage, tmp_path
):
    stage = _generated_stage(conn, storage, tmp_path)
    settings = _settings(tmp_path)
    service = GenerationService(conn, storage, settings, FakeProvider())
    stages = BaseStageService(conn, storage, settings)
    outcome = service.generate_base_stage(stage.id)
    stages.publish(stage.id, outcome.candidate_id)

    copy = stages.duplicate(stage.id)
    assert copy.id != stage.id
    assert copy.state == "draft"
    assert copy.selected_candidate_id is None
    assert copy.description == stage.description
    assert [target.description for target in copy.targets] == [
        target.description for target in stage.targets
    ]
    assert stages.is_editable(copy.id) is True


def test_staged_prompt_drift_failure_and_idempotency_use_edit_path(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    stage, scene = _staged_scene(conn, storage, tmp_path, character.id)
    provider = FakeProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    reviewed = service.preview(scene.id)
    conn.execute(
        "UPDATE base_stage SET description = 'Changed source description' WHERE id = ?",
        (stage.id,),
    )
    conn.commit()
    with pytest.raises(PreviewChangedError):
        service.generate(scene.id, expected_prompt_hash=reviewed.prompt_hash)
    assert provider.edits == []

    first = service.generate(scene.id, idempotency_key="staged-1")
    replay = service.generate(scene.id, idempotency_key="staged-1")
    assert replay.replayed is True
    assert replay.generation_id == first.generation_id
    assert len(provider.edits) == 1

    failing = FakeProvider(error=RuntimeError("edit failed"))
    with pytest.raises(GenerationError, match="edit failed"):
        GenerationService(conn, storage, _settings(tmp_path), failing).generate(scene.id)
    assert failing.requests == []
    assert len(failing.edits) == 1


def test_generation_resolves_provider_from_selected_model(conn, storage, tmp_path):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider()
    registry = FakeProviderRegistry(provider)

    GenerationService(conn, storage, _settings(tmp_path), registry).generate(
        scene_id, model="gemini-3-pro-image"
    )

    assert registry.models == ["gemini-3-pro-image"]
    assert len(provider.requests) == 1


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


def test_changed_preview_hash_fails_before_reservation_or_provider(
    conn, storage, tmp_path
):
    character, _, _ = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id}])
    provider = FakeProvider()
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    reviewed = service.preview(scene_id)

    style = StyleService(conn).get_default()
    StyleService(conn).update(
        style.id,
        name=style.name,
        style_contract=f"{style.style_contract}\nChanged after preview.",
    )

    with pytest.raises(PreviewChangedError, match="changed after preview"):
        service.generate(scene_id, expected_prompt_hash=reviewed.prompt_hash)
    assert provider.requests == []
    assert conn.execute("SELECT COUNT(*) FROM generation").fetchone()[0] == 0


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


def test_idempotency_key_cannot_be_reused_after_scene_edit(
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


# ---------------------------------------------------------------------------
# candidate editing (multi-turn)
# ---------------------------------------------------------------------------


def _generate_one(conn, storage, tmp_path, provider):
    character, _, ref_image = _character_with_canon(
        conn, storage, "ELIAS", "elias", (100, 20, 20)
    )
    scene_id = _scene(conn, [{"character_id": character.id, "role": "stands"}])
    service = GenerationService(conn, storage, _settings(tmp_path), provider)
    outcome = service.generate(scene_id)
    return service, outcome, ref_image


def test_edit_creates_child_generation_with_new_candidate(conn, storage, tmp_path):
    provider = FakeProvider()
    service, first, ref_image = _generate_one(conn, storage, tmp_path, provider)

    edited = service.edit_candidate(first.candidate_id, "make it night")

    assert len(provider.edits) == 1
    edit_request = provider.edits[0]
    # The instruction and the original prompt context both reach the provider.
    assert edit_request.instruction == "make it night"
    assert "canonical reference for ELIAS" in edit_request.prompt
    # Identity is anchored: the canonical reference travels with the edit.
    assert [ref.sha256 for ref in edit_request.references] == [ref_image.sha256]
    assert edit_request.source_image  # source bytes supplied
    assert edit_request.source_interaction_id == "interaction-fake"

    row = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (edited.generation_id,)
    ).fetchone()
    assert row["state"] == "succeeded"
    assert row["parent_generation_id"] == first.generation_id
    capture = json.loads(row["request_json"])
    assert capture["kind"] == "edit"
    assert capture["edit_instruction"] == "make it night"
    assert capture["source_candidate_id"] == first.candidate_id


def test_edit_capture_and_provenance_record_source_first(
    conn, storage, tmp_path, monkeypatch
):
    """An edit's capture/provenance are versioned and list source before refs."""
    provider = FakeProvider()
    service, first, ref_image = _generate_one(conn, storage, tmp_path, provider)
    char_id = json.loads(
        conn.execute(
            "SELECT request_json FROM generation WHERE id = ?",
            (first.generation_id,),
        ).fetchone()[0]
    )["cast"][0]["character_id"]

    edited = service.edit_candidate(first.candidate_id, "make it night")

    row = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (edited.generation_id,)
    ).fetchone()
    capture = json.loads(row["request_json"])
    assert capture["schema_version"] == 2
    assert capture["operation"] == "candidate_edit"
    inputs = capture["input_images"]
    assert inputs[0]["kind"] == "candidate_source"
    assert inputs[0]["sha256"] == first.candidate_sha256
    assert inputs[0]["source_candidate_id"] == first.candidate_id
    assert inputs[1]["sha256"] == ref_image.sha256
    assert inputs[1]["character_id"] == char_id

    provenance = conn.execute(
        "SELECT input_images FROM image_provenance WHERE generation_id = ?",
        (edited.generation_id,),
    ).fetchone()
    prov_inputs = json.loads(provenance["input_images"])
    assert prov_inputs[0]["sha256"] == first.candidate_sha256
    assert prov_inputs[1]["sha256"] == ref_image.sha256

    _, sidecar = storage.read(edited.candidate_sha256)
    sidecar_provenance = sidecar["provenance"][0]
    assert sidecar_provenance["schema_version"] == 2
    assert sidecar_provenance["operation"] == "candidate_edit"
    assert sidecar_provenance["input_images"][0]["sha256"] == first.candidate_sha256


def test_edit_goes_through_shared_identity_scoring(conn, storage, tmp_path, monkeypatch):
    """Edited candidates are identity-scored through the shared path."""
    scored = []
    monkeypatch.setattr("app.services.generation.get_embedder", lambda: object())
    monkeypatch.setattr(
        "app.services.generation.load_gallery_for_attachments",
        lambda _conn, _att: {1: [("sha-ref", object())]},
    )
    monkeypatch.setattr(
        "app.services.generation.score_generated_image",
        lambda embedder, gallery, data, cast_ids: (scored.append(cast_ids), None)[1],
    )
    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)

    service.edit_candidate(first.candidate_id, "make it night")
    assert scored  # the edit path scored its candidate against captured refs


def test_edit_requires_instruction(conn, storage, tmp_path):
    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)
    with pytest.raises(GenerationError, match="edit instruction is required"):
        service.edit_candidate(first.candidate_id, "   ")
    assert provider.edits == []


def test_edit_of_missing_candidate_is_not_found(conn, storage, tmp_path):
    service = GenerationService(conn, storage, _settings(tmp_path), FakeProvider())
    from app.services.generation import GenerationNotFoundError

    with pytest.raises(GenerationNotFoundError):
        service.edit_candidate(999, "make it night")


def test_edit_failure_marks_child_failed_and_keeps_reservation(
    conn, storage, tmp_path
):
    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)
    provider.error = RuntimeError("edit boom")
    with pytest.raises(GenerationError, match="edit boom"):
        service.edit_candidate(first.candidate_id, "make it night")
    child = conn.execute(
        "SELECT state, cost_usd_cents FROM generation WHERE parent_generation_id = ?",
        (first.generation_id,),
    ).fetchone()
    assert tuple(child) == ("failed", 7)


def test_edit_is_idempotent_on_replay(conn, storage, tmp_path):
    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)
    a = service.edit_candidate(
        first.candidate_id, "make it night", idempotency_key="edit-1"
    )
    b = service.edit_candidate(
        first.candidate_id, "make it night", idempotency_key="edit-1"
    )
    assert b.replayed is True
    assert b.generation_id == a.generation_id
    assert len(provider.edits) == 1


def test_identity_scoring_populates_candidate(conn, storage, tmp_path, monkeypatch):
    """With an embedder available, a candidate gains advisory identity scores."""
    embedder = FakeEmbedder()
    gallery = {1: [("sha", embedder.face)]}
    monkeypatch.setattr("app.services.generation.get_embedder", lambda: embedder)
    monkeypatch.setattr(
        "app.services.generation.load_gallery_for_attachments",
        lambda _conn, _att: gallery,
    )

    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)

    row = conn.execute(
        "SELECT identity_scores FROM candidate WHERE id = ?", (first.candidate_id,)
    ).fetchone()
    payload = json.loads(row["identity_scores"])
    assert set(payload["cast"]) == {"1"}
    assert payload["faces_detected"] == 1
    assert payload["cast"]["1"] > 0.5


def test_identity_scoring_failure_is_non_fatal(
    conn, storage, tmp_path, monkeypatch
):
    """A broken embedder must never fail a paid generation."""
    monkeypatch.setattr(
        "app.services.generation.get_embedder",
        lambda: FakeEmbedder(error=RuntimeError("face model crashed")),
    )

    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)

    state = conn.execute(
        "SELECT state FROM generation WHERE id = ?",
        (first.generation_id,),
    ).fetchone()
    assert state["state"] == "succeeded"
    row = conn.execute(
        "SELECT identity_scores FROM candidate WHERE id = ?", (first.candidate_id,)
    ).fetchone()
    assert json.loads(row["identity_scores"]) == {}


def test_identity_scoring_absent_embedder_leaves_scores_empty(
    conn, storage, tmp_path, monkeypatch
):
    """No insightface installed behaves the same as in CI: scores stay {}."""
    monkeypatch.setattr("app.services.generation.get_embedder", lambda: None)

    provider = FakeProvider()
    service, first, _ = _generate_one(conn, storage, tmp_path, provider)

    row = conn.execute(
        "SELECT identity_scores FROM candidate WHERE id = ?", (first.candidate_id,)
    ).fetchone()
    assert json.loads(row["identity_scores"]) == {}
