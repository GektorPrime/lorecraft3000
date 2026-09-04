"""Smoke test: the home route responds. No network access."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.main import app


def test_home_route_serves_built_frontend(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<div id="root">' in resp.text


def test_home_route_explains_missing_frontend_build(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "LoreCraft3000" in resp.text
    assert "npm run build" in resp.text


def test_liveness_route():
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_route_reports_readiness(tmp_path, monkeypatch):
    """/health returns 200 with a per-subsystem breakdown once initialized."""
    settings = Settings(db_path=tmp_path / "test.db", store_root=tmp_path / "store")
    monkeypatch.setattr(main_module, "settings", settings)
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert set(body["checks"]) == {"database", "migrations", "storage"}
        assert all(check["status"] == "ok" for check in body["checks"].values())


def test_lifespan_initializes_db(tmp_path, monkeypatch):
    """The lifespan creates the SQLite DB file on startup."""
    settings = Settings(db_path=tmp_path / "test.db", store_root=tmp_path / "store")
    monkeypatch.setattr(main_module, "settings", settings)
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        # Trigger the lifespan by making a request.
        client.get("/health")
        assert settings.db_path.exists()
