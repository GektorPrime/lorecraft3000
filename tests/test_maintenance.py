"""Tests for the storage consistency scan and repair command."""

from __future__ import annotations

import json

import pytest

from app.maintenance import run_check, run_repair
from app.storage import ImageStorage
from tests.conftest import FakeEmbedder, make_png_bytes


def _store_image(storage: ImageStorage, color=(200, 30, 30)) -> str:
    return storage.store(make_png_bytes(color)).sha256


def _sidecar(storage: ImageStorage, sha256: str):
    return storage.root / sha256[:2] / f"{sha256}.json"


def _image(storage: ImageStorage, sha256: str):
    return storage.find_image(sha256)


def _owned_generation(conn) -> int:
    """A generation must belong to exactly one panel or base stage."""
    style_id = conn.execute("SELECT id FROM style LIMIT 1").fetchone()["id"]
    scene_id = conn.execute(
        "INSERT INTO scene (style_id) VALUES (?)", (style_id,)
    ).lastrowid
    conn.execute(
        "INSERT INTO generation (scene_id, model) VALUES (?, 'test')", (scene_id,)
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_dangling_candidate(conn, sha256: str) -> None:
    generation_id = _owned_generation(conn)
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


def test_dangling_uploaded_base_stage_hash_is_detected(conn, storage):
    ghost = "b" * 64
    conn.execute(
        """
        INSERT INTO base_stage
            (origin, state, description, aspect_ratio, uploaded_sha256,
             image_width, image_height)
        VALUES ('upload', 'ready', 'Missing stage', '16:9', ?, 1600, 900)
        """,
        (ghost,),
    )
    conn.commit()

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
    generation_id = _owned_generation(conn)
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


# ---------------------------------------------------------------------------
# Identity backfill
# ---------------------------------------------------------------------------


def _canonical_character(conn, storage, name="ELIAS", slug="elias"):
    from app.services.characters import CharacterService
    from app.services.ref_sets import RefSetService

    character = CharacterService(conn).create(
        name=name, slug=slug, visual_contract=f"A painted face for {name}."
    )
    refs = RefSetService(conn, storage)
    ref_set = refs.create_draft(character.id)
    # No embedder here, so add_image leaves face_embedding empty — the
    # precondition the backfill command exists to repair.
    refs.add_image(
        ref_set.id, make_png_bytes((10, 20, 30)), "face_front", source_name=f"{slug}.png"
    )
    refs.promote(ref_set.id)
    return character


def _generated_candidate(conn, storage, tmp_path, character_id):
    """Run a real generation (no embedder) so the candidate starts with {}."""
    from app.config import Settings
    from app.services.generation import GenerationService
    from app.services.styles import StyleService
    from tests.test_generation_service import FakeProvider

    style = StyleService(conn).get_default()
    scene_id = conn.execute(
        "INSERT INTO scene (beat_text, camera, framing, mood, aspect_ratio, "
        "cast_json, style_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "Two painted faces study a map.",
            "eye level",
            "medium two-shot",
            "determined",
            "16:9",
            json.dumps([{"character_id": character_id, "prominence": 1}]),
            style.id,
        ),
    ).lastrowid
    conn.commit()
    settings = Settings(
        db_path=conn.execute("PRAGMA database_list").fetchone()[2],
        store_root=tmp_path / "store",
    )
    outcome = GenerationService(conn, storage, settings, FakeProvider()).generate(scene_id)
    return outcome


def test_backfill_raises_without_embedder(conn, storage, monkeypatch):
    monkeypatch.setattr("app.maintenance.get_embedder", lambda: None)
    from app.maintenance import run_identity_backfill

    with pytest.raises(RuntimeError, match="insightface"):
        run_identity_backfill(conn, storage)


def test_backfill_embeds_canonical_face_refs(conn, storage, monkeypatch):
    _canonical_character(conn, storage)
    ref = conn.execute("SELECT sha256 FROM ref_image WHERE role = 'face_front'").fetchone()
    assert ref is not None
    assert conn.execute(
        "SELECT 1 FROM face_embedding WHERE sha256 = ?", (ref["sha256"],)
    ).fetchone() is None

    monkeypatch.setattr("app.maintenance.get_embedder", lambda: FakeEmbedder())
    from app.maintenance import run_identity_backfill

    report = run_identity_backfill(conn, storage, scope="refs")
    assert report.refs_embedded == 1
    assert report.errors == ()
    assert conn.execute(
        "SELECT 1 FROM face_embedding WHERE sha256 = ?", (ref["sha256"],)
    ).fetchone() is not None
    # Idempotent: a second pass finds nothing left to embed.
    second = run_identity_backfill(conn, storage, scope="refs")
    assert second.refs_embedded == 0


def test_backfill_ref_without_face_is_reported_not_fatal(conn, storage, monkeypatch):
    _canonical_character(conn, storage)
    monkeypatch.setattr(
        "app.maintenance.get_embedder", lambda: FakeEmbedder(faces=[])
    )
    from app.maintenance import run_identity_backfill

    report = run_identity_backfill(conn, storage, scope="refs")
    assert report.refs_embedded == 0
    assert report.refs_no_face
    assert report.errors == ()


def test_backfill_scores_unscored_candidates(conn, storage, tmp_path, monkeypatch):
    character = _canonical_character(conn, storage)
    outcome = _generated_candidate(conn, storage, tmp_path, character.id)
    before = conn.execute(
        "SELECT identity_scores FROM candidate WHERE id = ?", (outcome.candidate_id,)
    ).fetchone()
    assert json.loads(before["identity_scores"]) == {}

    embedder = FakeEmbedder()
    monkeypatch.setattr("app.maintenance.get_embedder", lambda: embedder)
    monkeypatch.setattr(
        "app.maintenance.load_gallery", lambda _conn: {character.id: [("sha", embedder.face)]}
    )
    from app.maintenance import run_identity_backfill

    report = run_identity_backfill(conn, storage, scope="candidates")
    assert report.candidates_scored == 1
    assert report.candidates_no_face == 0
    after = conn.execute(
        "SELECT identity_scores FROM candidate WHERE id = ?", (outcome.candidate_id,)
    ).fetchone()
    payload = json.loads(after["identity_scores"])
    assert set(payload["cast"]) == {str(character.id)}
    assert payload["faces_detected"] == 1


def test_backfill_candidate_without_face_is_skipped_not_failed(
    conn, storage, tmp_path, monkeypatch
):
    character = _canonical_character(conn, storage)
    outcome = _generated_candidate(conn, storage, tmp_path, character.id)

    monkeypatch.setattr(
        "app.maintenance.get_embedder", lambda: FakeEmbedder(faces=[])
    )
    monkeypatch.setattr(
        "app.maintenance.load_gallery", lambda _conn: {character.id: []}
    )
    from app.maintenance import run_identity_backfill

    report = run_identity_backfill(conn, storage, scope="candidates")
    assert report.candidates_no_face == 1
    assert report.candidates_scored == 0
    assert report.candidates_skipped_bad_cast == 0


def test_backfill_force_rescores_unscored_background_and_leaves_new_fields(
    conn, storage, tmp_path, monkeypatch
):
    """--force re-runs scoring; a plain run only touches {}-scored candidates."""
    character = _canonical_character(conn, storage)
    outcome = _generated_candidate(conn, storage, tmp_path, character.id)

    embedder = FakeEmbedder()
    monkeypatch.setattr("app.maintenance.get_embedder", lambda: embedder)
    monkeypatch.setattr(
        "app.maintenance.load_gallery", lambda _conn: {character.id: [("sha", embedder.face)]}
    )
    from app.maintenance import run_identity_backfill

    run_identity_backfill(conn, storage, scope="candidates")
    # Rescored, so a plain run finds nothing to do...
    report = run_identity_backfill(conn, storage, scope="candidates")
    assert report.candidates_scored == 0
    # ...but --force recomputes anyway.
    forced = run_identity_backfill(conn, storage, scope="candidates", force=True)
    assert forced.candidates_scored == 1


# ---------------------------------------------------------------------------
# Face-model lifecycle CLI
# ---------------------------------------------------------------------------


def _cli_installed_layout(tmp_path, monkeypatch):
    from app.services.identity import BUFFALO_L_FILES, MIN_MODEL_FILE_BYTES, model_dir

    root = tmp_path / "insightface"
    monkeypatch.setenv("INSIGHTFACE_HOME", str(root))
    pack = model_dir()
    pack.mkdir(parents=True)
    for name in BUFFALO_L_FILES:
        (pack / name).write_bytes(b"x" * MIN_MODEL_FILE_BYTES)
    return pack


def test_cli_models_status_installed_reports_ok(tmp_path, monkeypatch, capsys):
    from app.maintenance import main

    _cli_installed_layout(tmp_path, monkeypatch)
    assert main(["models", "status"]) == 0
    assert "installed" in capsys.readouterr().out


def test_cli_models_status_missing_exits_nonzero(tmp_path, monkeypatch, capsys):
    from app.maintenance import main

    monkeypatch.setenv("INSIGHTFACE_HOME", str(tmp_path / "nowhere"))
    assert main(["models", "status"]) == 1
    assert "install" in capsys.readouterr().out


def test_cli_models_install_wires_url_and_force(tmp_path, monkeypatch):
    import app.maintenance as maint

    root = tmp_path / "insightface"
    monkeypatch.setenv("INSIGHTFACE_HOME", str(root))

    seen = {}

    def fake_install(**kwargs):
        seen.update(kwargs)
        return str(root / "buffalo_l")

    monkeypatch.setattr(maint, "install_model", fake_install)
    assert maint.main(["models", "install", "--force", "--url", "http://mirror/pack.zip"]) == 0
    assert seen["force"] is True
    assert seen["url"] == "http://mirror/pack.zip"
    assert seen["verify"] is True
