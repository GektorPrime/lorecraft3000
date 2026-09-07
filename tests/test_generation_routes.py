"""Vertical-path tests for the /api/v1 JSON API.

Covers the end-to-end "library -> ref-set -> scene -> preview -> generate ->
review -> content" flow plus the guard behaviors that live at the preview/gate
boundary (budget cap, cast-size cap, visual-contract cap, missing on-disk
files). All requests go through the typed /api/v1 endpoints (issue #15); there
is no server-rendered UI anymore.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.db import connect
from app.deps import get_conn, get_provider, get_storage, settings
from app.main import app
from app.migrate import run_migrations
from app.providers.base import ProviderResult
from app.storage import ImageStorage
from tests.conftest import make_png_bytes


class FakeProvider:
    def __init__(self):
        self.requests = []
        self.edits = []
        self.error = None

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((30, 60, 90)), "route-interaction", {"fake": True}
        )

    def edit(self, request):
        self.edits.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((60, 90, 30)), "route-edit", {"fake": True, "edited": True}
        )


@dataclass
class RouteApp:
    client: TestClient
    db_path: object
    storage: ImageStorage
    provider: FakeProvider

    def conn(self):
        return connect(self.db_path)


@pytest.fixture
def route_app(tmp_path, monkeypatch):
    db_path = tmp_path / "vertical.db"
    storage = ImageStorage(tmp_path / "store")
    provider = FakeProvider()
    run_migrations(db_path)
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(db_path=db_path, store_root=storage.root),
    )

    def override_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = override_conn
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_provider] = lambda: provider
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield RouteApp(client, db_path, storage, provider)
    finally:
        app.dependency_overrides.clear()


def _seed_character_with_canon(route_app, name, slug, color=(100, 20, 20)):
    """Create a character with a promoted canonical ref-set via the API."""
    created = route_app.client.post(
        "/api/v1/characters",
        json={"name": name, "slug": slug, "visual_contract": f"Distinctive {name} face."},
    )
    assert created.status_code == 201, created.text
    character_id = created.json()["id"]
    draft = route_app.client.post(f"/api/v1/characters/{character_id}/ref-sets")
    assert draft.status_code == 201
    ref_set_id = draft.json()["id"]
    upload = route_app.client.post(
        f"/api/v1/ref-sets/{ref_set_id}/images",
        data={"role": "face_front"},
        files={"image": ("ref.png", make_png_bytes(color), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    promoted = route_app.client.post(f"/api/v1/ref-sets/{ref_set_id}/promote")
    assert promoted.status_code == 200
    return created.json(), promoted.json()


def _default_style_id(route_app) -> int:
    styles = route_app.client.get("/api/v1/styles").json()
    return next(s["id"] for s in styles if s["name"] == "Victorian Oil Painting")


def _create_scene(route_app, characters, model="gemini-3.1-flash-image"):
    resp = route_app.client.post(
        "/api/v1/scenes",
        json={
            "beat_text": "The cast studies a map beside the fire.",
            "camera": "eye level",
            "framing": "medium group",
            "mood": "tense",
            "aspect_ratio": "3:2",
            "cast": [
                {"character_id": cid, "role": f"position {i}", "prominence": len(characters) - i + 1}
                for i, cid in enumerate(characters, 1)
            ],
            "style_id": _default_style_id(route_app),
            "model": model,
            "image_size": "1K",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_generate_review_and_content_vertical_path(route_app):
    elias, ref_set = _seed_character_with_canon(route_app, "ELIAS", "elias", (100, 20, 20))
    scene = _create_scene(route_app, [elias["id"]])

    preview = route_app.client.get(f"/api/v1/scenes/{scene['id']}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["can_generate"] is True
    expected_prompt_hash = body["prompt_hash"]

    generated = route_app.client.post(
        f"/api/v1/scenes/{scene['id']}/generate",
        json={"expected_prompt_hash": expected_prompt_hash},
    )
    assert generated.status_code == 201, generated.text
    generation = generated.json()
    assert generation["state"] == "succeeded"
    assert generation["interaction_id"] == "route-interaction"
    assert len(route_app.provider.requests) == 1

    candidate = generation["candidates"][0]
    content = route_app.client.get(candidate["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")

    reviewed = route_app.client.post(
        f"/api/v1/candidates/{candidate['id']}/review", json={"verdict": "accepted"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "accepted"

    fetched = route_app.client.get(f"/api/v1/generations/{generation['id']}")
    assert fetched.json()["candidates"][0]["review_status"] == "accepted"
    # Reviewing a candidate must never touch the promoted reference set.
    conn = route_app.conn()
    try:
        canonical_id = conn.execute(
            "SELECT id FROM ref_set WHERE status = 'canonical'"
        ).fetchone()["id"]
    finally:
        conn.close()
    assert canonical_id == ref_set["id"]


def test_preview_blocks_when_daily_cap_would_be_exceeded(route_app):
    elias, _ = _seed_character_with_canon(route_app, "ELIAS", "elias")
    scene = _create_scene(route_app, [elias["id"]])
    conn = route_app.conn()
    try:
        spent = settings.daily_spend_cap_cents - 1
        conn.execute(
            """
            INSERT INTO generation
                (scene_id, model, cost_usd_cents, reserved_cost_usd_cents,
                 actual_cost_usd_cents, state)
            VALUES (?, 'gemini-3.1-flash-image', ?, ?, ?, 'succeeded')
            """,
            (scene["id"], spent, spent, spent),
        )
        conn.commit()
    finally:
        conn.close()

    preview = route_app.client.get(f"/api/v1/scenes/{scene['id']}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["can_generate"] is False
    assert "daily budget would be exceeded" in body["blocked_reason"]
    # No spend, no attempt recorded.
    assert route_app.provider.requests == []


def test_preview_blocks_five_character_cast(route_app):
    characters = [
        _seed_character_with_canon(route_app, f"CHAR{i}", f"char-{i}", (20 * i, 10, 10))[0]
        for i in range(1, 6)
    ]
    scene = _create_scene(route_app, [c["id"] for c in characters])
    preview = route_app.client.get(f"/api/v1/scenes/{scene['id']}/preview")
    body = preview.json()
    assert body["can_generate"] is False
    assert "split the scene" in body["blocked_reason"]


def test_preview_blocks_over_limit_visual_contract(route_app):
    elias, _ = _seed_character_with_canon(route_app, "ELIAS", "elias")
    conn = route_app.conn()
    try:
        conn.execute(
            "UPDATE character SET visual_contract = ? WHERE id = ?",
            ("word " * 61, elias["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    scene = _create_scene(route_app, [elias["id"]])
    preview = route_app.client.get(f"/api/v1/scenes/{scene['id']}/preview")
    body = preview.json()
    assert body["can_generate"] is False
    assert "60-word cap" in body["blocked_reason"]


def test_missing_candidate_file_returns_404(route_app):
    elias, _ = _seed_character_with_canon(route_app, "ELIAS", "elias")
    scene = _create_scene(route_app, [elias["id"]])
    generation = _generate(route_app, scene)
    candidate = generation["candidates"][0]
    conn = route_app.conn()
    try:
        sha256 = conn.execute("SELECT sha256 FROM candidate WHERE id = ?", (candidate["id"],)).fetchone()[
            "sha256"
        ]
    finally:
        conn.close()
    data, metadata = route_app.storage.read(sha256)
    route_app.storage.path_for(sha256, metadata["extension"]).unlink()

    resp = route_app.client.get(candidate["content_url"])
    assert resp.status_code == 404


def _generate(route_app, scene):
    preview = route_app.client.get(f"/api/v1/scenes/{scene['id']}/preview").json()
    generated = route_app.client.post(
        f"/api/v1/scenes/{scene['id']}/generate",
        json={"expected_prompt_hash": preview["prompt_hash"]},
    )
    assert generated.status_code == 201, generated.text
    return generated.json()


def test_edit_candidate_creates_child_generation(route_app):
    elias, _ = _seed_character_with_canon(route_app, "ELIAS", "elias")
    scene = _create_scene(route_app, [elias["id"]])
    generation = _generate(route_app, scene)
    candidate = generation["candidates"][0]

    edited = route_app.client.post(
        f"/api/v1/candidates/{candidate['id']}/edit",
        json={"instruction": "make it night time with neon"},
    )
    assert edited.status_code == 201, edited.text
    body = edited.json()
    assert body["state"] == "succeeded"
    assert body["interaction_id"] == "route-edit"
    assert len(route_app.provider.edits) == 1
    assert route_app.provider.edits[0].instruction == "make it night time with neon"

    # The edit is a child of the source generation.
    conn = route_app.conn()
    try:
        parent = conn.execute(
            "SELECT parent_generation_id FROM generation WHERE id = ?",
            (body["id"],),
        ).fetchone()["parent_generation_id"]
    finally:
        conn.close()
    assert parent == generation["id"]

    # The new candidate renders as an image.
    new_candidate = body["candidates"][0]
    content = route_app.client.get(new_candidate["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")


def test_edit_requires_non_empty_instruction(route_app):
    elias, _ = _seed_character_with_canon(route_app, "ELIAS", "elias")
    scene = _create_scene(route_app, [elias["id"]])
    generation = _generate(route_app, scene)
    candidate = generation["candidates"][0]
    resp = route_app.client.post(
        f"/api/v1/candidates/{candidate['id']}/edit",
        json={"instruction": ""},
    )
    assert resp.status_code == 422


def test_edit_missing_candidate_returns_404(route_app):
    resp = route_app.client.post(
        "/api/v1/candidates/9999/edit",
        json={"instruction": "make it night"},
    )
    assert resp.status_code == 404
