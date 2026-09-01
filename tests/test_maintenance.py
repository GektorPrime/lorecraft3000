"""Tests for the storage consistency scan and repair command."""

from __future__ import annotations

import json

import pytest

from app.maintenance import run_check, run_repair
from app.storage import ImageStorage
from tests.conftest import make_png_bytes


def _store_image(storage: ImageStorage, color=(200, 30, 30)) -> str:
    return storage.store(make_png_bytes(color)).sha256


def _sidecar(storage: ImageStorage, sha256: str):
    return storage.root / sha256[:2] / f"{sha256}.json"


def _image(storage: ImageStorage, sha256: str):
    return storage.find_image(sha256)


def _insert_dangling_candidate(conn, sha256: str) -> None:
    conn.execute("INSERT INTO generation (model) VALUES ('test')")
    generation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO candidate (generation_id, sha256) VALUES (?, ?)",
        (generation_id, sha256),
    )
    conn.commit()


def test_clean_store_reports_no_issues(conn, storage, png_bytes):
    storage.store(png_bytes, source_name="ref.png")
    report = run_check(conn, storage)
    assert report.issue_count == 0
    assert (report.missing_sidecar, report.malformed_sidecar, report.hash_mismatch) == (
        (),
        (),
        (),
    )
    assert (report.sidecar_without_image, report.dangling_db_hashes) == ((), ())
    assert report.stale_temp_files == ()


def test_missing_sidecar_is_detected(conn, storage, png_bytes):
    sha = _store_image(storage)
    _sidecar(storage, sha).unlink()
    report = run_check(conn, storage)
    assert report.missing_sidecar == (sha,)
    assert report.issue_count == 1


def test_malformed_sidecar_jsons_are_detected(conn, storage, png_bytes):
    sha = _store_image(storage)
    _sidecar(storage, sha).write_text("{not json", encoding="utf-8")
    report = run_check(conn, storage)
    assert report.malformed_sidecar == (sha,)

    # Extension mismatch with parseable JSON is also malformed.
    sha2 = _store_image(storage, color=(30, 30, 200))
    existing = json.loads(_sidecar(storage, sha2).read_text())
    existing["extension"] = "gif"
    _sidecar(storage, sha2).write_text(
        json.dumps(existing, sort_keys=True), encoding="utf-8"
    )
    report = run_check(conn, storage)
    assert sha2 in report.malformed_sidecar


def test_hash_mismatch_is_detected(conn, storage, png_bytes):
    sha = _store_image(storage)
    _image(storage, sha).write_bytes(b"corrupted bytes")
    report = run_check(conn, storage)
    assert report.hash_mismatch == (sha,)
    assert sha not in report.malformed_sidecar
    assert sha not in report.missing_sidecar


def test_sidecar_without_image_is_detected(conn, storage, png_bytes):
    sha = _store_image(storage)
    _image(storage, sha).unlink()
    report = run_check(conn, storage)
    assert report.sidecar_without_image == (sha,)


def test_dangling_db_hash_is_detected(conn, storage):
    ghost = "d" * 64
    _insert_dangling_candidate(conn, ghost)
    report = run_check(conn, storage)
    assert report.dangling_db_hashes == (ghost,)


def test_stale_temp_files_are_detected(conn, storage):
    prefix = storage.root / "ab"
    prefix.mkdir(parents=True)
    stale = prefix / ".tmp-garbage"
    stale.touch()
    report = run_check(conn, storage)
    assert report.stale_temp_files == (str(stale),)


def test_repair_dry_run_changes_nothing_and_plan_reports_sidecar(conn, storage, png_bytes):
    sha = _store_image(storage)
    _sidecar(storage, sha).unlink()
    report = run_repair(conn, storage, apply=False)
    assert report.sidecars_rebuilt == (sha,)
    assert not _sidecar(storage, sha).exists()


def test_repair_rebuilds_missing_sidecar(conn, storage, png_bytes):
    sha = _store_image(storage)
    _sidecar(storage, sha).unlink()
    report = run_repair(conn, storage, apply=True)
    assert report.sidecars_rebuilt == (sha,)
    sidecar = json.loads(_sidecar(storage, sha).read_text())
    assert sidecar["sha256"] == sha
    assert sidecar["extension"] == "png"
    assert sidecar["format"] == "PNG"
    assert storage.is_complete(sha)
    assert run_check(conn, storage).issue_count == 0


def test_repair_rebuilds_malformed_sidecar_preserving_source_name(conn, storage, png_bytes):
    sha = storage.store(png_bytes, source_name="asset.png").sha256
    sidecar_path = _sidecar(storage, sha)
    existing = json.loads(sidecar_path.read_text())
    existing["extension"] = "webp"
    sidecar_path.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")
    report = run_repair(conn, storage, apply=True)
    assert sha in report.sidecars_rebuilt
    rebuilt = json.loads(sidecar_path.read_text())
    assert rebuilt["extension"] == "png"
    assert rebuilt["source_name"] == "asset.png"
    assert storage.is_complete(sha)


def test_repair_rebuilds_provenance_from_database(conn, storage, png_bytes):
    sha = _store_image(storage)
    conn.execute(
        "INSERT INTO generation (model) VALUES ('test')"
    )
    generation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO image_provenance (sha256, generation_id, prompt_hash, "
        "cost_cents, price_table_version, input_images) VALUES (?, ?, ?, ?, ?, ?)",
        (sha, generation_id, "abc123", 7, "2026-08-31.1", '["ref-1"]'),
    )
    conn.commit()

    _sidecar(storage, sha).unlink()
    report = run_repair(conn, storage, apply=True)
    assert sha in report.provenance_rebuilt_for
    rebuilt = json.loads(_sidecar(storage, sha).read_text())
    assert rebuilt["provenance"] == [
        {
            "generation_id": generation_id,
            "interaction_id": None,
            "prompt_hash": "abc123",
            "cost_cents": 7,
            "price_table_version": "2026-08-31.1",
            "input_images": ["ref-1"],
            "created_at": rebuilt["provenance"][0]["created_at"],
        }
    ]


def test_repair_declines_hash_mismatch(conn, storage, png_bytes):
    sha = _store_image(storage)
    _image(storage, sha).write_bytes(b"corrupted bytes")
    report = run_repair(conn, storage, apply=True)
    assert any(sha in message for message in report.unfixable)
    assert report.sidecars_rebuilt == ()
    assert run_check(conn, storage).hash_mismatch == (sha,)


def test_repair_declines_missing_image_bytes(conn, storage, png_bytes):
    sha = _store_image(storage)
    _image(storage, sha).unlink()
    report = run_repair(conn, storage, apply=True)
    assert any(sha in message for message in report.unfixable)
    assert report.sidecars_rebuilt == ()


def test_repair_removes_stale_temp_files(conn, storage):
    prefix = storage.root / "ab"
    prefix.mkdir(parents=True)
    stale = prefix / ".tmp-garbage"
    stale.touch()

    dry = run_repair(conn, storage, apply=False)
    assert dry.temp_files_removed == 0
    assert stale.exists()

    result = run_repair(conn, storage, apply=True)
    assert result.temp_files_removed == 1
    assert not stale.exists()


def test_unknown_extension_is_not_reconstructed(conn, storage, png_bytes):
    sha = storage.store(png_bytes).sha256
    image = _image(storage, sha)
    renamed = image.with_suffix(".xyz")
    image.rename(renamed)
    _sidecar(storage, sha).unlink()
    report = run_repair(conn, storage, apply=True)
    assert sha not in report.sidecars_rebuilt
    assert any(sha in message for message in report.unfixable)


def test_cli_check_exit_codes(tmp_path):
    from app.maintenance import main

    db = tmp_path / "test.db"
    store = tmp_path / "store"
    storage = ImageStorage(store)

    assert main(["check", "--db", str(db), "--store", str(store)]) == 0

    sha = storage.store(make_png_bytes()).sha256
    (store / sha[:2] / f"{sha}.json").unlink()
    assert main(["check", "--db", str(db), "--store", str(store)]) == 1


def test_cli_repair_dry_run_does_not_apply(tmp_path):
    from app.maintenance import main

    db = tmp_path / "test.db"
    store = tmp_path / "store"
    storage = ImageStorage(store)
    sha = storage.store(make_png_bytes()).sha256
    (store / sha[:2] / f"{sha}.json").unlink()

    assert main(["repair", "--db", str(db), "--store", str(store)]) == 0
    assert not (store / sha[:2] / f"{sha}.json").exists()

    assert main(["repair", "--yes", "--db", str(db), "--store", str(store)]) == 0
    assert (store / sha[:2] / f"{sha}.json").exists()