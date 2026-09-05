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
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main_module
from app.config import Settings
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
        self.billed_cost_cents = None
        self.edits = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((30, 60, 90)),
            "api-interaction",
            {"fake": True},
            self.billed_cost_cents,
        )

    def edit(self, request):
        self.edits.append(request)
        if self.error:
            raise self.error
        return ProviderResult(
            make_png_bytes((30, 60, 90)),
            "api-stage-interaction",
            {"fake": True, "edited": True},
            self.billed_cost_cents,
        )


@dataclass
class ApiApp:
    client: TestClient
    db_path: object
    storage: ImageStorage
    provider: FakeProvider

    def conn(self):
        return connect(self.db_path)


@pytest.fixture
def api(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
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
            yield ApiApp(client, db_path, storage, provider)
    finally:
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


def _generate_panel(api, panel_id, *, headers=None):
    preview = api.client.get(f"/api/v1/panels/{panel_id}/preview").json()
    return api.client.post(
        f"/api/v1/panels/{panel_id}/generate",
        json={"expected_prompt_hash": preview["prompt_hash"]},
        headers=headers,
    )


def _image_bytes(format: str, size=(12, 8)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(output, format=format)
    return output.getvalue()


def _upload_base_stage(api, *, image=None, description="Stone bridge", targets=None):
    return api.client.post(
        "/api/v1/base-stages/upload",
        data={
            "description": description,
            "targets": json.dumps(
                ["traveler beside the arch"] if targets is None else targets
            ),
        },
        files={"image": ("stage.png", image or _image_bytes("PNG"), "image/png")},
    )


# ---------------------------------------------------------------------------
# base stages
# ---------------------------------------------------------------------------


def test_base_stage_upload_list_get_content_archive_and_restore(api):
    uploaded = _upload_base_stage(
        api,
        image=_image_bytes("PNG", (160, 90)),
        description="  Four investigators hauling a machine uphill.  ",
        targets=["upper figure", "lower figure"],
    )
    assert uploaded.status_code == 201, uploaded.text
    stage = uploaded.json()

    assert stage["origin"] == "upload"
    assert stage["state"] == "ready"
    assert stage["description"] == "Four investigators hauling a machine uphill."
    assert stage["aspect_ratio"] == "16:9"
    assert stage["dimensions"] == {"width": 160, "height": 90}
    assert [target["description"] for target in stage["targets"]] == [
        "upper figure",
        "lower figure",
    ]
    assert stage["content_url"] == f"/api/v1/base-stages/{stage['id']}/content"
    assert "sha" not in json.dumps(stage).lower()

    listed = api.client.get("/api/v1/base-stages")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [stage["id"]]
    assert api.client.get(f"/api/v1/base-stages/{stage['id']}").json() == stage

    content = api.client.get(stage["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.content == _image_bytes("PNG", (160, 90))

    assert api.client.delete(f"/api/v1/base-stages/{stage['id']}").status_code == 204
    assert api.client.get("/api/v1/base-stages").json() == []
    archived = api.client.get("/api/v1/base-stages/archived").json()
    assert [item["id"] for item in archived] == [stage["id"]]
    assert api.client.get(stage["content_url"]).status_code == 200

    restored = api.client.post(f"/api/v1/base-stages/{stage['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert [item["id"] for item in api.client.get("/api/v1/base-stages").json()] == [
        stage["id"]
    ]


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ("not json", "valid JSON"),
        (json.dumps({"target": "left"}), "JSON array"),
        (json.dumps(["left", " LEFT "]), "case-insensitive"),
        (json.dumps([""]), "must not be blank"),
    ],
)
def test_base_stage_upload_rejects_invalid_targets(api, targets, message):
    response = api.client.post(
        "/api/v1/base-stages/upload",
        data={"description": "A clearing", "targets": targets},
        files={"image": ("stage.png", _image_bytes("PNG"), "image/png")},
    )
    assert response.status_code == 422
    assert message in response.json()["detail"]["message"]


def test_base_stage_upload_rejects_mime_size_and_decoded_format(api):
    wrong_mime = api.client.post(
        "/api/v1/base-stages/upload",
        data={"description": "A clearing", "targets": "[]"},
        files={"image": ("stage.png", _image_bytes("PNG"), "text/plain")},
    )
    assert wrong_mime.status_code == 422

    oversized = api.client.post(
        "/api/v1/base-stages/upload",
        data={"description": "A clearing", "targets": "[]"},
        files={"image": ("stage.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 422
    assert "10 MB" in oversized.json()["detail"]["message"]

    unsupported = api.client.post(
        "/api/v1/base-stages/upload",
        data={"description": "A clearing", "targets": "[]"},
        files={"image": ("stage.gif", _image_bytes("GIF"), "image/png")},
    )
    assert unsupported.status_code == 422
    assert "format GIF" in unsupported.json()["detail"]["message"]


def test_base_stage_missing_routes_return_404(api):
    assert api.client.get("/api/v1/base-stages/9999").status_code == 404
    assert api.client.get("/api/v1/base-stages/9999/content").status_code == 404
    assert api.client.delete("/api/v1/base-stages/9999").status_code == 404
    assert api.client.post("/api/v1/base-stages/9999/restore").status_code == 404
    assert api.client.get("/api/v1/base-stages/9999/preview").status_code == 404
    assert api.client.get("/api/v1/base-stages/9999/generations").status_code == 404
    assert (
        api.client.post(
            "/api/v1/base-stages/9999/generate", json={"expected_prompt_hash": "x"}
        ).status_code
        == 404
    )
    assert (
        api.client.post(
            "/api/v1/base-stages/9999/publish", json={"candidate_id": 1}
        ).status_code
        == 404
    )


def _create_generated_stage(api, **overrides):
    payload = {
        "description": "Four figures haul a machine up a muddy ravine.",
        "beat_text": "They strain against the rope as the machine slips.",
        "camera": "twenty metres away, slightly elevated",
        "framing": "wide environmental shot",
        "mood": "strenuous",
        "aspect_ratio": "16:9",
        "style_id": _default_style_id(api),
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
        "targets": ["figure above the slope", "figure beside the oak"],
    }
    payload.update(overrides)
    return api.client.post("/api/v1/base-stages/generated", json=payload)


def test_generated_base_stage_draft_preview_generate_and_publish(api):
    created = _create_generated_stage(api)
    assert created.status_code == 201, created.text
    stage = created.json()
    stage_id = stage["id"]

    # A draft is not usable yet: no image, and no panel may select it.
    assert (stage["origin"], stage["state"]) == ("generated", "draft")
    assert stage["content_url"] is None
    assert stage["is_editable"] is True
    assert api.client.get(f"/api/v1/base-stages/{stage_id}/content").status_code == 409

    preview = api.client.get(f"/api/v1/base-stages/{stage_id}/preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_generate"] is True
    assert body["estimated_cost_cents"] > 0
    assert "IDENTITY TARGETS" in body["prompt"]
    assert "Figure 1: figure above the slope" in body["prompt"]

    stale = api.client.post(
        f"/api/v1/base-stages/{stage_id}/generate",
        json={"expected_prompt_hash": "stale"},
    )
    assert stale.status_code == 409

    generated = api.client.post(
        f"/api/v1/base-stages/{stage_id}/generate",
        json={"expected_prompt_hash": body["prompt_hash"]},
    )
    assert generated.status_code == 201, generated.text
    attempt = generated.json()
    assert attempt["base_stage_id"] == stage_id
    assert attempt["scene_id"] is None
    assert attempt["attachments"] == []  # identity-neutral: no character refs
    candidate_id = attempt["candidates"][0]["id"]

    history = api.client.get(f"/api/v1/base-stages/{stage_id}/generations").json()
    assert [row["id"] for row in history] == [attempt["id"]]

    published = api.client.post(
        f"/api/v1/base-stages/{stage_id}/publish", json={"candidate_id": candidate_id}
    )
    assert published.status_code == 200, published.text
    ready = published.json()
    assert ready["state"] == "ready"
    assert ready["selected_candidate_id"] == candidate_id
    assert ready["content_url"] == f"/api/v1/base-stages/{stage_id}/content"
    assert ready["is_editable"] is False
    assert api.client.get(f"/api/v1/base-stages/{stage_id}/content").status_code == 200

    # Promotion is one-way; a variant needs a duplicate.
    assert (
        api.client.post(
            f"/api/v1/base-stages/{stage_id}/publish",
            json={"candidate_id": candidate_id},
        ).status_code
        == 409
    )
    copy = api.client.post(f"/api/v1/base-stages/{stage_id}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["state"] == "draft"
    assert copy.json()["id"] != stage_id


def test_generated_base_stage_edit_rules_and_validation(api):
    stage_id = _create_generated_stage(api).json()["id"]

    edited = api.client.put(
        f"/api/v1/base-stages/{stage_id}",
        json={
            "description": "A quieter ravine.",
            "beat_text": "They rest against the rope.",
            "camera": "thirty metres away",
            "framing": "wide shot",
            "mood": "weary",
            "aspect_ratio": "16:9",
            "style_id": _default_style_id(api),
            "model": "gemini-3.1-flash-image",
            "image_size": "1K",
            "targets": ["single figure"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["description"] == "A quieter ravine."
    assert edited.json()["revision"] == 1

    assert _create_generated_stage(api, targets=[]).status_code == 422
    assert _create_generated_stage(api, style_id=9999).status_code == 422
    assert _create_generated_stage(api, model="not-a-model").status_code == 422
    assert _create_generated_stage(api, image_size="9K").status_code == 422
    assert _create_generated_stage(api, aspect_ratio="7:5").status_code == 422

    # Uploaded stages have no composition to edit or duplicate.
    uploaded_id = _upload_base_stage(api).json()["id"]
    assert api.client.post(f"/api/v1/base-stages/{uploaded_id}/duplicate").status_code == 422
    assert api.client.get(f"/api/v1/base-stages/{uploaded_id}/preview").json()[
        "can_generate"
    ] is False


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


def test_budget_accepts_timezone_header_and_falls_back_to_utc(api):
    """/budget accepts X-Timezone (case-insensitive) and treats an invalid zone
    the same as UTC, so the value never depends on the server's own timezone."""
    from datetime import datetime, timezone

    from app.services.costs import CostLedger

    conn = connect(api.db_path)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        # Every generation must belong to exactly one panel or base stage
        # (017_base_stage_generations), so the spend row gets a real panel.
        style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
        scene_id = conn.execute(
            "INSERT INTO scene (style_id) VALUES (?)", (style_id,)
        ).lastrowid
        conn.execute(
            """
            INSERT INTO generation
                (scene_id, model, params_json, prompt_hash, request_json,
                 cost_usd_cents, reserved_cost_usd_cents, state,
                 price_table_version, scene_revision, created_at)
            VALUES (?, 'gemini-3.1-flash-image', '{}', 'hash', '{}',
                    33, 33, 'succeeded', 'test', 0, ?)
            """,
            (scene_id, ts),
        )
        conn.commit()
    finally:
        conn.close()

    # No header and an explicit UTC header must agree: the server+UTC boundary.
    no_header = api.client.get("/api/v1/budget").json()["spent_today_cents"]
    utc_header = api.client.get(
        "/api/v1/budget", headers={"X-Timezone": "UTC"}
    ).json()["spent_today_cents"]
    assert utc_header == no_header

    # An invalid zone also falls back to UTC (never raises, depends only on UTC).
    invalid = api.client.get(
        "/api/v1/budget", headers={"x-timezone": "Not/AZone"}
    ).json()
    assert invalid["spent_today_cents"] == no_header

    # The UTC attribution is exactly the documented conversion.
    expected = (
        33 if CostLedger._local_date(ts, "UTC") == ts[:10] else 0
    )
    assert no_header == expected


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
    assert "ref_image_ids" not in created.json()
    style_id = created.json()["id"]

    fetched = api.client.get(f"/api/v1/styles/{style_id}").json()
    assert fetched["name"] == "Ink Wash"
    assert "ref_image_ids" not in fetched

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
    assert panel["latest_attempt_preview_url"] is None
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
    generated = _generate_panel(api, panel["id"])
    assert generated.status_code == 201, generated.text
    assert generated.json()["state"] == "succeeded"

    listed_panel = api.client.get("/api/v1/panels").json()[0]
    candidate_id = generated.json()["candidates"][0]["id"]
    assert listed_panel["latest_attempt_preview_url"] == (
        f"/api/v1/candidates/{candidate_id}/content"
    )

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


def test_panel_model_can_change_after_success_without_rewriting_history(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    generated = _generate_panel(api, panel["id"]).json()

    changed = api.client.patch(
        f"/api/v1/panels/{panel['id']}/model",
        json={"model": "gemini-3-pro-image"},
    )

    assert changed.status_code == 200
    assert changed.json()["model"] == "gemini-3-pro-image"
    preview = api.client.get(f"/api/v1/panels/{panel['id']}/preview").json()
    assert preview["model"] == "gemini-3-pro-image"
    history = api.client.get(f"/api/v1/panels/{panel['id']}/generations").json()
    assert history[0]["id"] == generated["id"]
    assert history[0]["model"] == "gemini-3.1-flash-image"


def test_panel_model_cannot_change_while_generation_is_pending(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    conn = api.conn()
    try:
        conn.execute(
            "INSERT INTO generation (scene_id, model, state) VALUES (?, ?, 'pending')",
            (panel["id"], panel["model"]),
        )
        conn.commit()
    finally:
        conn.close()

    rejected = api.client.patch(
        f"/api/v1/panels/{panel['id']}/model",
        json={"model": "gemini-3-pro-image"},
    )

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["type"] == "SceneImmutableError"
    unchanged = api.client.get(f"/api/v1/panels/{panel['id']}").json()
    assert unchanged["model"] == "gemini-3.1-flash-image"


def test_generation_idempotency_key_returns_existing_attempt(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    headers = {"Idempotency-Key": "browser-request-1"}

    first = _generate_panel(api, panel["id"], headers=headers)
    replay = _generate_panel(api, panel["id"], headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert len(api.provider.requests) == 1


def test_actual_cost_overrun_is_returned_as_a_warning(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    from app.deps import settings

    api.provider.billed_cost_cents = settings.daily_spend_cap_cents + 1
    response = _generate_panel(api, panel["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["actual_cost_usd_cents"] == settings.daily_spend_cap_cents + 1
    assert any("exceeded" in warning for warning in body["warnings"])


def test_failed_generation_remains_editable_and_is_preserved_in_history(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    api.provider.error = RuntimeError("provider unavailable")

    failed = _generate_panel(api, panel["id"])
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
    _generate_panel(api, panel["id"])

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


def test_staged_panel_crud_preview_generate_duplicate_and_no_source_hash(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    stage_response = _upload_base_stage(
        api,
        description="A traveler stands under a stone arch.",
        targets=["traveler beneath arch"],
    )
    stage = stage_response.json()
    payload = {
        "base_stage_id": stage["id"],
        "cast": [
            {
                "character_id": character["id"],
                "base_stage_target_id": stage["targets"][0]["id"],
                "role": "this must be discarded",
            }
        ],
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
    }

    created = api.client.post("/api/v1/panels", json=payload)
    assert created.status_code == 201, created.text
    panel = created.json()
    assert panel["base_stage_id"] == stage["id"]
    assert panel["base_stage"]["content_url"] == stage["content_url"]
    assert panel["beat_text"] == stage["description"]
    assert panel["camera"] == panel["framing"] == panel["mood"] == ""
    assert panel["aspect_ratio"] == stage["aspect_ratio"]
    assert panel["style_id"] is None
    assert panel["cast"][0]["role"] == ""
    assert "sha" not in json.dumps(panel).lower()
    assert api.client.get(f"/api/v1/panels/{panel['id']}").json() == panel

    updated = api.client.put(f"/api/v1/panels/{panel['id']}", json=payload)
    assert updated.status_code == 200
    preview = api.client.get(f"/api/v1/panels/{panel['id']}/preview").json()
    assert preview["base_stage_id"] == stage["id"]
    assert preview["source_content_url"] == stage["content_url"]
    assert preview["attachments"][0]["image_number"] == 2
    assert "content_sha256" not in json.dumps(preview)

    generated = api.client.post(
        f"/api/v1/panels/{panel['id']}/generate",
        json={"expected_prompt_hash": preview["prompt_hash"]},
    )
    assert generated.status_code == 201, generated.text
    assert generated.json()["interaction_id"] == "api-stage-interaction"
    assert api.provider.requests == []
    assert len(api.provider.edits) == 1

    assert api.client.delete(f"/api/v1/base-stages/{stage['id']}").status_code == 204
    duplicated = api.client.post(f"/api/v1/panels/{panel['id']}/duplicate")
    assert duplicated.status_code == 201
    assert duplicated.json()["base_stage_id"] == stage["id"]
    assert duplicated.json()["cast"][0]["base_stage_target_id"] == stage["targets"][0]["id"]


def test_staged_panel_validation_and_blocked_preview_include_source_fields(api):
    first = _create_character(api, "Elias", "elias")
    second = _create_character(api, "Mara", "mara")
    stage = _upload_base_stage(
        api, targets=["left figure", "right figure"]
    ).json()
    base = {
        "base_stage_id": stage["id"],
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
    }
    duplicate_target = api.client.post(
        "/api/v1/panels",
        json={
            **base,
            "cast": [
                {"character_id": first["id"], "base_stage_target_id": stage["targets"][0]["id"]},
                {"character_id": second["id"], "base_stage_target_id": stage["targets"][0]["id"]},
            ],
        },
    )
    assert duplicate_target.status_code == 422
    assert "mapped only once" in duplicate_target.text

    valid = api.client.post(
        "/api/v1/panels",
        json={
            **base,
            "cast": [
                {"character_id": first["id"], "base_stage_target_id": stage["targets"][0]["id"]},
                {"character_id": second["id"], "base_stage_target_id": stage["targets"][1]["id"]},
            ],
        },
    ).json()
    blocked = api.client.get(f"/api/v1/panels/{valid['id']}/preview").json()
    assert blocked["can_generate"] is False
    assert blocked["base_stage_id"] == stage["id"]
    assert blocked["source_content_url"] == stage["content_url"]
    assert "no canonical reference set" in blocked["blocked_reason"]

    assert api.client.delete(f"/api/v1/base-stages/{stage['id']}").status_code == 204
    newly_selected = api.client.post("/api/v1/panels", json={**base, "cast": [
        {"character_id": first["id"], "base_stage_target_id": stage["targets"][0]["id"]},
        {"character_id": second["id"], "base_stage_target_id": stage["targets"][1]["id"]},
    ]})
    assert newly_selected.status_code == 422
    assert "archived" in newly_selected.text


def test_panel_generate_rejects_prompt_changed_after_preview(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    preview = api.client.get(f"/api/v1/panels/{panel['id']}/preview").json()
    style = api.client.get(f"/api/v1/styles/{panel['style_id']}").json()
    updated = api.client.put(
        f"/api/v1/styles/{panel['style_id']}",
        json={
            "name": style["name"],
            "style_contract": f"{style['style_contract']} Changed after preview.",
        },
    )
    assert updated.status_code == 200

    response = api.client.post(
        f"/api/v1/panels/{panel['id']}/generate",
        json={"expected_prompt_hash": preview["prompt_hash"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "PreviewChangedError"
    assert api.provider.requests == []
    assert api.client.get(f"/api/v1/panels/{panel['id']}/generations").json() == []


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

    generated = _generate_panel(api, panel["id"])
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


def test_generation_history_includes_candidate_previews(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    generated = _generate_panel(api, panel["id"])
    assert generated.status_code == 201

    history = api.client.get(f"/api/v1/panels/{panel['id']}/generations")
    assert history.status_code == 200
    attempts = history.json()
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt["id"] == generated.json()["id"]
    assert len(attempt["candidates"]) == 1
    candidate = attempt["candidates"][0]
    assert candidate["review_status"] == "pending"
    assert candidate["content_url"] == f"/api/v1/candidates/{candidate['id']}/content"


def test_invalid_review_verdict_is_422(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    generation = _generate_panel(api, panel["id"]).json()
    candidate_id = generation["candidates"][0]["id"]
    resp = api.client.post(
        f"/api/v1/candidates/{candidate_id}/review", json={"verdict": "maybe"}
    )
    assert resp.status_code == 422


def test_gallery_lists_only_accepted_candidates(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    accepted = _generate_panel(api, panel["id"]).json()
    candidate = accepted["candidates"][0]
    resp = api.client.post(
        f"/api/v1/candidates/{candidate['id']}/review", json={"verdict": "accepted"}
    )
    assert resp.status_code == 200

    pending_panel = _create_panel(api, [character["id"]])
    _generate_panel(api, pending_panel["id"])

    gallery = api.client.get("/api/v1/gallery")
    assert gallery.status_code == 200
    items = gallery.json()
    assert len(items) == 1
    item = items[0]
    assert item["candidate_id"] == candidate["id"]
    assert item["content_url"] == f"/api/v1/candidates/{candidate['id']}/content"
    assert item["panel_id"] == panel["id"]
    assert item["aspect_ratio"]
    assert item["beat_text"].strip()


def test_generation_not_found_is_404(api):
    resp = api.client.get("/api/v1/generations/9999")
    assert resp.status_code == 404


def test_panel_not_found_is_404(api):
    resp = api.client.get("/api/v1/panels/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# archive / restore (characters, styles) and hard delete (panels)
# ---------------------------------------------------------------------------


def test_character_archive_hides_from_list_and_restore_brings_it_back(api):
    character = _create_character(api)
    cid = character["id"]

    archived = api.client.delete(f"/api/v1/characters/{cid}")
    assert archived.status_code == 204

    active = api.client.get("/api/v1/characters").json()
    assert cid not in {c["id"] for c in active}

    archived_list = api.client.get("/api/v1/characters/archived").json()
    assert cid in {c["id"] for c in archived_list}

    # The archived character still resolves individually (existing panels need it).
    still_there = api.client.get(f"/api/v1/characters/{cid}")
    assert still_there.status_code == 200
    assert still_there.json()["archived_at"] is not None

    restored = api.client.post(f"/api/v1/characters/{cid}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert cid in {c["id"] for c in api.client.get("/api/v1/characters").json()}


def test_character_archive_frees_slug_for_reuse(api):
    character = _create_character(api, name="Alice", slug="alice")
    assert api.client.delete(f"/api/v1/characters/{character['id']}").status_code == 204
    reused = api.client.post(
        "/api/v1/characters",
        json={"name": "Alice", "slug": "alice", "visual_contract": "x"},
    )
    assert reused.status_code == 201
    assert reused.json()["id"] != character["id"]


def test_style_archive_and_restore(api):
    created = api.client.post("/api/v1/styles", json={"name": "Ink Wash"}).json()
    sid = created["id"]

    assert api.client.delete(f"/api/v1/styles/{sid}").status_code == 204
    assert sid not in {s["id"] for s in api.client.get("/api/v1/styles").json()}
    assert sid in {s["id"] for s in api.client.get("/api/v1/styles/archived").json()}

    # Name is freed for a new active style.
    reused = api.client.post("/api/v1/styles", json={"name": "Ink Wash"})
    assert reused.status_code == 201

    # Restoring now clashes with the active style holding the name -> 409.
    clash = api.client.post(f"/api/v1/styles/{sid}/restore")
    assert clash.status_code == 409


def test_default_style_archive_is_409(api):
    sid = _default_style_id(api)
    resp = api.client.delete(f"/api/v1/styles/{sid}")
    assert resp.status_code == 409


def test_archived_style_still_usable_by_existing_panel(api):
    """Archiving a style must not break panels that already reference it."""
    style = api.client.post("/api/v1/styles", json={"name": "Ephemeral"}).json()
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = api.client.post(
        "/api/v1/panels",
        json={
            "beat_text": "A lone figure on the moor.",
            "camera": "eye level",
            "framing": "wide",
            "mood": "bleak",
            "aspect_ratio": "3:2",
            "cast": [{"character_id": character["id"], "role": "lead", "prominence": 1}],
            "style_id": style["id"],
            "model": "gemini-3.1-flash-image",
            "image_size": "1K",
        },
    ).json()

    assert api.client.delete(f"/api/v1/styles/{style['id']}").status_code == 204

    # The panel still loads and previews with the archived style.
    fetched = api.client.get(f"/api/v1/panels/{panel['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["style_id"] == style["id"]
    preview = api.client.get(f"/api/v1/panels/{panel['id']}/preview")
    assert preview.status_code == 200


def test_panel_hard_delete_removes_panel_and_generation_history(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    panel = _create_panel(api, [character["id"]])
    pid = panel["id"]

    gen = _generate_panel(api, pid)
    assert gen.status_code in (200, 201), gen.text

    deleted = api.client.delete(f"/api/v1/panels/{pid}")
    assert deleted.status_code == 204

    assert api.client.get(f"/api/v1/panels/{pid}").status_code == 404
    assert pid not in {p["id"] for p in api.client.get("/api/v1/panels").json()}

    # The generation history is gone too (hard delete cascades).
    conn = connect(api.db_path)
    try:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM generation WHERE scene_id = ?", (pid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert remaining == 0


def test_panel_delete_missing_is_404(api):
    assert api.client.delete("/api/v1/panels/9999").status_code == 404


def test_character_and_style_restore_missing_is_404(api):
    assert api.client.post("/api/v1/characters/9999/restore").status_code == 404
    assert api.client.post("/api/v1/styles/9999/restore").status_code == 404


def test_base_stage_panels_endpoint_lists_only_staged_panels(api):
    character = _create_character(api)
    _promote_canonical(api, character["id"])
    stage = _upload_base_stage(
        api, description="Under an arch.", targets=["traveler beneath arch"]
    ).json()

    _create_panel(api, [character["id"]])  # unrelated direct panel

    staged = api.client.post(
        "/api/v1/panels",
        json={
            "base_stage_id": stage["id"],
            "cast": [
                {
                    "character_id": character["id"],
                    "base_stage_target_id": stage["targets"][0]["id"],
                    "role": "",
                }
            ],
            "model": "gemini-3.1-flash-image",
            "image_size": "1K",
        },
    )
    assert staged.status_code == 201, staged.text
    panel = staged.json()

    listed = api.client.get(f"/api/v1/base-stages/{stage['id']}/panels")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [row["id"] for row in rows] == [panel["id"]]
    assert rows[0]["beat_text"] == stage["description"]
    assert rows[0]["is_editable"] is True
    assert rows[0]["generation_count"] == 0
    assert rows[0]["latest_attempt_preview_url"] is None
    assert "cast" not in json.dumps(rows)

    assert api.client.get("/api/v1/base-stages/99999/panels").status_code == 404
