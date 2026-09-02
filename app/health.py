"""Readiness reporting for the /health endpoint.

Liveness ("the process is up") is trivial: if the endpoint answers at all, the
process is running. Readiness ("the app can actually serve requests") is not:
it depends on the database being reachable, all migrations being applied, and
the image store being present and writable.

This module performs those three checks cheaply and read-only. It never runs
the full storage consistency scan (that is `app.maintenance`), never mutates
domain data, and never raises out of `readiness_report`: every check is
individually guarded so one failing subsystem is reported, not propagated as a
500. The health endpoint turns a not-ready report into a 503.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.db import connect
from app.migrate import MIGRATIONS, applied_versions

# Subdirectory used only for the storage write probe. Kept separate from the
# content-addressed layout (two-hex-character shards) so a probe file can never
# be mistaken for a stored object or its sidecar.
_HEALTH_PROBE_DIR = ".health"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one readiness check."""

    ok: bool
    detail: str = ""

    def as_dict(self) -> dict:
        result: dict = {"status": "ok" if self.ok else "error"}
        if self.detail:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate readiness across database, migrations, and storage."""

    checks: dict[str, CheckResult] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks.values())

    def as_dict(self) -> dict:
        return {
            "status": "ok" if self.ok else "not_ready",
            "checks": {name: check.as_dict() for name, check in self.checks.items()},
        }


def _check_database(settings: Settings) -> CheckResult:
    try:
        conn = connect(
            settings.db_path,
            journal_mode=settings.sqlite_journal_mode,
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
            synchronous=settings.sqlite_synchronous,
        )
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001 - report, never propagate
        return CheckResult(ok=False, detail=f"database unreachable: {exc}")


def _check_migrations(settings: Settings) -> CheckResult:
    try:
        conn = connect(
            settings.db_path,
            journal_mode=settings.sqlite_journal_mode,
            busy_timeout_ms=settings.sqlite_busy_timeout_ms,
            synchronous=settings.sqlite_synchronous,
        )
        try:
            applied = applied_versions(conn)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - report, never propagate
        return CheckResult(ok=False, detail=f"cannot read migration state: {exc}")

    expected = {name.rsplit(".", 1)[-1] for name in MIGRATIONS}
    missing = sorted(expected - applied)
    if missing:
        return CheckResult(
            ok=False, detail="pending migrations: " + ", ".join(missing)
        )
    unknown = sorted(applied - expected)
    if unknown:
        return CheckResult(
            ok=False,
            detail="database has unknown migrations: " + ", ".join(unknown),
        )
    return CheckResult(ok=True)


def _check_storage(settings: Settings) -> CheckResult:
    root = Path(settings.store_root)
    try:
        if not root.exists():
            return CheckResult(ok=False, detail=f"store root missing: {root}")
        probe_dir = root / _HEALTH_PROBE_DIR
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = probe_dir / f"probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return CheckResult(ok=True)
    except Exception as exc:  # noqa: BLE001 - report, never propagate
        return CheckResult(ok=False, detail=f"store root not writable: {exc}")


def readiness_report(settings: Settings) -> ReadinessReport:
    """Check database, migrations, and storage readiness.

    Each check is independent and guarded; a failure in one is reported in the
    returned report rather than raised. The caller (the /health route) maps a
    not-ready report to a 503 response.
    """
    return ReadinessReport(
        checks={
            "database": _check_database(settings),
            "migrations": _check_migrations(settings),
            "storage": _check_storage(settings),
        }
    )
