"""Route-level tests for the library UI (HTMX server-rendered pages).

Uses dependency_overrides so every request hits an isolated temp DB + store.
No network access.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.deps import get_conn, get_storage
from app.main import app
from app.migrate import run_migrations
from app.storage import ImageStorage
from tests.conftest import make_png_bytes


@pytest.fixture
def client(tmp_path):
    """TestClient with temp DB + store wired via dependency overrides."""
    db_path = tmp_path / "routes.db"
    store_root = tmp_path / "store"
    run_migrations(db_path)

    def override_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = override_conn
    app.dependency_overrides[get_storage] = lambda: ImageStorage(store_root)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    app.dependency_overrides.clear()


def _create_character(client, name="Elias", slug="elias", visual_contract="Pale eyes."):
    resp = client.post(
        "/characters",
        data={
            "name": name,
            "slug": slug,
            "lore_md": "local lore",
            "visual_contract": visual_contract,
            "negative_traits": "no smile",
            "default_style_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp.headers["location"]


# ---------------------------------------------------------------------------
# character pages
# ---------------------------------------------------------------------------

def test_characters_list_page(client):
    resp = client.get("/characters")
    assert resp.status_code == 200
    assert "Characters" in resp.text
    assert "New character" in resp.text


def test_new_character_form_page(client):
    resp = client.get("/characters/new")
    assert resp.status_code == 200
    assert 'name="visual_contract"' in resp.text
    assert 'name="lore_md"' in resp.text
    assert 'name="slug"' in resp.text
    # The seeded default style is offered in the select.
    assert "Victorian Oil Painting" in resp.text


def test_create_character_via_route(client):
    location = _create_character(client)
    assert location == "/characters/1"

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Elias" in detail.text
    assert "elias" in detail.text


def test_create_character_over_cap_shows_error(client):
    contract = "word " * 61
    resp = client.post(
        "/characters",
        data={
            "name": "Elias",
            "slug": "",
            "visual_contract": contract,
            "default_style_id": "",
        },
    )
    assert resp.status_code == 422
    assert "60-word cap" in resp.text
    # No character was created.
    assert client.get("/characters").text.count("Elias") == 0


def test_create_character_slug_collision_shows_error(client):
    _create_character(client, name="Elias", slug="elias")
    resp = client.post(
        "/characters",
        data={"name": "Elias 2", "slug": "elias", "default_style_id": ""},
    )
    assert resp.status_code == 422
    assert "already taken" in resp.text


def test_character_detail_shows_ref_set_versions(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]

    resp = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/ref-sets/")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Reference-set versions" in detail.text
    assert "v1" in detail.text
    assert "draft" in detail.text


def test_edit_character_via_route(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]

    form = client.get(f"/characters/{character_id}/edit")
    assert form.status_code == 200
    assert 'value="Elias"' in form.text

    resp = client.post(
        f"/characters/{character_id}/edit",
        data={
            "name": "Elias Thorne",
            "slug": "elias-thorne",
            "visual_contract": "Pale eyes.",
            "default_style_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Elias Thorne" in client.get(location).text


def test_failed_character_edit_keeps_edit_action(client):
    """A failed edit (over-cap contract) must re-render the form targeting the
    EDIT endpoint with the user's values, and a corrected retry must UPDATE the
    existing character rather than create a duplicate."""
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]

    resp = client.post(
        f"/characters/{character_id}/edit",
        data={
            "name": "Elias",
            "slug": "elias",
            "visual_contract": "blah " * 61,
            "default_style_id": "",
        },
    )
    assert resp.status_code == 422
    assert "60-word cap" in resp.text
    # The form must keep the entity identity and submit to the edit endpoint.
    assert f'action="/characters/{character_id}/edit"' in resp.text
    # The user's submitted values are preserved in the re-rendered form.
    assert "blah blah" in resp.text

    # Corrected retry: updates the existing character, no duplicate created.
    resp = client.post(
        f"/characters/{character_id}/edit",
        data={
            "name": "Elias Thorne",
            "slug": "elias",
            "visual_contract": "Pale eyes.",
            "default_style_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == location
    assert "Elias Thorne" in client.get(location).text
    assert client.get("/characters").text.count("Elias Thorne") == 1


def test_failed_character_edit_slug_collision_keeps_edit_action(client):
    _create_character(client, name="Ada", slug="ada")
    location = _create_character(client, name="Elias", slug="elias")
    character_id = location.rsplit("/", 1)[-1]

    resp = client.post(
        f"/characters/{character_id}/edit",
        data={
            "name": "Elias",
            "slug": "ada",
            "visual_contract": "Pale eyes.",
            "default_style_id": "",
        },
    )
    assert resp.status_code == 422
    assert "already taken" in resp.text
    assert f'action="/characters/{character_id}/edit"' in resp.text


def test_create_character_invalid_style_reference_shows_error(client):
    resp = client.post(
        "/characters",
        data={
            "name": "Elias",
            "slug": "elias",
            "visual_contract": "Pale eyes.",
            "default_style_id": "99999",
        },
    )
    assert resp.status_code == 422
    assert "default_style_id 99999" in resp.text
    assert "does not reference an existing style" in resp.text
    # No character was created.
    assert client.get("/characters").text.count("Elias") == 0


def test_create_character_malformed_style_id_shows_error(client):
    resp = client.post(
        "/characters",
        data={
            "name": "Elias",
            "slug": "elias",
            "visual_contract": "Pale eyes.",
            "default_style_id": "not-an-integer",
        },
    )
    assert resp.status_code == 422
    assert "default_style_id must be an integer" in resp.text
    assert client.get("/characters").text.count("Elias") == 0


def test_edit_character_invalid_style_reference_shows_error(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]

    resp = client.post(
        f"/characters/{character_id}/edit",
        data={
            "name": "Elias",
            "slug": "elias",
            "visual_contract": "Pale eyes.",
            "default_style_id": "99999",
        },
    )
    assert resp.status_code == 422
    assert "does not reference an existing style" in resp.text
    # Edit action preserved so the retry still targets this character.
    assert f'action="/characters/{character_id}/edit"' in resp.text
    # Character unchanged: default style is still none.
    assert "none" in client.get(location).text


def test_character_detail_escapes_user_html(client):
    """User-supplied lore/contract/traits must be HTML-escaped on the detail
    page; only the literal empty-state markup may render as markup."""
    resp = client.post(
        "/characters",
        data={
            "name": "Elias",
            "slug": "elias",
            "lore_md": "<script>alert('lore')</script>",
            "visual_contract": "<b>bold contract</b>",
            "negative_traits": "<img src=x onerror=alert(1)>",
            "default_style_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    detail = client.get(resp.headers["location"])
    assert detail.status_code == 200
    # Raw injected markup must not appear.
    assert "<script>alert('lore')</script>" not in detail.text
    assert "<b>bold contract</b>" not in detail.text
    assert "<img src=x onerror=alert(1)>" not in detail.text
    # Escaped forms appear.
    assert "&lt;script&gt;alert(&#39;lore&#39;)&lt;/script&gt;" in detail.text
    assert "&lt;b&gt;bold contract&lt;/b&gt;" in detail.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in detail.text


# ---------------------------------------------------------------------------
# style pages
# ---------------------------------------------------------------------------

def test_styles_list_shows_seeded_default(client):
    resp = client.get("/styles")
    assert resp.status_code == 200
    assert "Victorian Oil Painting" in resp.text


def test_new_style_form_page(client):
    resp = client.get("/styles/new")
    assert resp.status_code == 200
    assert 'name="style_contract"' in resp.text
    assert "ref_image_ids" not in resp.text


def test_create_style_via_route(client):
    resp = client.post(
        "/styles",
        data={
            "name": "Ink Wash",
            "style_contract": "Loose ink wash.",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Ink Wash" in client.get("/styles").text


def test_create_style_duplicate_name_shows_error(client):
    client.post("/styles", data={"name": "Ink Wash"})
    resp = client.post("/styles", data={"name": "Ink Wash"})
    assert resp.status_code == 422
    assert "already taken" in resp.text


def test_failed_style_edit_keeps_edit_action(client):
    """A failed edit (duplicate name) must re-render the form targeting the
    EDIT endpoint with the user's values, and a corrected retry must UPDATE the
    existing style rather than create a duplicate."""
    client.post("/styles", data={"name": "Ink Wash"})
    # The seeded default style is the first style row (id 1) in a fresh DB.
    resp = client.post(
        "/styles/1/edit",
        data={
            "name": "Ink Wash",
            "style_contract": "New contract text.",
        },
    )
    assert resp.status_code == 422
    assert "already taken" in resp.text
    # The form must keep the entity identity and submit to the edit endpoint.
    assert 'action="/styles/1/edit"' in resp.text
    # The user's submitted values are preserved in the re-rendered form.
    assert "New contract text." in resp.text

    # Corrected retry: updates style 1, no duplicate style created.
    resp = client.post(
        "/styles/1/edit",
        data={
            "name": "Victorian Oil Painting",
            "style_contract": "Updated contract.",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Updated contract." in client.get("/styles").text
    assert client.get("/styles").text.count("Ink Wash") == 1


def test_styles_list_escapes_user_html(client):
    """User-supplied style contract must be HTML-escaped on the list page."""
    client.post(
        "/styles",
        data={
            "name": "Ink Wash",
            "style_contract": "<script>alert('style')</script>",
        },
    )
    page = client.get("/styles").text
    assert "<script>alert('style')</script>" not in page
    assert "&lt;script&gt;alert(&#39;style&#39;)&lt;/script&gt;" in page


# ---------------------------------------------------------------------------
# reference-set workflow pages
# ---------------------------------------------------------------------------

def test_ref_set_upload_promote_flow(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]

    # Create a draft.
    resp = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    ref_set_url = resp.headers["location"]
    ref_set_id = ref_set_url.rsplit("/", 1)[-1]

    # Upload an image with a role (multipart, real storage behind the route).
    resp = client.post(
        f"/ref-sets/{ref_set_id}/images",
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
        data={"role": "face_front"},
    )
    assert resp.status_code == 200
    assert "face_front" in resp.text
    assert "ref.png" not in resp.text  # fragment shows sha256, not filename

    # Detail page shows the image.
    detail = client.get(ref_set_url)
    assert detail.status_code == 200
    assert "face_front" in detail.text

    # Promote -> redirect to the character detail page.
    resp = client.post(f"/ref-sets/{ref_set_id}/promote", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == location
    assert "canonical" in client.get(location).text


def test_ref_set_upload_invalid_role_shows_error(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]
    resp = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    ref_set_id = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.post(
        f"/ref-sets/{ref_set_id}/images",
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
        data={"role": "bogus"},
    )
    assert resp.status_code == 200
    assert "invalid role" in resp.text
    assert "No images yet" in resp.text


def test_ref_upload_rejects_bad_mime_and_oversized_file(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]
    draft = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    ref_set_id = draft.headers["location"].rsplit("/", 1)[-1]

    bad_mime = client.post(
        f"/ref-sets/{ref_set_id}/images",
        data={"role": "face_front"},
        files={"image": ("notes.txt", b"not an image", "text/plain")},
    )
    assert bad_mime.status_code == 200
    assert "PNG, JPEG, or WebP" in bad_mime.text

    oversized = client.post(
        f"/ref-sets/{ref_set_id}/images",
        data={"role": "face_front"},
        files={"image": ("huge.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 200
    assert "10 MB limit" in oversized.text

    # Declared MIME is not trusted: Pillow-decoded GIF bytes are still rejected.
    import io
    from PIL import Image

    gif = io.BytesIO()
    Image.new("RGB", (2, 2)).save(gif, format="GIF")
    spoofed = client.post(
        f"/ref-sets/{ref_set_id}/images",
        data={"role": "face_front"},
        files={"image": ("fake.png", gif.getvalue(), "image/png")},
    )
    assert spoofed.status_code == 200
    assert "decoded image format GIF is not allowed" in spoofed.text


def test_ref_set_remove_and_rerole_via_route(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]
    resp = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    ref_set_id = resp.headers["location"].rsplit("/", 1)[-1]

    resp = client.post(
        f"/ref-sets/{ref_set_id}/images",
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
        data={"role": "face_front"},
    )
    assert resp.status_code == 200

    # Re-role the image.
    resp = client.post(
        f"/ref-sets/{ref_set_id}/images/1/role", data={"role": "outfit"}
    )
    assert resp.status_code == 200
    assert "outfit" in resp.text

    # Remove the image.
    resp = client.post(f"/ref-sets/{ref_set_id}/images/1/remove")
    assert resp.status_code == 200
    assert "No images yet" in resp.text


def test_copy_ref_set_via_route(client):
    location = _create_character(client)
    character_id = location.rsplit("/", 1)[-1]
    resp = client.post(
        f"/characters/{character_id}/ref-sets", follow_redirects=False
    )
    ref_set_id = resp.headers["location"].rsplit("/", 1)[-1]
    client.post(
        f"/ref-sets/{ref_set_id}/images",
        files={"image": ("ref.png", make_png_bytes(), "image/png")},
        data={"role": "face_front"},
    )

    resp = client.post(f"/ref-sets/{ref_set_id}/copy", follow_redirects=False)
    assert resp.status_code == 303
    new_url = resp.headers["location"]
    assert new_url != f"/ref-sets/{ref_set_id}"
    assert "v2" in client.get(new_url).text
    assert "face_front" in client.get(new_url).text
