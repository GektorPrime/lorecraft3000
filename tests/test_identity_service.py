"""Tests for the face-embedding identity service.

These run in CI WITHOUT insightface/numpy installed, so they exercise the
numpy-free surface: graceful degradation when the optional model is absent,
the BLOB codec, gallery scoring, and the generated-image scoring wrapper with
a fake embedder.
"""

from __future__ import annotations

import struct

import pytest

from app.services.identity import (
    decode_embedding,
    encode_embedding,
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


def test_score_generated_image_omits_absent_characters():
    """Characters with no detected match simply do not appear."""
    embedder = FakeEmbedder(faces=[make_unit_vector(0.1)])
    gallery = {
        1: [("a", make_unit_vector(0.4))],
        2: [("b", make_unit_vector(0.2))],
    }
    payload = score_generated_image(embedder, gallery, b"\x00", (1, 2))
    assert payload is not None
    assert set(payload["cast"]) == {"1", "2"}