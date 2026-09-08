"""Backend contracts for flexible panel aggregates and renders."""

from __future__ import annotations

import io
import json
import math
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
from app.services.panel_rendering import PanelRenderService
from app.services.panels import (
    PanelCandidateConflictError,
    PanelIncompleteError,
    PanelRevisionConflictError,
    PanelService,
    PanelValidationError,
)
from app.services.scenes import SceneDeleteConflictError, SceneService
from app.storage import ImageStorage


@dataclass
class PanelApi:
    client: TestClient
    db_path: object
    storage: ImageStorage

    def conn(self):
        return connect(self.db_path)


@pytest.fixture
def panel_api(tmp_path, monkeypatch):
    db_path = tmp_path / "panels-api.db"
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
            yield PanelApi(client, db_path, storage)
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


def _solid_png(color) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (400, 200), color).save(output, format="PNG")
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
    stored = storage.store(_gradient_png() if color is None else _solid_png(color))
    candidate_id = conn.execute(
        "INSERT INTO candidate (generation_id, sha256, review_status) VALUES (?, ?, ?)",
        (generation_id, stored.sha256, "accepted" if accepted else "pending"),
    ).lastrowid
    conn.commit()
    return int(candidate_id)


def _slot(candidate_id, slot_index, rect=(0.0, 0.0, 1.0, 1.0), **overrides):
    return {
        "candidate_id": candidate_id,
        "slot_index": slot_index,
        "x0": rect[0],
        "y0": rect[1],
        "x1": rect[2],
        "y1": rect[3],
        "focal_x": overrides.get("focal_x", 0.5),
        "focal_y": overrides.get("focal_y", 0.5),
        "zoom": overrides.get("zoom", 1.0),
    }


def _two_columns(first=None, second=None):
    return [
        _slot(first, 0, (0.0, 0.0, 0.5, 1.0)),
        _slot(second, 1, (0.5, 0.0, 1.0, 1.0)),
    ]


def _update(service, panel, slots, **overrides):
    return service.update(
        panel.id,
        expected_revision=overrides.get("expected_revision", panel.revision),
        title=overrides.get("title", panel.title),
        format=overrides.get("format", panel.format),
        background_color=overrides.get("background_color", "#FFFFFF"),
        gutter_px=overrides.get("gutter_px", 20),
        frame_px=overrides.get("frame_px", 0),
        slots=slots,
    )


def test_migration_enforces_panel_and_slot_constraints(conn, storage):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO panel (title, format, width_px, height_px, frame_px) "
            "VALUES ('bad', 'portrait', 1200, 1800, 81)"
        )
    conn.rollback()

    panel_id = conn.execute(
        "INSERT INTO panel (title, format, width_px, height_px) "
        "VALUES ('Panel', 'portrait', 1200, 1800)"
    ).lastrowid
    conn.commit()
    for coordinates in [(-0.1, 0, 1, 1), (0, 0, 0.03, 1), (0, 0, 1, 0.03)]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO panel_slot (panel_id, slot_index, x0, y0, x1, y1) "
                "VALUES (?, 0, ?, ?, ?, ?)", (panel_id, *coordinates)
            )
        conn.rollback()

    candidate_id = _candidate(conn, storage)
    conn.execute(
        "INSERT INTO panel_slot (panel_id, candidate_id, slot_index, x0, y0, x1, y1) "
        "VALUES (?, ?, 0, 0, 0, 0.5, 1)", (panel_id, candidate_id)
    )
    conn.execute(
        "INSERT INTO panel_slot (panel_id, candidate_id, slot_index, x0, y0, x1, y1) "
        "VALUES (?, ?, 1, 0.5, 0, 1, 1)", (panel_id, candidate_id)
    )
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM panel_slot WHERE candidate_id=?", (candidate_id,)
    ).fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO panel_render (panel_id, panel_revision, sha256, width, height, layout_json) "
            "VALUES (?, 1, ?, 1200, 1800, '{}')", (panel_id, "G" * 64)
        )
    conn.rollback()


def test_create_builds_equal_grid_and_attaches_candidate_atomically(conn, storage):
    service = PanelService(conn)
    accepted = _candidate(conn, storage)
    panel = service.create(
        title="  Opening  ", format="portrait", rows=2, columns=3, candidate_id=accepted
    )
    assert (panel.title, panel.width_px, panel.height_px, panel.frame_px) == (
        "Opening", 1200, 1800, 0
    )
    assert [(slot.slot_index, slot.candidate_id) for slot in panel.slots] == [
        (0, accepted), (1, None), (2, None), (3, None), (4, None), (5, None)
    ]
    assert [(slot.x0, slot.y0, slot.x1, slot.y1) for slot in panel.slots] == [
        (0.0, 0.0, 1 / 3, 0.5), (1 / 3, 0.0, 2 / 3, 0.5),
        (2 / 3, 0.0, 1.0, 0.5), (0.0, 0.5, 1 / 3, 1.0),
        (1 / 3, 0.5, 2 / 3, 1.0), (2 / 3, 0.5, 1.0, 1.0),
    ]

    pending = _candidate(conn, storage, accepted=False)
    with pytest.raises(PanelCandidateConflictError, match="accepted"):
        service.create(title="Not created", format="square", rows=2, candidate_id=pending)
    assert conn.execute(
        "SELECT COUNT(*) FROM panel WHERE title='Not created'"
    ).fetchone()[0] == 0

    for rows, columns in [(0, 1), (1, 9), (True, 1)]:
        with pytest.raises(PanelValidationError):
            service.create(title="Bad", format="square", rows=rows, columns=columns)


@pytest.mark.parametrize(
    ("slots", "message"),
    [
        ([_slot(None, 0, (0, 0, 0.6, 1)), _slot(None, 1, (0.5, 0, 1, 1))], "overlap"),
        ([_slot(None, 0, (0, 0, 0.4, 1)), _slot(None, 1, (0.5, 0, 1, 1))], "cover"),
        ([_slot(None, 1)], "contiguous"),
        ([_slot(None, 0, (0, 0, math.inf, 1))], "finite"),
    ],
)
def test_update_rejects_invalid_geometry(conn, slots, message):
    service = PanelService(conn)
    panel = service.create(title="Geometry", format="square")
    with pytest.raises(PanelValidationError, match=message):
        _update(service, panel, slots)


def test_update_rejects_frame_and_gutter_that_collapse_a_slot(conn):
    service = PanelService(conn)
    panel = service.create(title="Narrow", format="portrait", columns=3)
    narrow_middle = [
        _slot(None, 0, (0, 0, 0.48, 1)),
        _slot(None, 1, (0.48, 0, 0.52, 1)),
        _slot(None, 2, (0.52, 0, 1, 1)),
    ]
    with pytest.raises(PanelValidationError, match="without usable space"):
        _update(service, panel, narrow_middle, gutter_px=80, frame_px=80)


def test_update_revision_and_candidate_rules(conn, storage):
    service = PanelService(conn)
    panel = service.create(title="Rules", format="square", columns=2)
    accepted = _candidate(conn, storage)
    pending = _candidate(conn, storage, accepted=False)
    base = _candidate(conn, storage, base_stage=True)

    with pytest.raises(PanelCandidateConflictError, match="accepted"):
        _update(service, panel, _two_columns(pending))
    with pytest.raises(PanelCandidateConflictError, match="scene generation"):
        _update(service, panel, _two_columns(base))

    panel = _update(service, panel, _two_columns(accepted, accepted), frame_px=12)
    assert panel.revision == 2
    assert panel.frame_px == 12
    assert [slot.candidate_id for slot in panel.slots] == [accepted, accepted]

    conn.execute("UPDATE candidate SET review_status='rejected' WHERE id=?", (accepted,))
    conn.commit()
    panel = _update(service, panel, _two_columns(accepted, accepted))
    assert panel.revision == 3
    with pytest.raises(PanelRevisionConflictError):
        _update(service, panel, _two_columns(), expected_revision=1)


def test_render_uses_geometry_frame_and_gutter_and_requires_complete_slots(conn, storage):
    panels = PanelService(conn)
    first = _candidate(conn, storage)
    second = _candidate(conn, storage, color=(20, 40, 60))
    panel = panels.create(title="Spread", format="portrait", columns=2)
    slots = _two_columns(first, second)
    slots[0]["focal_x"] = 0.0
    slots[0]["zoom"] = 2.0
    panel = _update(panels, panel, slots, gutter_px=20, frame_px=20)

    renderer = PanelRenderService(conn, storage)
    render = renderer.render(panel.id, expected_revision=panel.revision)
    assert renderer.render(panel.id, expected_revision=panel.revision).id == render.id
    assert [slot["target_rect"] for slot in render.layout["slots"]] == [
        [20, 20, 590, 1780], [610, 20, 1180, 1780]
    ]
    assert render.layout["frame_px"] == 20
    assert render.layout["gutter_px"] == 20
    assert [render.layout["slots"][0][key] for key in ("x0", "y0", "x1", "y1")] == [
        0.0, 0.0, 0.5, 1.0
    ]
    assert render.layout["slots"][0]["source_crop"][0] == 0.0

    data, metadata = storage.read(
        conn.execute("SELECT sha256 FROM panel_render WHERE id=?", (render.id,)).fetchone()[0]
    )
    with Image.open(io.BytesIO(data)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert (image.size, image.mode, metadata["format"]) == ((1200, 1800), "RGB", "PNG")

    incomplete = panels.create(title="Missing", format="square", columns=2, candidate_id=first)
    with pytest.raises(PanelIncompleteError):
        renderer.render(incomplete.id, expected_revision=incomplete.revision)


def test_panel_api_contract_and_scene_conflict(panel_api):
    candidate_conn = panel_api.conn()
    try:
        candidate_id = _candidate(candidate_conn, panel_api.storage)
        scene_id = candidate_conn.execute(
            "SELECT g.scene_id FROM candidate c JOIN generation g ON g.id=c.generation_id "
            "WHERE c.id=?", (candidate_id,),
        ).fetchone()[0]
    finally:
        candidate_conn.close()

    created = panel_api.client.post(
        "/api/v1/panels",
        json={"title": "API panel", "format": "square", "rows": 1, "columns": 2},
    )
    assert created.status_code == 201
    panel = created.json()
    assert len(panel["slots"]) == 2
    assert panel["slots"][0]["candidate_id"] is None
    assert panel["slots"][0]["content_url"] is None
    assert {"frame_px", "slots"} <= panel.keys()
    assert not ({"template_key", "template_version", "divider_values"} & panel.keys())

    # Empty slots do not create a scene reference.
    assert panel_api.client.delete(f"/api/v1/scenes/{scene_id}").status_code == 204

    candidate_conn = panel_api.conn()
    try:
        candidate_id = _candidate(candidate_conn, panel_api.storage)
        scene_id = candidate_conn.execute(
            "SELECT g.scene_id FROM candidate c JOIN generation g ON g.id=c.generation_id "
            "WHERE c.id=?", (candidate_id,),
        ).fetchone()[0]
    finally:
        candidate_conn.close()

    payload = {
        "expected_revision": panel["revision"], "title": panel["title"],
        "format": "square", "background_color": "#102030", "gutter_px": 0,
        "frame_px": 8, "slots": _two_columns(candidate_id, candidate_id),
    }
    updated = panel_api.client.put(f"/api/v1/panels/{panel['id']}", json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["slots"][0]["content_url"] == (
        f"/api/v1/candidates/{candidate_id}/content"
    )
    rendered = panel_api.client.post(
        f"/api/v1/panels/{panel['id']}/render",
        json={"expected_revision": updated.json()["revision"]},
    )
    assert rendered.status_code == 201, rendered.text
    body = rendered.json()
    assert "sha256" not in json.dumps(body)
    assert panel_api.client.get(body["content_url"]).headers["content-type"] == "image/png"
    download = panel_api.client.get(body["download_url"])
    assert download.headers["content-disposition"] == (
        f'attachment; filename="panel-{panel["id"]}-r{updated.json()["revision"]}.png"'
    )
    assert panel_api.client.delete(f"/api/v1/scenes/{scene_id}").status_code == 409

    stale = panel_api.client.put(f"/api/v1/panels/{panel['id']}", json=payload)
    assert stale.status_code == 409
    assert stale.json()["detail"]["type"] == "PanelRevisionConflictError"


def test_maintenance_tracks_panel_render_hash(conn, storage):
    from app.maintenance import run_check

    panel_id = conn.execute(
        "INSERT INTO panel (title, format, width_px, height_px) "
        "VALUES ('Panel', 'square', 1600, 1600)"
    ).lastrowid
    ghost = "e" * 64
    conn.execute(
        "INSERT INTO panel_render (panel_id, panel_revision, sha256, width, height, layout_json) "
        "VALUES (?, 1, ?, 1600, 1600, '{}')", (panel_id, ghost)
    )
    conn.commit()
    assert run_check(conn, storage).dangling_db_hashes == (ghost,)
