"""Tests for the typed /api/v1 JSON API (issue #15).

Covers: options/summary, characters, styles, ref-sets/images/promotion,
ref-image content by ID, panels CRUD/preview/generation, generations,
candidate review/content, budget — plus the two behavioral contracts most at
risk of regression: panel edit immutability after any generation attempt (and
duplicate as the escape hatch), and that no sha256/hash ever appears in a
JSON response body.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.deps import get_conn, get_provider, get_storage
from app.main import app
from app.migrate import run_migrations
from app.providers.base import ProviderResult
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
        return ProviderResult(make_png_bytes((30, 60, 90)), "api-interaction", {"fake": True})


@dataclass
class ApiApp:
    client: TestClient
    db_path: object
    storage: ImageStorage
    provider: FakeProvider

    def conn(self):
        return connect(self.db_path)


@pytest.fixture
def api(tmp_path):
    db_path = tmp_path / "api.db"
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
    with TestClient(app) as client:
        yield ApiApp(client, db_path, storage, provider)
    app.dependency_overrides.clear()


def _default_style_id(api) -> int:
    styles = api.client.get("/api/v1/styles").json()
    return next(s["id"] for s in styles if s["name"] == "Victorian Oil Painting")


def _create_character(api, name="Elias", slug="elias", visual_contract="Pale eyes."):
    resp = api.client.post(
        "/api/v1/characters",
        json={"name": name, "slug": slug, "visual_contract": visual_contract},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _promote_canonical(api, character_id, color=(100, 20, 20), role="face_front"):
    draft = api.client.post(f"/api/v1/characters/{character_id}/ref-sets")
    assert draft.status_code == 201
    ref_set_id = draft.json()["id"]
    upload = api.client.post(
        f"/api/v1/ref-sets/{ref_set_id}/images",
        data={"role": role},
        files={"image": ("ref.png", make_png_bytes(color), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    promoted = api.client.post(f"/api/v1/ref-sets/{ref_set_id}/promote")
    assert promoted.status_code == 200
    return promoted.json()


def _create_panel(api, character_ids, model="gemini-3.1-flash-image"):
    resp = api.client.post(
        "/api/v1/panels",
        json={
            "beat_text": "The cast studies a map beside the fire.",
            "camera": "eye level",
            "framing": "medium group",
            "mood": "tense",
            "aspect_ratio": "3:2",
            "cast": [
                {"character_id": cid, "role": f"position {i}", "prominence": i}
                for i, cid in enumerate(character_ids, 1)
            ],
            "style_id": _default_style_id(api),
            "model": model,
            "image_size": "1K",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# options / budget
# ---------------------------------------------------------------------------


def test_options_summary_shape(api):
    resp = api.client.get("/api/v1/options/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "gemini-3.1-flash-image" in body["models"]
    assert "1K" in body["image_sizes"]
    assert "3:2" in body["aspect_ratios"]
    assert "face_front" in body["ref_image_roles"]
    assert body["daily_spend_cap_cents"] > 0
    assert body["spent_today_cents"] == 0
    assert "cannot be edited" in body["ref_image_weight_explanation"].lower()
    assert "canonical" in body["ref_set_immutability_explanation"].lower()
    assert "duplicate" in body["panel_immutability_explanation"].lower()


def test_budget_reflects_spend(api):
    resp = api.client.get("/api/v1/budget")
    assert resp.status_code == 200
    body = resp.json()
    assert body["spent_today_cents"] == 0
    assert body["remaining_today_cents"] == body["daily_spend_cap_cents"]


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------


def test_character_crud_round_trip(api):
    created = _create_character(api)
    assert created["slug"] == "elias"
    assert created["has_canonical_ref_set"] is False
    assert created["avatar_url"] is None
    assert created["avatar_initials"] == "EL"

    listed = api.client.get("/api/v1/characters").json()
    assert len(listed) == 1

    fetched = api.client.get(f"/api/v1/characters/{created['id']}").json()
    assert fetched["name"] == "Elias"

    updated = api.client.put(
        f"/api/v1/characters/{created['id']}",
        json={"name": "Elias Thorne", "slug": "elias", "visual_contract": "Pale eyes."},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Elias Thorne"


def test_character_slug_collision_is_409(api):
    _create_character(api, name="Elias", slug="elias")
    resp = api.client.post("/api/v1/characters", json={"name": "Elias 2", "slug": "elias"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["type"] == "SlugCollisionError"


def test_character_visual_contract_over_cap_is_422(api):
    resp = api.client.post(
        "/api/v1/characters",
        json={"name": "Elias", "slug": "elias", "visual_contract": "word " * 61},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["type"] == "VisualContractTooLongError"


def test_character_not_found_is_404(api):
    resp = api.client.get("/api/v1/characters/9999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["type"] == "CharacterNotFoundError"


def test_character_avatar_url_after_promotion_has_no_hash(api):
    created = _create_character(api)
    _promote_canonical(api, created["id"])
    fetched = api.client.get(f"/api/v1/characters/{created['id']}").json()
    assert fetched["has_canonical_ref_set"] is True
    assert fetched["avatar_url"] is not None
    assert fetched["avatar_url"].startswith("/api/v1/ref-images/")
    assert fetched["avatar_url"].endswith("/content")
    # No sha256 anywhere near a URL — content is served by opaque ID.
    img = api.client.get(fetched["avatar_url"])
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/png")


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------


def test_style_crud_round_trip(api):
    created = api.client.post(
        "/api/v1/styles", json={"name": "Ink Wash", "style_contract": "Loose ink wash."}
    )
    assert created.status_code == 201
    style_id = created.json()["id"]

    fetched = api.client.get(f"/api/v1/styles/{style_id}").json()
    assert fetched["name"] == "Ink Wash"

    updated = api.client.put(
        f"/api/v1/styles/{style_id}",
        json={"name": "Ink Wash 2", "style_contract": "Updated."},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ink Wash 2"

    dup = api.client.post("/api/v1/styles", json={"name": "Ink Wash 2"})
    assert dup.status_code == 409


def test_seeded_default_style_is_listed(api):
    styles = api.client.get("/api/v1/styles").json()
    assert any(s["name"] == "Victorian Oil Painting" for s in styles)


# ---------------------------------------------------------------------------
# ref-sets / ref-images
# ---------------------------------------------------------------------------


def test_ref_set_create_upload_promote_and_no_hash_in_json(api):
    character = _create_character(api)
    draft_resp = api.client.post(f"/api/v1/characters/{character['id']}/ref-sets")
    assert draft_resp.status_code == 201
    draft = draft_resp.json()
    assert draft["status"] == "draft"
    assert draft["version"] == 1

    upload = api.client.post(
        f"/api/v1/ref-sets/{draft['id']}/images",
        data={"role": "face_front"},
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
    )
    assert upload.status_code == 201
    image = upload.json()
    assert image["role"] == "face_front"
    assert image["weight"] == 1.0
    assert "sha256" not in image
    assert "hash" not in {k.lower() for k in image}

    # re-role (draft only)
    re_roled = api.client.patch(
        f"/api/v1/ref-sets/{draft['id']}/images/{image['id']}", json={"role": "outfit"}
    )
    assert re_roled.status_code == 200
    assert re_roled.json()["role"] == "outfit"

    detail = api.client.get(f"/api/v1/ref-sets/{draft['id']}").json()
    assert len(detail["images"]) == 1
    assert "sha256" not in detail["images"][0]

    promoted = api.client.post(f"/api/v1/ref-sets/{draft['id']}/promote")
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "canonical"

    # canonical set is immutable: re-role now rejected
    blocked = api.client.patch(
        f"/api/v1/ref-sets/{draft['id']}/images/{image['id']}", json={"role": "face_3q"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["type"] == "RefSetNotDraftError"


def test_ref_set_copy_creates_new_draft_version(api):
    character = _create_character(api)
    promoted = _promote_canonical(api, character["id"])
    copied = api.client.post(f"/api/v1/ref-sets/{promoted['id']}/copy")
    assert copied.status_code == 201
    body = copied.json()
    assert body["version"] == 2
    assert body["status"] == "draft"
    assert len(body["images"]) == 1


def test_ref_set_remove_image(api):
    character = _create_character(api)
    draft = api.client.post(f"/api/v1/characters/{character['id']}/ref-sets").json()
    image = api.client.post(
        f"/api/v1/ref-sets/{draft['id']}/images",
        data={"role": "face_front"},
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
    ).json()
    removed = api.client.delete(f"/api/v1/ref-sets/{draft['id']}/images/{image['id']}")
    assert removed.status_code == 204
    detail = api.client.get(f"/api/v1/ref-sets/{draft['id']}").json()
    assert detail["images"] == []


def test_invalid_role_upload_is_422(api):
    character = _create_character(api)
    draft = api.client.post(f"/api/v1/characters/{character['id']}/ref-sets").json()
    resp = api.client.post(
        f"/api/v1/ref-sets/{draft['id']}/images",
        data={"role": "bogus"},
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["type"] == "InvalidRoleError"


# ---------------------------------------------------------------------------
# panels: CRUD, immutability, duplication, preview, generation
# ---------------------------------------------------------------------------


def test_panel_create_and_list(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    assert panel["is_editable"] is True
    assert panel["generation_count"] == 0
    assert panel["cast"][0]["name"] == "Elias"
    assert panel["cast"][0]["avatar_url"] is not None

    listed = api.client.get("/api/v1/panels").json()
    assert len(listed) == 1


def test_panel_create_rejects_zero_or_negative_prominence(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    base_payload = {
        "beat_text": "A scene.",
        "camera": "eye level, looking straight on",
        "framing": "medium shot",
        "mood": "",
        "aspect_ratio": "3:2",
        "style_id": _default_style_id(api),
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
    }
    for bad_prominence in (0, -1, -100):
        resp = api.client.post(
            "/api/v1/panels",
            json={
                **base_payload,
                "cast": [
                    {
                        "character_id": character["id"],
                        "role": "lead",
                        "prominence": bad_prominence,
                    }
                ],
            },
        )
        # Rejected at the Pydantic boundary (schemas.CastMemberIn ge=1).
        assert resp.status_code == 422, resp.text
    # No panel was created by any of the rejected attempts.
    assert api.client.get("/api/v1/panels").json() == []


def test_scene_service_rejects_zero_or_negative_prominence_even_bypassing_pydantic(api):
    """The backend is authoritative independent of the Pydantic layer: call
    SceneService directly (as any non-API caller would) with a cast dict
    carrying prominence <= 0 and confirm it is still rejected."""
    from app.config import Settings
    from app.services.scenes import SceneError, SceneService

    character = _create_character(api)
    _promote_canonical(api, character["id"])
    conn = api.conn()
    try:
        style_id = _default_style_id(api)
        service = SceneService(conn, Settings())
        for bad_prominence in (0, -5):
            with pytest.raises(SceneError, match="prominence must be a positive integer"):
                service.create(
                    beat_text="A scene.",
                    camera="eye level, looking straight on",
                    framing="medium shot",
                    mood="",
                    aspect_ratio="3:2",
                    cast=[
                        {
                            "character_id": character["id"],
                            "role": "lead",
                            "prominence": bad_prominence,
                        }
                    ],
                    style_id=style_id,
                    model="gemini-3.1-flash-image",
                    image_size="1K",
                )
        # Non-integer prominence is rejected the same way.
        with pytest.raises(SceneError, match="prominence must be a positive integer"):
            service.create(
                beat_text="A scene.",
                camera="eye level, looking straight on",
                framing="medium shot",
                mood="",
                aspect_ratio="3:2",
                cast=[
                    {"character_id": character["id"], "role": "lead", "prominence": "primary"}
                ],
                style_id=style_id,
                model="gemini-3.1-flash-image",
                image_size="1K",
            )
        # A valid create still succeeds (the guard isn't over-broad).
        scene = service.create(
            beat_text="A scene.",
            camera="eye level, looking straight on",
            framing="medium shot",
            mood="",
            aspect_ratio="3:2",
            cast=[{"character_id": character["id"], "role": "lead", "prominence": 1}],
            style_id=style_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
        )
        assert scene.cast[0]["prominence"] == 1
    finally:
        conn.close()


def test_panel_update_rejects_zero_or_negative_prominence(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    resp = api.client.put(
        f"/api/v1/panels/{panel['id']}",
        json={
            "beat_text": panel["beat_text"],
            "camera": panel["camera"],
            "framing": panel["framing"],
            "mood": panel["mood"],
            "aspect_ratio": panel["aspect_ratio"],
            "cast": [{"character_id": character["id"], "role": "lead", "prominence": -1}],
            "style_id": panel["style_id"],
            "model": panel["model"],
            "image_size": panel["image_size"],
        },
    )
    assert resp.status_code == 422
    # The panel is unchanged.
    unchanged = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert unchanged["cast"][0]["prominence"] == panel["cast"][0]["prominence"]


def test_panel_editable_until_generation_succeeds_then_backend_rejects_update(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])

    # Editable with zero generations: update succeeds.
    update_payload = {
        "beat_text": "Updated beat.",
        "camera": "low angle",
        "framing": "close up",
        "mood": "calm",
        "aspect_ratio": "3:2",
        "cast": [{"character_id": character["id"], "role": "lead", "prominence": 1}],
        "style_id": panel["style_id"],
        "model": panel["model"],
        "image_size": panel["image_size"],
    }
    updated = api.client.put(f"/api/v1/panels/{panel['id']}", json=update_payload)
    assert updated.status_code == 200
    assert updated.json()["beat_text"] == "Updated beat."

    # Generate once.
    generated = api.client.post(f"/api/v1/panels/{panel['id']}/generate")
    assert generated.status_code == 201, generated.text
    assert generated.json()["state"] == "succeeded"

    # Now the panel must report non-editable and reject a further update,
    # even though the request itself is well-formed (backend enforcement,
    # not just a disabled UI control).
    refreshed = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert refreshed["is_editable"] is False
    assert refreshed["generation_count"] == 1

    rejected = api.client.put(f"/api/v1/panels/{panel['id']}", json=update_payload)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["type"] == "SceneImmutableError"

    # The original beat_text from before the rejected update is preserved.
    still = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert still["beat_text"] == "Updated beat."


def test_failed_generation_remains_editable_and_is_preserved_in_history(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    api.provider.error = RuntimeError("provider unavailable")

    failed = api.client.post(f"/api/v1/panels/{panel['id']}/generate")
    assert failed.status_code == 422

    refreshed = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert refreshed["is_editable"] is True
    assert refreshed["generation_count"] == 1

    history = api.client.get(
        f"/api/v1/panels/{panel['id']}/generations"
    )
    assert history.status_code == 200
    attempts = history.json()
    assert len(attempts) == 1
    assert attempts[0]["state"] == "failed"
    assert "provider unavailable" in attempts[0]["error_text"]

    update_payload = {
        "beat_text": "Revised after provider failure.",
        "camera": panel["camera"],
        "framing": panel["framing"],
        "mood": panel["mood"],
        "aspect_ratio": panel["aspect_ratio"],
        "cast": [
            {"character_id": character["id"], "role": "lead", "prominence": 1}
        ],
        "style_id": panel["style_id"],
        "model": panel["model"],
        "image_size": panel["image_size"],
    }
    updated = api.client.put(
        f"/api/v1/panels/{panel['id']}", json=update_payload
    )
    assert updated.status_code == 200
    assert updated.json()["beat_text"] == "Revised after provider failure."


def test_panel_duplicate_prefills_all_fields_with_new_id_and_preserves_original(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    api.client.post(f"/api/v1/panels/{panel['id']}/generate")

    duplicated = api.client.post(f"/api/v1/panels/{panel['id']}/duplicate")
    assert duplicated.status_code == 201
    copy = duplicated.json()
    assert copy["id"] != panel["id"]
    assert copy["beat_text"] == panel["beat_text"]
    assert copy["camera"] == panel["camera"]
    assert copy["framing"] == panel["framing"]
    assert copy["cast"][0]["character_id"] == panel["cast"][0]["character_id"]
    assert copy["is_editable"] is True
    assert copy["generation_count"] == 0

    # Original panel and its generation history are untouched.
    original = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert original["generation_count"] == 1
    assert original["is_editable"] is False


def test_panel_preview_is_no_spend_and_reports_allocation(api):
    elias = _create_character(api, "Elias", "elias")
    _promote_canonical(api, elias["id"], (100, 20, 20))
    mara = _create_character(api, "Mara", "mara")
    _promote_canonical(api, mara["id"], (20, 100, 20))
    panel = _create_panel(api, [elias["id"], mara["id"]])

    preview = api.client.get(f"/api/v1/panels/{panel['id']}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["can_generate"] is True
    assert body["estimated_cost_cents"] > 0
    names = {a["character_name"] for a in body["attachments"]}
    assert names == {"Elias", "Mara"}
    assert "sha256" not in str(body)

    # Preview never spends: no generation rows created.
    budget = api.client.get("/api/v1/budget").json()
    assert budget["spent_today_cents"] == 0


def test_panel_preview_blocked_without_canonical_ref_set(api):
    character = _create_character(api)  # no canonical ref-set
    resp = api.client.post(
        "/api/v1/panels",
        json={
            "beat_text": "A scene.",
            "camera": "eye level",
            "framing": "medium",
            "mood": "",
            "aspect_ratio": "3:2",
            "cast": [{"character_id": character["id"], "role": "", "prominence": 1}],
            "style_id": _default_style_id(api),
            "model": "gemini-3.1-flash-image",
            "image_size": "1K",
        },
    )
    assert resp.status_code == 201
    panel_id = resp.json()["id"]
    preview = api.client.get(f"/api/v1/panels/{panel_id}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["can_generate"] is False
    assert "no canonical reference set" in body["blocked_reason"]


def test_panel_generate_and_review_and_content(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])

    generated = api.client.post(f"/api/v1/panels/{panel['id']}/generate")
    assert generated.status_code == 201
    generation = generated.json()
    assert generation["state"] == "succeeded"
    assert generation["interaction_id"] == "api-interaction"
    assert len(generation["candidates"]) == 1
    assert "sha256" not in str(generation)

    candidate = generation["candidates"][0]
    assert candidate["review_status"] == "pending"

    content = api.client.get(candidate["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")

    reviewed = api.client.post(
        f"/api/v1/candidates/{candidate['id']}/review", json={"verdict": "accepted"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "accepted"

    fetched_generation = api.client.get(f"/api/v1/generations/{generation['id']}")
    assert fetched_generation.status_code == 200
    assert fetched_generation.json()["candidates"][0]["review_status"] == "accepted"


def test_invalid_review_verdict_is_422(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    generation = api.client.post(f"/api/v1/panels/{panel['id']}/generate").json()
    candidate_id = generation["candidates"][0]["id"]
    resp = api.client.post(
        f"/api/v1/candidates/{candidate_id}/review", json={"verdict": "maybe"}
    )
    assert resp.status_code == 422


def test_generation_not_found_is_404(api):
    resp = api.client.get("/api/v1/generations/9999")
    assert resp.status_code == 404


def test_panel_not_found_is_404(api):
    resp = api.client.get("/api/v1/panels/9999")
    assert resp.status_code == 404
