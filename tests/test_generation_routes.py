from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.deps import get_conn, get_provider, get_storage, settings
from app.main import app
from app.migrate import run_migrations
from app.providers.base import ProviderResult
from app.services.characters import CharacterService
from app.services.ref_sets import RefSetService
from app.storage import ImageStorage
from tests.conftest import make_png_bytes


class FakeProvider:
    def __init__(self):
        self.requests = []
        self.error = None

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((30, 60, 90)), "route-interaction", {"fake": True}
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
def route_app(tmp_path):
    db_path = tmp_path / "vertical.db"
    storage = ImageStorage(tmp_path / "store")
    provider = FakeProvider()
    run_migrations(db_path)

    def override_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = override_conn
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_provider] = lambda: provider
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield RouteApp(client, db_path, storage, provider)
    app.dependency_overrides.clear()


def _character_with_canon(route_app, name, slug, color):
    conn = route_app.conn()
    try:
        character = CharacterService(conn).create(
            name=name,
            slug=slug,
            lore_md=f"SECRET {name} LORE",
            visual_contract=f"Distinctive {name} face.",
        )
        refs = RefSetService(conn, route_app.storage)
        ref_set = refs.create_draft(character.id)
        refs.add_image(ref_set.id, make_png_bytes(color), "face_front")
        refs.promote(ref_set.id)
        return character, ref_set
    finally:
        conn.close()


def _create_scene(route_app, characters, model="gemini-3.1-flash-image"):
    conn = route_app.conn()
    try:
        style_id = conn.execute(
            "SELECT id FROM style WHERE name = 'Victorian Oil Painting'"
        ).fetchone()["id"]
    finally:
        conn.close()
    order = ",".join(str(character.id) for character in characters)
    data = {
        "beat_text": "The cast studies a map beside the fire.",
        "camera": "eye level",
        "framing": "medium group",
        "mood": "tense",
        "aspect_ratio": "3:2",
        "cast_order": order,
        "style_id": str(style_id),
        "model": model,
        "image_size": "1K",
    }
    for index, character in enumerate(characters, 1):
        data[f"role_{character.id}"] = f"position {index}"
        data[f"prominence_{character.id}"] = str(len(characters) - index + 1)
    response = route_app.client.post("/scenes", data=data, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def _preview_prompt_hash(route_app, preview_url: str) -> str:
    page = route_app.client.get(preview_url)
    match = re.search(r'name="expected_prompt_hash" value="([a-f0-9]+)"', page.text)
    assert match is not None
    return match.group(1)


def test_new_panel_form_and_list_are_available(route_app):
    assert route_app.client.get("/scenes").status_code == 200
    form = route_app.client.get("/scenes/new")
    assert form.status_code == 200
    assert 'name="cast_order"' in form.text
    assert "Save and preview" in form.text


def test_preview_is_no_spend_and_shows_exact_multi_character_allocation(route_app):
    elias, _ = _character_with_canon(route_app, "ELIAS", "elias", (100, 20, 20))
    mara, _ = _character_with_canon(route_app, "MARA", "mara", (20, 100, 20))
    preview_url = _create_scene(route_app, [elias, mara])
    page = route_app.client.get(preview_url)
    assert page.status_code == 200
    assert "Reference-slot allocation" in page.text
    assert "ELIAS" in page.text and "MARA" in page.text
    assert "Image 1 is a canonical reference for ELIAS" in page.text
    assert "Generate one candidate · $0.07" in page.text
    assert 'name="expected_prompt_hash"' in page.text
    assert "SECRET" not in page.text
    conn = route_app.conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM generation").fetchone()[0] == 0
    finally:
        conn.close()
    assert route_app.provider.requests == []


def test_generate_review_and_media_vertical_path(route_app):
    elias, ref_set = _character_with_canon(
        route_app, "ELIAS", "elias", (100, 20, 20)
    )
    preview_url = _create_scene(route_app, [elias])
    scene_id = preview_url.split("/")[2]
    generated = route_app.client.post(
        f"/scenes/{scene_id}/generate",
        data={"expected_prompt_hash": _preview_prompt_hash(route_app, preview_url)},
        follow_redirects=False,
    )
    assert generated.status_code == 303
    assert generated.headers["location"].startswith("/generations/")
    detail = route_app.client.get(generated.headers["location"])
    assert detail.status_code == 200
    assert "route-interaction" in detail.text
    assert "Review status: <strong>pending</strong>" in detail.text
    assert len(route_app.provider.requests) == 1

    conn = route_app.conn()
    try:
        candidate = conn.execute("SELECT * FROM candidate").fetchone()
        canonical_before = conn.execute(
            "SELECT id FROM ref_set WHERE status = 'canonical'"
        ).fetchone()["id"]
    finally:
        conn.close()
    media = route_app.client.get(f"/media/{candidate['sha256']}")
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("image/png")

    reviewed = route_app.client.post(
        f"/candidates/{candidate['id']}/review",
        data={"verdict": "accepted"},
        follow_redirects=False,
    )
    assert reviewed.status_code == 303
    conn = route_app.conn()
    try:
        assert conn.execute(
            "SELECT review_status FROM candidate WHERE id = ?", (candidate["id"],)
        ).fetchone()["review_status"] == "accepted"
        assert conn.execute(
            "SELECT id FROM ref_set WHERE status = 'canonical'"
        ).fetchone()["id"] == canonical_before == ref_set.id
    finally:
        conn.close()


def test_preview_blocks_missing_canonical_without_generate_button(route_app):
    conn = route_app.conn()
    try:
        character = CharacterService(conn).create(name="ELIAS", slug="elias")
    finally:
        conn.close()
    preview_url = _create_scene(route_app, [character])
    page = route_app.client.get(preview_url)
    assert "Generation blocked" in page.text
    assert "no canonical reference set" in page.text
    assert "Generate one candidate" not in page.text
    conn = route_app.conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM generation").fetchone()[0] == 0
    finally:
        conn.close()


def test_preview_blocks_when_daily_cap_would_be_exceeded(route_app):
    character, _ = _character_with_canon(
        route_app, "ELIAS", "elias", (100, 20, 20)
    )
    preview_url = _create_scene(route_app, [character])
    scene_id = int(preview_url.split("/")[2])
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
                (scene_id, spent, spent, spent),
            )
        conn.commit()
    finally:
        conn.close()
    page = route_app.client.get(preview_url)
    assert "daily budget would be exceeded" in page.text
    assert "Generate one candidate" not in page.text


def test_provider_failure_is_recorded_and_visible(route_app):
    character, _ = _character_with_canon(
        route_app, "ELIAS", "elias", (100, 20, 20)
    )
    preview_url = _create_scene(route_app, [character])
    scene_id = preview_url.split("/")[2]
    route_app.provider.error = TimeoutError("provider timeout")
    response = route_app.client.post(
        f"/scenes/{scene_id}/generate",
        data={"expected_prompt_hash": _preview_prompt_hash(route_app, preview_url)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "notice=" in response.headers["location"]
    retry_page = route_app.client.get(response.headers["location"])
    assert "Last attempt failed" in retry_page.text
    assert "Generate one candidate" in retry_page.text
    conn = route_app.conn()
    try:
        failed = conn.execute("SELECT state, error_text FROM generation").fetchone()
        assert failed["state"] == "failed"
        assert "provider timeout" in failed["error_text"]
    finally:
        conn.close()


def test_missing_candidate_file_returns_404(route_app):
    assert route_app.client.get("/media/" + "a" * 64).status_code == 404


def test_scene_create_rejects_missing_required_fields(route_app):
    response = route_app.client.post(
        "/scenes",
        data={"beat_text": "", "camera": "", "framing": "", "cast_order": ""},
    )
    assert response.status_code == 422
    assert "required" in response.text or "select at least one" in response.text


def test_flash_preview_blocks_five_character_cast(route_app):
    characters = [
        _character_with_canon(
            route_app, f"CHAR{i}", f"char-{i}", (20 * i, 10, 10)
        )[0]
        for i in range(1, 6)
    ]
    preview_url = _create_scene(route_app, characters)
    page = route_app.client.get(preview_url)
    assert "switch to Pro or split the panel" in page.text
    assert "Generate one candidate" not in page.text


def test_preview_blocks_legacy_over_limit_visual_contract(route_app):
    character, _ = _character_with_canon(
        route_app, "ELIAS", "elias", (100, 20, 20)
    )
    preview_url = _create_scene(route_app, [character])
    conn = route_app.conn()
    try:
        conn.execute(
            "UPDATE character SET visual_contract = ? WHERE id = ?",
            ("word " * 61, character.id),
        )
        conn.commit()
    finally:
        conn.close()
    page = route_app.client.get(preview_url)
    assert "60-word cap" in page.text
    assert "Generate one candidate" not in page.text


def test_generation_detail_reports_missing_candidate_file(route_app):
    character, _ = _character_with_canon(
        route_app, "ELIAS", "elias", (100, 20, 20)
    )
    preview_url = _create_scene(route_app, [character])
    scene_id = preview_url.split("/")[2]
    generated = route_app.client.post(
        f"/scenes/{scene_id}/generate",
        data={"expected_prompt_hash": _preview_prompt_hash(route_app, preview_url)},
        follow_redirects=False,
    )
    detail_url = generated.headers["location"]
    conn = route_app.conn()
    try:
        sha256 = conn.execute("SELECT sha256 FROM candidate").fetchone()["sha256"]
    finally:
        conn.close()
    data, metadata = route_app.storage.read(sha256)
    route_app.storage.path_for(sha256, metadata["extension"]).unlink()
    detail = route_app.client.get(detail_url)
    assert detail.status_code == 200
    assert "candidate file is missing" in detail.text
