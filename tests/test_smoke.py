"""Smoke test: the home route responds. No network access."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import FRONTEND_DIST_DIR, app, settings


def test_home_route_responds():
    """"/" always responds; its content depends on whether the React frontend
    has been built (frontend/dist/, see app/main.py + README "Frontend"
    section). Both branches are exercised so this test is correct whether or
    not `npm run build` has been run locally."""
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/")
    assert resp.status_code == 200
    if (FRONTEND_DIST_DIR / "index.html").is_file():
        # Primary UI: the built React app's shell.
        assert '<div id="root">' in resp.text
    else:
        # No build present: a short notice, not a second interface.
        assert "LoreCraft3000" in resp.text
        assert "npm run build" in resp.text


def test_liveness_route():
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_route_reports_readiness():
    """/health returns 200 with a per-subsystem breakdown once initialized."""
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert set(body["checks"]) == {"database", "migrations", "storage"}
        assert all(check["status"] == "ok" for check in body["checks"].values())


def test_lifespan_initializes_db():
    """The lifespan creates the SQLite DB file on startup."""
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        # Trigger the lifespan by making a request.
        client.get("/health")
        assert settings.db_path.exists()
