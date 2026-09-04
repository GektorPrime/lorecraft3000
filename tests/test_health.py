"""Readiness health-check tests.

Verify that /health reflects real database, migration, and storage state:
200 when ready, 503 with the failing check named otherwise, and that the
report never raises out of the endpoint.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.db import connect
from app.health import readiness_report
from app.main import app
from app.migrate import run_migrations


@pytest.fixture
def ready_settings(tmp_path) -> Settings:
    """A fully-initialized database and store: all readiness checks pass."""
    db_path = tmp_path / "data" / "lorecraft.db"
    store_root = tmp_path / "store"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    run_migrations(db_path)
    return Settings(db_path=db_path, store_root=store_root)


def test_readiness_all_ok(ready_settings):
    report = readiness_report(ready_settings)
    assert report.ok
    assert set(report.checks) == {"database", "migrations", "storage"}
    assert all(check.ok for check in report.checks.values())


def test_pending_migration_is_not_ready(ready_settings):
    # A fresh, un-migrated database has no applied versions.
    unmigrated = ready_settings.db_path.parent / "empty.db"
    connect(unmigrated).close()
    settings = dataclasses.replace(ready_settings, db_path=unmigrated)
    report = readiness_report(settings)
    assert not report.ok
    assert not report.checks["migrations"].ok
    assert "pending migrations" in report.checks["migrations"].detail
    # Database itself is reachable; only migrations are behind.
    assert report.checks["database"].ok


def test_unknown_migration_is_not_ready(ready_settings):
    conn = connect(ready_settings.db_path)
    conn.execute(
        "INSERT INTO schema_migrations (version) VALUES ('999_from_the_future')"
    )
    conn.commit()
    conn.close()
    report = readiness_report(ready_settings)
    assert not report.ok
    assert "unknown migrations" in report.checks["migrations"].detail


def test_missing_store_root_is_not_ready(ready_settings):
    settings = dataclasses.replace(
        ready_settings, store_root=ready_settings.store_root / "does-not-exist"
    )
    report = readiness_report(settings)
    assert not report.ok
    assert not report.checks["storage"].ok
    assert "missing" in report.checks["storage"].detail


def test_read_only_store_root_is_not_ready(ready_settings):
    import os
    import stat

    ready_settings.store_root.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        report = readiness_report(ready_settings)
        # Root cannot write regardless of mode; skip if the probe still succeeds.
        if report.checks["storage"].ok and os.geteuid() == 0:
            pytest.skip("running as root; write permission cannot be revoked")
        assert not report.checks["storage"].ok
    finally:
        ready_settings.store_root.chmod(0o755)


def test_unreachable_database_is_not_ready(ready_settings):
    # Point at a path that cannot be opened as a database (a directory).
    settings = dataclasses.replace(
        ready_settings, db_path=ready_settings.store_root
    )
    report = readiness_report(settings)
    assert not report.ok
    assert not report.checks["database"].ok


def test_report_never_raises_on_all_failures(tmp_path):
    """Every subsystem broken at once still yields a report, not an exception."""
    settings = Settings(
        db_path=tmp_path / "store-as-db",  # a directory masquerading as a DB
        store_root=tmp_path / "missing-store",
    )
    (tmp_path / "store-as-db").mkdir()
    report = readiness_report(settings)
    assert not report.ok
    # A report object is returned with all three named checks present.
    assert set(report.checks) == {"database", "migrations", "storage"}


def test_health_endpoint_ok_returns_200(ready_settings, monkeypatch):
    monkeypatch.setattr(main_module, "settings", ready_settings)
    client = TestClient(app, base_url="http://127.0.0.1")
    with client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_liveness_endpoint_is_trivial():
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
