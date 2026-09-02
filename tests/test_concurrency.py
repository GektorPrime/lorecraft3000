"""Concurrency and crash-recovery tests at the database boundary.

Phase 1 guarantees "one pending paid generation per panel" and stale-pending
recovery. Other suites verify those guarantees through single-connection
service calls. These tests exercise the same guarantees under real concurrent
execution against one on-disk SQLite database (WAL + busy timeout), where the
protection actually has to hold: the unique partial index and BEGIN IMMEDIATE
reservation, not application-level checks alone.
"""

from __future__ import annotations

import json
import threading
import time

from app.config import Settings
from app.db import connect
from app.providers.base import ProviderResult
from app.services.characters import CharacterService
from app.services.costs import CostLedger, GenerationPendingError
from app.services.generation import GenerationError, GenerationService
from app.services.ref_sets import RefSetService
from app.services.styles import StyleService
from tests.conftest import make_png_bytes


class _BlockingProvider:
    """Provider that blocks inside generate() until released.

    Lets a test hold one generation "in flight" (pending, provider call
    started) while a second concurrent request tries to reserve the same panel.
    """

    def __init__(self, release: threading.Event, entered: threading.Event) -> None:
        self._release = release
        self._entered = entered
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request):
        with self._lock:
            self.calls += 1
        self._entered.set()
        self._release.wait(timeout=5)
        return ProviderResult(make_png_bytes((20, 40, 80)), "interaction", {})


def _settings(tmp_path) -> Settings:
    return Settings(
        daily_spend_cap_usd=3.0,
        db_path=tmp_path / "db.sqlite",
        store_root=tmp_path / "store",
    )


def _seed_scene(settings: Settings) -> int:
    """Create one character with canon and a single-cast scene. Returns scene id."""
    conn = _connect(settings)
    try:
        from app.migrate import run_migrations

        conn.close()
        run_migrations(settings.db_path)
        conn = _connect(settings)
        storage_dir = settings.store_root
        storage_dir.mkdir(parents=True, exist_ok=True)
        from app.storage import ImageStorage

        storage = ImageStorage(storage_dir)
        character = CharacterService(conn).create(
            name="ELIAS",
            slug="elias",
            lore_md="SECRET LORE",
            visual_contract="Distinctive face of ELIAS.",
            negative_traits="identity blending",
        )
        refs = RefSetService(conn, storage)
        ref_set = refs.create_draft(character.id)
        refs.add_image(
            ref_set.id, make_png_bytes((100, 20, 20)), "face_front", source_name="e.png"
        )
        refs.promote(ref_set.id)
        style = StyleService(conn).get_default()
        scene_id = conn.execute(
            """
            INSERT INTO scene
                (beat_text, camera, framing, mood, aspect_ratio, cast_json, style_id)
            VALUES (?, 'eye level', 'medium', 'tense', '3:2', ?, ?)
            """,
            ("A beat.", json.dumps([{"character_id": character.id}]), style.id),
        ).lastrowid
        conn.commit()
        return int(scene_id)
    finally:
        conn.close()


def _connect(settings: Settings):
    return connect(
        settings.db_path,
        journal_mode=settings.sqlite_journal_mode,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        synchronous=settings.sqlite_synchronous,
    )


def test_concurrent_generation_yields_one_provider_call(tmp_path):
    """Two overlapping generation requests for one panel: exactly one paid call.

    The first request holds a pending generation open inside the provider; the
    second must be rejected by the one-pending-per-panel guarantee rather than
    starting a second provider call or a second reservation.
    """
    settings = _settings(tmp_path)
    scene_id = _seed_scene(settings)

    release = threading.Event()
    entered = threading.Event()
    provider = _BlockingProvider(release, entered)

    from app.storage import ImageStorage

    first_result: dict = {}
    second_error: list[Exception] = []

    def first() -> None:
        conn = _connect(settings)
        try:
            service = GenerationService(
                conn, ImageStorage(settings.store_root), settings, provider
            )
            first_result["outcome"] = service.generate(scene_id)
        finally:
            conn.close()

    def second() -> None:
        # Wait until the first request is inside the provider (pending row
        # committed), then attempt to reserve the same panel.
        entered.wait(timeout=5)
        conn = _connect(settings)
        try:
            service = GenerationService(
                conn, ImageStorage(settings.store_root), settings, provider
            )
            try:
                service.generate(scene_id)
            except Exception as exc:  # noqa: BLE001 - captured for assertion
                second_error.append(exc)
        finally:
            conn.close()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    # Give the second thread time to hit the pending guard, then release the
    # first so it can finish.
    time.sleep(0.2)
    release.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    # Exactly one provider call was made.
    assert provider.calls == 1
    # The second request was rejected for a pending generation, not charged.
    assert second_error, "second concurrent request should have been rejected"
    assert isinstance(second_error[0], (GenerationPendingError, GenerationError))

    conn = _connect(settings)
    try:
        rows = conn.execute(
            "SELECT state FROM generation WHERE scene_id = ?", (scene_id,)
        ).fetchall()
        states = sorted(row["state"] for row in rows)
        # One succeeded generation; no second pending/succeeded row was created.
        assert states == ["succeeded"], states
    finally:
        conn.close()


def test_startup_recovers_stale_pending_generation(tmp_path):
    """A generation left pending by a crash is recovered by the ledger.

    Simulates a process that reserved a generation and then died before the
    provider returned: the row stays pending with its reservation. Recovery
    (which runs at startup in app.main lifespan) must fail the stale attempt,
    releasing the reservation and unlocking the panel.
    """
    settings = _settings(tmp_path)
    scene_id = _seed_scene(settings)

    conn = _connect(settings)
    try:
        ledger = CostLedger(conn, settings)
        reservation = ledger.reserve(
            scene_id=scene_id,
            model=settings.default_model,
            image_size=settings.default_image_size,
            prompt_hash="crash",
            request_json={"aspect_ratio": "3:2"},
        )
        assert reservation.created
        # Backdate the pending row beyond the stale threshold to mimic a crash
        # that left it in flight.
        conn.execute(
            "UPDATE generation SET created_at = datetime('now', ?) WHERE id = ?",
            (f"-{settings.pending_stale_seconds + 60} seconds", reservation.generation_id),
        )
        conn.commit()
    finally:
        conn.close()

    # A fresh process performs startup recovery.
    conn = _connect(settings)
    try:
        recovered = CostLedger(conn, settings).recover_stale_pending()
        assert recovered == 1
        row = conn.execute(
            "SELECT state FROM generation WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        assert row["state"] == "failed"
        # Panel is unlocked: a new reservation succeeds.
        new_reservation = CostLedger(conn, settings).reserve(
            scene_id=scene_id,
            model=settings.default_model,
            image_size=settings.default_image_size,
            prompt_hash="after-recovery",
            request_json={"aspect_ratio": "3:2"},
        )
        assert new_reservation.created
        conn.rollback()
    finally:
        conn.close()
