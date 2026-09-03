"""Tests for Phase 4 consolidation pieces.

Covers the ModelRegistry (single source of model/size/ratio capabilities), the
new CandidateService, generation history reads (list_for_scene /
get_with_candidates), content-sha resolution for ref images and candidates,
the ASPECT_RATIOS re-export, and a wire-stability comparison of the /api/v1
path + method surface against the pre-split route set (a regression tripwire
for the router refactor).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db import connect
from app.main import app
from app.migrate import run_migrations
from app.models import ModelRegistry
from app.services.candidates import CandidateNotFoundError, CandidateService
from app.services.generation import GenerationNotFoundError, GenerationService
from app.services.ref_sets import RefImageNotFoundError, RefSetService
from app.services.scenes import ASPECT_RATIOS  # re-export from app.models
from app.storage import ImageStorage
from tests.conftest import make_png_bytes

# The exact path+method surface of app/routes/api_v1.py before the split into
# resource routers. If this set ever changes, the change is a deliberate API
# contract change (bump the frontend client together with it), not an
# incidental refactor artifact.
WIRE_SURFACE = {
    ("GET", "/api/v1/options/summary"),
    ("GET", "/api/v1/budget"),
    ("GET", "/api/v1/characters"),
    ("POST", "/api/v1/characters"),
    ("GET", "/api/v1/characters/archived"),
    ("GET", "/api/v1/characters/{character_id}"),
    ("PUT", "/api/v1/characters/{character_id}"),
    ("DELETE", "/api/v1/characters/{character_id}"),
    ("POST", "/api/v1/characters/{character_id}/restore"),
    ("GET", "/api/v1/characters/{character_id}/ref-sets"),
    ("POST", "/api/v1/characters/{character_id}/ref-sets"),
    ("GET", "/api/v1/ref-sets/{ref_set_id}"),
    ("POST", "/api/v1/ref-sets/{ref_set_id}/copy"),
    ("POST", "/api/v1/ref-sets/{ref_set_id}/promote"),
    ("POST", "/api/v1/ref-sets/{ref_set_id}/images"),
    ("PATCH", "/api/v1/ref-sets/{ref_set_id}/images/{image_id}"),
    ("DELETE", "/api/v1/ref-sets/{ref_set_id}/images/{image_id}"),
    ("GET", "/api/v1/ref-images/{image_id}/content"),
    ("GET", "/api/v1/styles"),
    ("POST", "/api/v1/styles"),
    ("GET", "/api/v1/styles/archived"),
    ("GET", "/api/v1/styles/{style_id}"),
    ("PUT", "/api/v1/styles/{style_id}"),
    ("DELETE", "/api/v1/styles/{style_id}"),
    ("POST", "/api/v1/styles/{style_id}/restore"),
    ("GET", "/api/v1/panels"),
    ("POST", "/api/v1/panels"),
    ("GET", "/api/v1/panels/{panel_id}"),
    ("PUT", "/api/v1/panels/{panel_id}"),
    ("PATCH", "/api/v1/panels/{panel_id}/model"),
    ("DELETE", "/api/v1/panels/{panel_id}"),
    ("POST", "/api/v1/panels/{panel_id}/duplicate"),
    ("GET", "/api/v1/panels/{panel_id}/preview"),
    ("GET", "/api/v1/panels/{panel_id}/generations"),
    ("POST", "/api/v1/panels/{panel_id}/generate"),
    ("GET", "/api/v1/generations/{generation_id}"),
    ("POST", "/api/v1/candidates/{candidate_id}/review"),
    ("GET", "/api/v1/candidates/{candidate_id}/content"),
    ("GET", "/api/v1/gallery"),
}


def test_router_split_preserves_wire_surface():
    """The api_v1 package exposes exactly the pre-split /api/v1 route surface."""
    schema = app.openapi()
    actual = {
        (method.upper(), path)
        for path, ops in schema["paths"].items()
        for method in ops
        if path.startswith("/api/v1")
    }
    assert actual == WIRE_SURFACE


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path):
    """A Settings instance with temp paths (assembly-time only, no env)."""
    return Settings(
        db_path=tmp_path / "test.db",
        store_root=tmp_path / "store",
    )


def test_registry_defaults_and_selectable_surface(settings):
    registry = ModelRegistry(settings)
    models = list(registry.models)
    assert "gemini-3.1-flash-image" in models
    assert registry.image_sizes_for("gemini-3.1-flash-image") == ("1K", "2K", "4K")
    assert list(registry.image_sizes) == ["1K", "2K", "4K"]
    assert registry.aspect_ratios == ("3:2", "16:9", "4:3", "1:1", "3:4", "9:16")


def test_registry_defaults_track_settings(settings):
    registry = ModelRegistry(settings)
    assert registry.default_model == settings.default_model
    assert registry.default_image_size == settings.default_image_size


def test_registry_is_source_of_aspect_ratios(settings):
    """Scenes imports ASPECT_RATIOS from app.models so there is a single source."""
    from app.models import ASPECT_RATIOS as MODEL_ASPECT_RATIOS

    assert ASPECT_RATIOS is MODEL_ASPECT_RATIOS
    assert ASPECT_RATIOS == ModelRegistry(settings).aspect_ratios


# ---------------------------------------------------------------------------
# CandidateService / content_sha / generation history
# ---------------------------------------------------------------------------


@pytest.fixture
def conn_storage(tmp_path):
    """Migrated temp DB connection + storage for service-level tests."""
    db_path = tmp_path / "services.db"
    run_migrations(db_path)
    storage = ImageStorage(tmp_path / "store")
    conn = connect(db_path)
    yield conn, storage
    conn.close()


def _insert_generation_and_candidate(conn, scene_id=1, sha256="a" * 64) -> int:
    conn.execute(
        """INSERT INTO scene (id, beat_text)
           VALUES (?, 'A scene.')""",
        (scene_id,),
    )
    cur = conn.execute(
        """
        INSERT INTO generation
            (scene_id, model, cost_usd_cents, reserved_cost_usd_cents,
             actual_cost_usd_cents, state, request_json, prompt_hash)
        VALUES (?, 'gemini-3.1-flash-image', 100, 100, 100, 'succeeded',
                '{"prompt": "x", "image_size": "1K", "aspect_ratio": "3:2"}',
                'h' * 64)
        """,
        (scene_id,),
    )
    generation_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO candidate (generation_id, idx, sha256, review_status)
        VALUES (?, 0, ?, 'pending')
        """,
        (generation_id, sha256),
    )
    conn.commit()
    return generation_id


def test_candidate_service_review_and_content_sha(conn_storage):
    conn, _ = conn_storage
    sha = "a" * 64
    generation_id = _insert_generation_and_candidate(conn, sha256=sha)
    candidate_id = conn.execute("SELECT id FROM candidate").fetchone()["id"]

    service = CandidateService(conn)
    row = service.review(candidate_id, "accepted")
    assert row["review_status"] == "accepted"
    assert service.content_sha(candidate_id) == sha

    with pytest.raises(GenerationNotFoundError):
        GenerationService(conn, None, None, None).get_with_candidates(9999)
    with pytest.raises(CandidateNotFoundError):
        service.content_sha(9999)


def test_ref_image_content_sha(conn_storage):
    conn, storage = conn_storage
    from app.services.characters import CharacterService

    character = CharacterService(conn).create(name="Elias", slug="elias")
    refs = RefSetService(conn, storage)
    draft = refs.create_draft(character.id)
    image = refs.add_image(draft.id, make_png_bytes(), "face_front")

    assert refs.content_sha(image.id) == image.sha256
    with pytest.raises(RefImageNotFoundError):
        refs.content_sha(9999)


def test_generation_history_service_reads(conn_storage):
    conn, _ = conn_storage
    generation_id = _insert_generation_and_candidate(conn)
    service = GenerationService(conn, None, None, None)

    row, candidates = service.get_with_candidates(generation_id)
    assert row["id"] == generation_id
    assert row["state"] == "succeeded"
    assert [c["review_status"] for c in candidates] == ["pending"]

    summaries = [dict(r) for r in service.list_for_scene(1)]
    assert [s["id"] for s in summaries] == [generation_id]
    assert service.list_for_scene(9999) == []

    with pytest.raises(GenerationNotFoundError):
        service.get_with_candidates(9999)
