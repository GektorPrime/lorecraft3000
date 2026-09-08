"""Backend contracts for comic page templates, aggregates, and renders."""

from __future__ import annotations

import io
import json
import sqlite3
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main_module
from app.config import Settings
from app.db import connect
from app.deps import get_conn, get_storage
from app.main import app
from app.migrate import run_migrations
from app.services.comic_pages import (
    PageCandidateConflictError,
    PageIncompleteError,
    PageRevisionConflictError,
    PageService,
    PageValidationError,
)
from app.services.page_rendering import PageRenderService
from app.services.scenes import SceneDeleteConflictError, SceneService
from app.storage import ImageStorage


@dataclass
class PageApi:
    client: TestClient
    db_path: object
    storage: ImageStorage

    def conn(self):
        return connect(self.db_path)


@pytest.fixture
def page_api(tmp_path, monkeypatch):
    db_path = tmp_path / "pages-api.db"
    storage = ImageStorage(tmp_path / "store")
    run_migrations(db_path)
    monkeypatch.setattr(
        main_module, "settings", Settings(db_path=db_path, store_root=storage.root)
    )

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
            yield PageApi(client, db_path, storage)
    finally:
        app.dependency_overrides.clear()


def _gradient_png(width=400, height=200) -> bytes:
    image = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _candidate(conn, storage, *, accepted=True, state="succeeded", base_stage=False, color=None):
    if base_stage:
        owner_id = conn.execute(
            "INSERT INTO base_stage (origin, state, description, aspect_ratio) "
            "VALUES ('generated', 'draft', 'test', '1:1')"
        ).lastrowid
        generation_id = conn.execute(
            "INSERT INTO generation (base_stage_id, model, state) VALUES (?, 'test', ?)",
            (owner_id, state),
        ).lastrowid
    else:
        style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
        scene_id = conn.execute("INSERT INTO scene (style_id) VALUES (?)", (style_id,)).lastrowid
        generation_id = conn.execute(
            "INSERT INTO generation (scene_id, model, state) VALUES (?, 'test', ?)",
            (scene_id, state),
        ).lastrowid
    data = _gradient_png() if color is None else _solid_png(color)
    stored = storage.store(data)
    candidate_id = conn.execute(
        "INSERT INTO candidate (generation_id, sha256, review_status) VALUES (?, ?, ?)",
        (generation_id, stored.sha256, "accepted" if accepted else "pending"),
    ).lastrowid
    conn.commit()
    return int(candidate_id)


def _solid_png(color) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (400, 200), color).save(output, format="PNG")
    return output.getvalue()


def _panel(candidate_id, slot_index, **overrides):
    return {
        "candidate_id": candidate_id,
        "slot_index": slot_index,
        "focal_x": overrides.get("focal_x", 0.5),
        "focal_y": overrides.get("focal_y", 0.5),
        "zoom": overrides.get("zoom", 1.0),
    }


def _update(service, page, panels, **overrides):
    return service.update(
        page.id,
        expected_revision=overrides.get("expected_revision", page.revision),
        title=overrides.get("title", page.title),
        format=overrides.get("format", page.format),
        background_color=overrides.get("background_color", "#FFFFFF"),
        gutter_px=overrides.get("gutter_px", 20),
        template_key=overrides.get("template_key", page.template_key),
        template_version=1,
        divider_values=overrides.get("divider_values", page.divider_values),
        panels=panels,
    )


def test_migration_enforces_page_panel_and_render_constraints(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO comic_page (title, format, width_px, height_px, template_key) "
            "VALUES ('bad', 'portrait', 1, 1, 'full')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO comic_page (title, format, width_px, height_px, template_key, divider_values_json) "
            "VALUES ('bad', 'portrait', 1200, 1800, 'three_rows', '[0.7,0.3]')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO comic_page (title, format, width_px, height_px, template_key, divider_values_json) "
            "VALUES ('too narrow', 'portrait', 1200, 1800, 'six_grid', '[0.4,0.45,0.5]')"
        )
    conn.rollback()

    page_id = conn.execute(
        "INSERT INTO comic_page (title, format, width_px, height_px, template_key) "
        "VALUES ('Page', 'portrait', 1200, 1800, 'full')"
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO page_render (page_id, page_revision, sha256, width, height, layout_json) "
            "VALUES (?, 1, ?, 1200, 1800, '{}')", (page_id, "G" * 64)
        )
    conn.rollback()


def test_page_crud_revision_and_candidate_attachment_rules(conn, storage, settings):
    service = PageService(conn)
    page = service.create(title="  Opening  ", format="portrait", template_key="two_columns")
    assert (page.title, page.width_px, page.height_px, page.divider_values) == (
        "Opening", 1200, 1800, [0.5]
    )
    accepted = _candidate(conn, storage)
    pending = _candidate(conn, storage, accepted=False)
    base = _candidate(conn, storage, base_stage=True)

    with pytest.raises(PageCandidateConflictError, match="accepted"):
        _update(service, page, [_panel(pending, 0)])
    with pytest.raises(PageCandidateConflictError, match="scene generation"):
        _update(service, page, [_panel(base, 0)])

    page = _update(service, page, [_panel(accepted, 0)])
    assert page.revision == 2
    conn.execute("UPDATE candidate SET review_status='rejected' WHERE id=?", (accepted,))
    conn.commit()
    page = _update(service, page, [_panel(accepted, 1, focal_x=0.2)])
    assert page.panels[0].slot_index == 1
    with pytest.raises(PageRevisionConflictError):
        _update(service, page, [], expected_revision=1)
    with pytest.raises(PageValidationError, match="only once"):
        _update(service, page, [_panel(accepted, 0), _panel(accepted, 1)])

    scene_id = conn.execute(
        "SELECT g.scene_id FROM candidate c JOIN generation g ON g.id=c.generation_id WHERE c.id=?",
        (accepted,),
    ).fetchone()[0]
    with pytest.raises(SceneDeleteConflictError):
        SceneService(conn, settings).delete(scene_id)
    service.delete(page.id)
    assert conn.execute("SELECT COUNT(*) FROM comic_page_panel").fetchone()[0] == 0


def test_page_create_attaches_candidate_atomically(conn, storage):
    service = PageService(conn)
    accepted = _candidate(conn, storage)

    page = service.create(
        title="Opening", format="portrait", template_key="feature_top",
        candidate_id=accepted,
    )
    assert [(panel.candidate_id, panel.slot_index) for panel in page.panels] == [
        (accepted, 0)
    ]

    pending = _candidate(conn, storage, accepted=False)
    with pytest.raises(PageCandidateConflictError, match="accepted"):
        service.create(
            title="Not created", format="portrait", template_key="full",
            candidate_id=pending,
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM comic_page WHERE title = 'Not created'"
    ).fetchone()[0] == 0


def test_render_is_deterministic_records_crop_and_rejects_incomplete(conn, storage):
    pages = PageService(conn)
    page = pages.create(title="Spread", format="portrait", template_key="two_columns")
    first = _candidate(conn, storage)
    second = _candidate(conn, storage, color=(20, 40, 60))
    page = _update(
        pages, page, [_panel(first, 0, focal_x=0.0, zoom=2.0), _panel(second, 1)],
        gutter_px=20,
    )
    renderer = PageRenderService(conn, storage)
    render = renderer.render(page.id, expected_revision=page.revision)
    repeated = renderer.render(page.id, expected_revision=page.revision)
    assert repeated.id == render.id
    assert (render.width, render.height) == (1200, 1800)
    assert [panel["target_rect"] for panel in render.layout["panels"]] == [
        [0, 0, 590, 1800], [610, 0, 1200, 1800]
    ]
    assert render.layout["panels"][0]["source_crop"][0] == 0.0
    data, metadata = storage.read(
        conn.execute("SELECT sha256 FROM page_render WHERE id=?", (render.id,)).fetchone()[0]
    )
    with Image.open(io.BytesIO(data)) as image:
        assert (image.size, image.mode, metadata["format"]) == ((1200, 1800), "RGB", "PNG")

    incomplete = pages.create(title="Missing", format="square", template_key="two_rows")
    incomplete = _update(pages, incomplete, [_panel(first, 0)])
    with pytest.raises(PageIncompleteError):
        renderer.render(incomplete.id, expected_revision=incomplete.revision)


def test_page_api_content_download_and_scene_conflict(page_api):
    candidate_conn = page_api.conn()
    try:
        candidate_id = _candidate(candidate_conn, page_api.storage)
    finally:
        candidate_conn.close()
    created = page_api.client.post(
        "/api/v1/pages", json={"title": "API page", "format": "square", "template_key": "full"}
    )
    assert created.status_code == 201
    page = created.json()
    updated = page_api.client.put(
        f"/api/v1/pages/{page['id']}",
        json={
            "expected_revision": page["revision"], "title": page["title"],
            "format": "square", "background_color": "#102030", "gutter_px": 0,
            "template_key": "full", "template_version": 1,
            "divider_values": [], "panels": [_panel(candidate_id, 0)],
        },
    )
    assert updated.status_code == 200, updated.text
    rendered = page_api.client.post(
        f"/api/v1/pages/{page['id']}/render",
        json={"expected_revision": updated.json()["revision"]},
    )
    assert rendered.status_code == 201, rendered.text
    body = rendered.json()
    assert "sha256" not in json.dumps(body)
    content = page_api.client.get(body["content_url"])
    download = page_api.client.get(body["download_url"])
    assert content.status_code == 200 and content.headers["content-type"] == "image/png"
    assert download.headers["content-disposition"].startswith("attachment; filename=")
    assert len(page_api.client.get(f"/api/v1/pages/{page['id']}/renders").json()) == 1
    stale = page_api.client.put(
        f"/api/v1/pages/{page['id']}",
        json={
            "expected_revision": page["revision"], "title": page["title"],
            "format": "square", "background_color": "#102030", "gutter_px": 0,
            "template_key": "full", "template_version": 1,
            "divider_values": [], "panels": [_panel(candidate_id, 0)],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["type"] == "PageRevisionConflictError"

    candidate_conn = page_api.conn()
    try:
        scene_id = candidate_conn.execute(
            "SELECT g.scene_id FROM candidate c JOIN generation g ON g.id=c.generation_id "
            "WHERE c.id=?", (candidate_id,),
        ).fetchone()[0]
    finally:
        candidate_conn.close()
    blocked = page_api.client.delete(f"/api/v1/scenes/{scene_id}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["type"] == "SceneDeleteConflictError"


def test_maintenance_tracks_page_render_hash(conn, storage):
    from app.maintenance import run_check

    page_id = conn.execute(
        "INSERT INTO comic_page (title, format, width_px, height_px, template_key) "
        "VALUES ('Page', 'square', 1600, 1600, 'full')"
    ).lastrowid
    ghost = "e" * 64
    conn.execute(
        "INSERT INTO page_render (page_id, page_revision, sha256, width, height, layout_json) "
        "VALUES (?, 1, ?, 1600, 1600, '{}')", (page_id, ghost)
    )
    conn.commit()
    assert run_check(conn, storage).dangling_db_hashes == (ghost,)
