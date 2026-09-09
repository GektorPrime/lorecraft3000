"""Backend contracts for uploaded gallery pictures and panel integration."""

from __future__ import annotations

import importlib
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.db import connect
from app.deps import get_conn, get_storage
from app.main import app
from app.migrate import MIGRATIONS, run_migrations
from app.services.gallery import GalleryPictureService, GalleryPictureValidationError
from app.services.panels import PanelGalleryPictureConflictError, PanelService
from app.storage import ImageStorage


def _image_bytes(format="PNG", size=(12, 8), *, animated=False):
    output = io.BytesIO()
    image = Image.new("RGB", size, (10, 20, 30))
    if animated:
        second = Image.new("RGB", size, (30, 20, 10))
        image.save(output, format=format, save_all=True, append_images=[second])
    else:
        image.save(output, format=format)
    return output.getvalue()


def _oriented_jpeg() -> bytes:
    output = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (12, 8), (10, 20, 30)).save(output, format="JPEG", exif=exif)
    return output.getvalue()


def _transparent_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def gallery_api(tmp_path):
    db_path = tmp_path / "gallery.db"
    storage = ImageStorage(tmp_path / "store")
    run_migrations(db_path)

    def override_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = override_conn
    app.dependency_overrides[get_storage] = lambda: storage
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, db_path, storage
    finally:
        app.dependency_overrides.clear()


def test_upload_gallery_content_archive_restore_and_filename_per_row(gallery_api):
    client, _, _ = gallery_api
    data = _image_bytes()
    first = client.post(
        "/api/v1/gallery-pictures",
        data={"title": "  Establishing shot  "},
        files={"image": ("first.png", data, "image/png")},
    )
    second = client.post(
        "/api/v1/gallery-pictures",
        data={"title": "Duplicate bytes"},
        files={"image": ("second.png", data, "image/png")},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["title"] == "Establishing shot"
    assert first.json()["original_filename"] == "first.png"
    assert second.json()["original_filename"] == "second.png"
    assert first.json()["dimensions"] == {"width": 12, "height": 8}
    assert "sha256" not in first.text

    content = client.get(first.json()["content_url"])
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.content == data

    gallery = client.get("/api/v1/gallery").json()
    upload = next(item for item in gallery if item["source_id"] == first.json()["id"])
    assert upload == {
        "source_type": "upload",
        "source_id": first.json()["id"],
        "candidate_id": None,
        "gallery_picture_id": first.json()["id"],
        "content_url": first.json()["content_url"],
        "scene_id": None,
        "description": "Establishing shot",
        "beat_text": None,
        "aspect_ratio": "3:2",
        "created_at": first.json()["created_at"],
    }

    archived = client.delete(f"/api/v1/gallery-pictures/{first.json()['id']}")
    assert archived.status_code == 204
    assert first.json()["id"] not in {
        item["gallery_picture_id"] for item in client.get("/api/v1/gallery").json()
    }
    assert client.get(first.json()["content_url"]).status_code == 200
    restored = client.post(f"/api/v1/gallery-pictures/{first.json()['id']}/restore")
    assert restored.status_code == 200 and restored.json()["archived_at"] is None


@pytest.mark.parametrize(
    ("data", "filename", "mime", "message"),
    [
        (b"not an image", "bad.png", "image/png", "not a decodable image"),
        (_image_bytes("GIF"), "bad.gif", "image/gif", "PNG, JPEG, or WebP"),
        (_image_bytes("WEBP", animated=True), "animated.webp", "image/webp", "animated"),
    ],
)
def test_upload_rejects_invalid_images(gallery_api, data, filename, mime, message):
    client, _, _ = gallery_api
    response = client.post(
        "/api/v1/gallery-pictures",
        data={"title": "Invalid"},
        files={"image": (filename, data, mime)},
    )
    assert response.status_code == 422
    assert message in response.json()["detail"]["message"]


def test_upload_uses_exif_adjusted_dimensions_and_aspect_ratio(gallery_api):
    client, _, _ = gallery_api
    response = client.post(
        "/api/v1/gallery-pictures",
        data={"title": "Portrait"},
        files={"image": ("portrait.jpg", _oriented_jpeg(), "image/jpeg")},
    )
    assert response.status_code == 201
    assert response.json()["dimensions"] == {"width": 8, "height": 12}
    item = next(
        item for item in client.get("/api/v1/gallery").json()
        if item["gallery_picture_id"] == response.json()["id"]
    )
    assert item["aspect_ratio"] == "2:3"


def test_panel_api_rejects_boolean_picture_id(gallery_api):
    client, _, _ = gallery_api
    response = client.post(
        "/api/v1/panels",
        json={"title": "Invalid", "format": "square", "gallery_picture_id": True},
    )
    assert response.status_code == 422


def test_service_rejects_title_and_image_limits(conn, storage):
    service = GalleryPictureService(conn, storage)
    with pytest.raises(GalleryPictureValidationError, match="title is required"):
        service.upload(_image_bytes(), "  ")
    with pytest.raises(GalleryPictureValidationError, match="120"):
        service.upload(_image_bytes(), "x" * 121)
    with pytest.raises(GalleryPictureValidationError, match="width exceeds 8192"):
        service.upload(_image_bytes(size=(8193, 1)), "Too wide")


def test_panel_create_update_render_and_archived_retention(conn, storage):
    pictures = GalleryPictureService(conn, storage)
    first = pictures.upload(_image_bytes(), "First")
    second = pictures.upload(_image_bytes(size=(8, 12)), "Second")
    panels = PanelService(conn)
    panel = panels.create(
        title="Upload panel", format="square", gallery_picture_id=first.id
    )
    assert panel.slots[0].candidate_id is None
    assert panel.slots[0].gallery_picture_id == first.id

    pictures.archive(first.id)
    slot = panel.slots[0]
    retained = [{
        "candidate_id": None, "gallery_picture_id": first.id, "slot_index": 0,
        "x0": slot.x0, "y0": slot.y0, "x1": slot.x1, "y1": slot.y1,
        "focal_x": slot.focal_x, "focal_y": slot.focal_y, "zoom": slot.zoom,
    }]
    panel = panels.update(
        panel.id, expected_revision=panel.revision, title=panel.title,
        format=panel.format, background_color="#FFFFFF", gutter_px=20,
        frame_px=0, slots=retained,
    )
    from app.services.panel_rendering import PanelRenderService

    render = PanelRenderService(conn, storage).render(
        panel.id, expected_revision=panel.revision
    )
    snapshot = render.layout["slots"][0]
    assert snapshot["source_type"] == "upload"
    assert snapshot["candidate_id"] is None
    assert snapshot["gallery_picture_id"] == first.id

    other = panels.create(title="Other", format="square")
    with pytest.raises(PanelGalleryPictureConflictError, match="archived"):
        panels.update(
            other.id, expected_revision=other.revision, title=other.title,
            format=other.format, background_color="#FFFFFF", gutter_px=20,
            frame_px=0, slots=retained,
        )
    pictures.archive(second.id)
    with pytest.raises(PanelGalleryPictureConflictError):
        panels.create(title="No", format="square", gallery_picture_id=second.id)


def test_panel_render_composites_upload_transparency_over_background(conn, storage):
    picture = GalleryPictureService(conn, storage).upload(
        _transparent_png(), "Transparent"
    )
    panel = PanelService(conn).create(
        title="Transparency", format="square", gallery_picture_id=picture.id
    )
    from app.services.panel_rendering import PanelRenderService

    render = PanelRenderService(conn, storage).render(
        panel.id, expected_revision=panel.revision
    )
    sha256 = conn.execute(
        "SELECT sha256 FROM panel_render WHERE id=?", (render.id,)
    ).fetchone()[0]
    data, _ = storage.read(sha256)
    with Image.open(io.BytesIO(data)) as image:
        assert image.getpixel((image.width // 2, image.height // 2)) == (255, 255, 255)


def test_migration_rebuild_preserves_slots_and_enforces_sources(tmp_path):
    db = tmp_path / "through-020.db"
    conn = connect(db)
    try:
        for module_name in MIGRATIONS[:-1]:
            importlib.import_module(module_name).upgrade(conn)
        panel_id = conn.execute(
            "INSERT INTO panel (title, format, width_px, height_px) "
            "VALUES ('Existing', 'square', 1600, 1600)"
        ).lastrowid
        slot_id = conn.execute(
            "INSERT INTO panel_slot (panel_id, slot_index, x0, y0, x1, y1) "
            "VALUES (?, 0, 0, 0, 1, 1)", (panel_id,)
        ).lastrowid
        importlib.import_module(MIGRATIONS[-1]).upgrade(conn)
        conn.commit()
        row = conn.execute("SELECT * FROM panel_slot WHERE id=?", (slot_id,)).fetchone()
        assert row["panel_id"] == panel_id and row["gallery_picture_id"] is None
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(panel_slot)")}
        assert {"idx_panel_slot_candidate", "idx_panel_slot_gallery_picture"} <= indexes
        picture_id = conn.execute(
            "INSERT INTO gallery_picture "
            "(sha256, title, image_width, image_height) VALUES (?, 'Picture', 8, 8)",
            ("a" * 64,),
        ).lastrowid
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE panel_slot SET candidate_id=999, gallery_picture_id=? WHERE id=?",
                (picture_id, slot_id),
            )
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO gallery_picture "
                "(sha256, title, image_width, image_height) VALUES (?, 'Bad', 8192, 8192)",
                ("b" * 64,),
            )
    finally:
        conn.close()


def test_maintenance_tracks_gallery_picture_hash(conn, storage):
    from app.maintenance import run_check

    ghost = "d" * 64
    conn.execute(
        "INSERT INTO gallery_picture (sha256, title, image_width, image_height) "
        "VALUES (?, 'Missing', 8, 8)", (ghost,)
    )
    conn.commit()
    assert run_check(conn, storage).dangling_db_hashes == (ghost,)
