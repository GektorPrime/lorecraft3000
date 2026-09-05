"""Tests for the face-embedding identity service.

These run in CI WITHOUT insightface/numpy installed, so they exercise the
numpy-free surface: graceful degradation when the optional model is absent,
the BLOB codec, gallery scoring, the generated-image scoring wrapper with a
fake embedder, and the model-pack lifecycle.
"""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from app.services.identity import (
    BUFFALO_L_FILES,
    MIN_MODEL_FILE_BYTES,
    decode_embedding,
    encode_embedding,
    install_model,
    model_dir,
    model_installed,
    model_status,
    score_against_gallery,
    score_generated_image,
)
from tests.conftest import FakeEmbedder, make_unit_vector


def test_encode_embedding_accepts_plain_sequences_without_numpy():
    vector = make_unit_vector(0.5)
    blob = encode_embedding(vector)
    assert len(blob) == 512 * 4
    # First float32 entry round-trips through struct without numpy.
    first = struct.unpack("<f", blob[:4])[0]
    assert first == pytest.approx(vector[0], abs=1e-6)


def test_decode_embedding_round_trip_requires_numpy():
    """decode returns a numpy float32 array; skipped where numpy is absent."""
    np = pytest.importorskip("numpy")
    blob = encode_embedding(make_unit_vector(0.3))
    decoded = decode_embedding(blob)
    assert decoded is not None
    assert decoded.shape == (512,)
    assert decoded.dtype == np.float32


def test_decode_embedding_rejects_wrong_size():
    assert decode_embedding(b"\x00" * 100) is None


def test_get_embedder_is_none_without_insightface():
    """Without insightface the app must keep running with embeddings skipped."""
    from app.services.identity import get_embedder

    try:
        import insightface  # noqa: F401

        pytest.skip("insightface installed; degradation path not testable here")
    except ImportError:
        assert get_embedder() is None


def test_get_embedder_is_none_when_model_missing(monkeypatch):
    """A missing buffalo_l pack disables scoring without downloading it."""
    monkeypatch.setattr(
        "app.services.identity._model_root", lambda: "/nonexistent/insightface/models"
    )
    from app.services.identity import get_embedder

    assert get_embedder() is None


def test_score_against_gallery_matches_exclusive_character():
    own = make_unit_vector(0.8)
    rival = make_unit_vector(0.2)
    gallery = {
        1: [("sha-own", own)],
        2: [("sha-rival", rival)],
    }
    scores = score_against_gallery(own, gallery)
    assert scores[1] > scores[2]


def test_score_against_gallery_excludes_held_out_reference():
    """Leave-one-out: the probe's own image is hidden, so it cannot win."""
    probe = make_unit_vector(0.9)
    gallery = {
        1: [("probe-sha", probe), ("other-sha", make_unit_vector(0.9))],
        2: [("rival-sha", make_unit_vector(0.1))],
    }
    scores = score_against_gallery(probe, gallery, exclude_sha="probe-sha")
    # Other reference of the same character still matches the probe.
    assert scores[1] > scores[2]


def test_score_generated_image_returns_none_without_faces():
    embedder = FakeEmbedder(faces=[])
    gallery = {1: [("sha", make_unit_vector(0.7))]}
    assert score_generated_image(embedder, gallery, b"\x00", (1,)) is None


def test_score_generated_image_maps_cast_scores():
    cast_vec = make_unit_vector(0.9)
    embedder = FakeEmbedder(faces=[cast_vec])
    gallery = {
        1: [("a", cast_vec)],
        2: [("b", make_unit_vector(0.2))],
    }
    payload = score_generated_image(embedder, gallery, b"\x00", (1,))
    assert payload is not None
    expected = sum(p * v for p, v in zip(cast_vec, cast_vec))
    assert payload["cast"] == {"1": pytest.approx(expected, abs=1e-4)}
    assert payload["faces_detected"] == 1


def test_score_generated_image_scores_every_requested_cast_member():
    embedder = FakeEmbedder(faces=[make_unit_vector(0.1)])
    gallery = {
        1: [("a", make_unit_vector(0.4))],
        2: [("b", make_unit_vector(0.2))],
    }
    payload = score_generated_image(embedder, gallery, b"\x00", (1, 2))
    assert payload is not None
    assert set(payload["cast"]) == {"1", "2"}


# ---------------------------------------------------------------------------
# Model-pack lifecycle
# ---------------------------------------------------------------------------

_FAKE_BYTES = b"x" * MIN_MODEL_FILE_BYTES


def _install_pack(tmp_path, monkeypatch, *, nested=False, undersized=False):
    """Write a fake pack zip (file URL) and point INSIGHTFACE_HOME at tmp."""
    root = tmp_path / "insightface"
    monkeypatch.setenv("INSIGHTFACE_HOME", str(root))
    size = 1 if undersized else MIN_MODEL_FILE_BYTES
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name in BUFFALO_L_FILES:
            archive.writestr(
                ("buffalo_l/" if nested else "") + name, b"y" * size
            )
    zip_path = tmp_path / "pack.zip"
    zip_path.write_bytes(buf.getvalue())
    return zip_path.as_uri()


def _write_installed_layout(tmp_path, monkeypatch):
    root = tmp_path / "insightface"
    monkeypatch.setenv("INSIGHTFACE_HOME", str(root))
    pack = model_dir()
    pack.mkdir(parents=True)
    for name in BUFFALO_L_FILES:
        (pack / name).write_bytes(b"x" * MIN_MODEL_FILE_BYTES)
    return pack


def test_model_status_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHTFACE_HOME", str(tmp_path / "nowhere"))
    assert model_status()["state"] == "missing"
    assert not model_installed()


def test_model_status_incomplete(tmp_path, monkeypatch):
    root = tmp_path / "insightface"
    monkeypatch.setenv("INSIGHTFACE_HOME", str(root))
    pack = model_dir()
    pack.mkdir(parents=True)
    (pack / BUFFALO_L_FILES[0]).write_bytes(b"x" * MIN_MODEL_FILE_BYTES)
    status = model_status()
    assert status["state"] == "incomplete"
    assert status["files"][BUFFALO_L_FILES[1]] is False
    assert not model_installed()


def test_model_status_ok(tmp_path, monkeypatch):
    _write_installed_layout(tmp_path, monkeypatch)
    assert model_status()["state"] == "ok"
    assert model_installed()


def test_install_is_noop_when_pack_installed(tmp_path, monkeypatch):
    pack = _write_installed_layout(tmp_path, monkeypatch)
    # A url that would fail loudly if it were ever hit: the early return must
    # mean no download attempt.
    result = install_model(url="file:///nonexistent/pack.zip", verify=True)
    assert result == str(pack)
    assert model_installed()


def test_install_unpacks_flat_pack(tmp_path, monkeypatch):
    url = _install_pack(tmp_path, monkeypatch, nested=False)
    install_model(url=url, verify=False)
    assert model_installed()
    assert sorted(p.name for p in model_dir().iterdir()) == sorted(BUFFALO_L_FILES)


def test_install_flattens_nested_pack(tmp_path, monkeypatch):
    url = _install_pack(tmp_path, monkeypatch, nested=True)
    install_model(url=url, verify=False)
    assert model_installed()
    assert sorted(p.name for p in model_dir().iterdir()) == sorted(BUFFALO_L_FILES)


def test_install_rejects_truncated_pack(tmp_path, monkeypatch):
    url = _install_pack(tmp_path, monkeypatch, undersized=True)
    with pytest.raises(RuntimeError, match="truncated"):
        install_model(url=url, verify=False)
    assert not model_installed()


def test_install_rolls_back_on_load_failure(tmp_path, monkeypatch):
    """A pack that fails to load must leave the previous install untouched."""
    pack = _write_installed_layout(tmp_path, monkeypatch)
    marker = pack / ".probe"
    marker.write_bytes(b"original")
    url = _install_pack(tmp_path, monkeypatch)

    class BrokenEmbedder:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("onnx runtime cannot start")

    monkeypatch.setattr("app.services.identity.FaceEmbedder", BrokenEmbedder)

    with pytest.raises(RuntimeError, match="failed to load"):
        install_model(url=url, verify=True, force=True)

    assert marker.read_bytes() == b"original"
    assert model_installed()


def test_install_force_replaces_installed_pack(tmp_path, monkeypatch):
    pack = _write_installed_layout(tmp_path, monkeypatch)
    (pack / ".probe").write_bytes(b"original")
    url = _install_pack(tmp_path, monkeypatch, nested=True)

    install_model(url=url, verify=False, force=True)

    assert model_installed()
    assert not (model_dir() / ".probe").exists()


# ---------------------------------------------------------------------------
# Captured-reference gallery
# ---------------------------------------------------------------------------


def test_load_gallery_for_attachments_resolves_captured_hashes(conn, storage):
    """A request's captured attachments resolve to exactly its reference faces."""
    from app.services.characters import CharacterService
    from app.services.identity import load_gallery_for_attachments, store_embedding
    from app.services.ref_sets import RefSetService
    from tests.conftest import make_png_bytes

    np = pytest.importorskip("numpy")

    character = CharacterService(conn).create(
        name="ELIAS", slug="elias", visual_contract="A painted face."
    )
    rival = CharacterService(conn).create(
        name="MARA", slug="mara", visual_contract="A different painted face."
    )
    refs = RefSetService(conn, storage)
    elias_set = refs.create_draft(character.id)
    elias_front = refs.add_image(
        elias_set.id, make_png_bytes((1, 2, 3)), "face_front", source_name="e.png"
    )
    # A non-face role must not enter the gallery even when embedded.
    elias_full = refs.add_image(
        elias_set.id, make_png_bytes((4, 5, 6)), "full_body", source_name="e-body.png"
    )
    refs.promote(elias_set.id)
    mara_set = refs.create_draft(rival.id)
    mara_front = refs.add_image(
        mara_set.id, make_png_bytes((7, 8, 9)), "face_front", source_name="m.png"
    )
    refs.promote(mara_set.id)

    # Embed only the character's own face_front — the rival and the full_body
    # stay unembedded, exercising the "missing embedding is skipped" branch.
    store_embedding(conn, elias_front.sha256, make_unit_vector(0.5))
    conn.commit()

    attachments = [
        {"image_number": 1, "character_id": character.id, "sha256": elias_front.sha256},
        {"image_number": 2, "character_id": character.id, "sha256": elias_full.sha256},
        {"image_number": 3, "character_id": rival.id, "sha256": mara_front.sha256},
        {"image_number": 4, "character_id": "not-an-int", "sha256": "1" * 64},
        None,
    ]

    gallery = load_gallery_for_attachments(conn, attachments)

    assert isinstance(next(iter(gallery.values()))[0][1], np.ndarray)
    assert set(gallery) == {character.id}
    assert [sha for sha, _ in gallery[character.id]] == [elias_front.sha256]


def test_load_gallery_for_attachments_accepts_empty_and_agrees_on_canonical(
    conn, storage
):
    """Empty attachments yield an empty gallery; the helper matches load_gallery."""
    from app.services.identity import load_gallery, load_gallery_for_attachments

    assert load_gallery_for_attachments(conn, ()) == {}
    # A nothing-but-noise input must not send a broken IN clause to SQLite.
    assert load_gallery_for_attachments(conn, [{}, "bogus"]) == {}


def test_load_gallery_for_attachments_uses_retired_reference_versions(conn, storage):
    """Retired-but-captured references still score, unlike the canonical query."""
    pytest.importorskip("numpy")
    from app.services.characters import CharacterService
    from app.services.identity import load_gallery, load_gallery_for_attachments, store_embedding
    from app.services.ref_sets import RefSetService
    from tests.conftest import make_png_bytes

    character = CharacterService(conn).create(
        name="ELIAS", slug="elias", visual_contract="A painted face."
    )
    refs = RefSetService(conn, storage)
    old_set = refs.create_draft(character.id)
    old_front = refs.add_image(
        old_set.id, make_png_bytes((1, 2, 3)), "face_front", source_name="e-old.png"
    )
    refs.promote(old_set.id)  # canonical
    newer_set = refs.create_draft(character.id)
    newer_front = refs.add_image(
        newer_set.id, make_png_bytes((9, 9, 9)), "face_front", source_name="e-new.png"
    )
    refs.promote(newer_set.id)  # retires old_front
    store_embedding(conn, old_front.sha256, make_unit_vector(0.4))
    store_embedding(conn, newer_front.sha256, make_unit_vector(0.8))
    conn.commit()

    attachments = [
        {"image_number": 1, "character_id": character.id, "sha256": old_front.sha256},
    ]

    captured = load_gallery_for_attachments(conn, attachments)
    assert set(captured) == {character.id}
    assert [sha for sha, _ in captured[character.id]] == [old_front.sha256]

    # The canonical query exposes the *new* reference only — the retired one a
    # captured request used is invisible to it.
    canonical = load_gallery(conn)
    assert [sha for sha, _ in canonical.get(character.id, [])] == [newer_front.sha256]
    assert [sha for sha, _ in captured[character.id]] != [newer_front.sha256]
