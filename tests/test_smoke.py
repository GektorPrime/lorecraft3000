"""Smoke test: the home route responds. No network access."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app, settings


def test_home_route_responds():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "LoreCraft3000" in resp.text


def test_health_route():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_lifespan_initializes_db():
    """The lifespan creates the SQLite DB file on startup."""
    client = TestClient(app)
    with client:
        # Trigger the lifespan by making a request.
        client.get("/health")
        assert settings.db_path.exists()
