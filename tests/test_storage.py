"""Tests for the content-addressed image storage service."""

from __future__ import annotations

import json
import hashlib

import pytest

from app.storage import ImageStorage, ImageStorageError
from tests.conftest import make_png_bytes


def test_store_returns_metadata(storage, png_bytes):
    meta = storage.store(png_bytes, source_name="ref.png")
    assert meta.sha256 == hashlib.sha256(png_bytes).hexdigest()
    assert meta.format == "PNG"
    assert meta.size == len(png_bytes)
    assert meta.width == 8
    assert meta.height == 8
    assert meta.deduplicated is False
    assert meta.path.endswith(f"{meta.sha256}.png")


def test_store_writes_file_and_sidecar(storage, png_bytes):
    meta = storage.store(png_bytes, source_name="ref.png")
    path = storage.root / meta.sha256[:2] / f"{meta.sha256}.png"
    assert path.exists()
    assert path.read_bytes() == png_bytes

    sidecar = storage.root / meta.sha256[:2] / f"{meta.sha256}.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["sha256"] == meta.sha256
    assert data["size"] == len(png_bytes)
    assert data["format"] == "PNG"
    assert data["source_name"] == "ref.png"
    # Sidecar must contain no secrets.
    assert "key" not in data
    assert "token" not in data
    assert "secret" not in data


def test_dedupe_identical_bytes(storage, png_bytes):
    first = storage.store(png_bytes)
    second = storage.store(png_bytes)
    assert first.sha256 == second.sha256
    assert second.deduplicated is True
    # Only one file + one sidecar on disk.
    files = [p for p in storage.root.rglob("*") if p.is_file()]
    assert len(files) == 2  # image + sidecar


def test_dedupe_preserves_first_sidecar(storage, png_bytes):
    """Re-storing identical bytes with a different source_name keeps the FIRST sidecar."""
    first = storage.store(png_bytes, source_name="first.png")
    second = storage.store(png_bytes, source_name="second.png")
    assert second.deduplicated is True

    sidecar = storage.root / first.sha256[:2] / f"{first.sha256}.json"
    data = json.loads(sidecar.read_text())
    # The sidecar still reflects the FIRST source_name.
    assert data["source_name"] == "first.png"


def test_read_rejects_non_hash_path_input(storage):
    with pytest.raises(ImageStorageError, match="64 lowercase hexadecimal"):
        storage.read("../../outside")


def test_different_bytes_stored_separately(storage):
    a = make_png_bytes((200, 30, 30))
    b = make_png_bytes((30, 200, 30))
    ma = storage.store(a)
    mb = storage.store(b)
    assert ma.sha256 != mb.sha256
    assert ma.deduplicated is False
    assert mb.deduplicated is False


def test_rebuild_friendly_metadata(storage, png_bytes):
    """Metadata is enough to rebuild the index from the filesystem."""
    meta = storage.store(png_bytes, source_name="ref.png")
    sidecar = storage.root / meta.sha256[:2] / f"{meta.sha256}.json"
    data = json.loads(sidecar.read_text())
    # The sidecar carries everything needed to reconstruct a DB pointer.
    assert data["sha256"] == meta.sha256
    assert data["extension"] == "png"
    assert data["size"] == meta.size
    assert data["format"] == meta.format


def test_rejects_non_image_bytes(storage):
    with pytest.raises(ImageStorageError):
        storage.store(b"this is not an image")


def test_rejects_empty_bytes(storage):
    with pytest.raises(ImageStorageError):
        storage.store(b"")


def test_path_for(storage, png_bytes):
    meta = storage.store(png_bytes)
    expected = storage.root / meta.sha256[:2] / f"{meta.sha256}.png"
    assert storage.path_for(meta.sha256, "png") == expected


# ---------------------------------------------------------------------------
# Atomic, durable, self-healing publish (Phase 3 Work Package 2)
# ---------------------------------------------------------------------------

def test_orphaned_image_without_sidecar_is_healed_on_restore(storage, png_bytes):
    """A crash-orphaned image (no sidecar) is completed by the next store."""
    meta = storage.store(png_bytes, source_name="ref.png")
    sidecar = storage.root / meta.sha256[:2] / f"{meta.sha256}.json"

    # Simulate a crash between writing the image and its sidecar.
    sidecar.unlink()
    with pytest.raises(ImageStorageError):
        storage.read(meta.sha256)

    # Re-storing the same bytes must heal the object rather than skip it.
    again = storage.store(png_bytes, source_name="ref.png")
    assert again.deduplicated is False
    assert sidecar.exists()
    data, metadata = storage.read(meta.sha256)
    assert data == png_bytes
    assert metadata["extension"] == "png"


def test_orphaned_image_with_malformed_sidecar_is_healed(storage, png_bytes):
    meta = storage.store(png_bytes)
    sidecar = storage.root / meta.sha256[:2] / f"{meta.sha256}.json"
    sidecar.write_text("{ not valid json")

    again = storage.store(png_bytes)
    assert again.deduplicated is False
    data, metadata = storage.read(meta.sha256)
    assert data == png_bytes
    assert metadata["extension"] == "png"


def test_complete_object_is_deduplicated_not_republished(storage, png_bytes):
    """A genuinely complete duplicate is skipped and keeps the first sidecar."""
    first = storage.store(png_bytes, source_name="first.png")
    image = storage.root / first.sha256[:2] / f"{first.sha256}.png"
    sidecar = storage.root / first.sha256[:2] / f"{first.sha256}.json"
    image_mtime = image.stat().st_mtime_ns
    sidecar_mtime = sidecar.stat().st_mtime_ns

    second = storage.store(png_bytes, source_name="second.png")
    assert second.deduplicated is True
    # No republish: files are untouched and the first sidecar is preserved.
    assert image.stat().st_mtime_ns == image_mtime
    assert sidecar.stat().st_mtime_ns == sidecar_mtime
    assert json.loads(sidecar.read_text())["source_name"] == "first.png"


def test_publish_leaves_no_temp_files(storage, png_bytes):
    meta = storage.store(png_bytes)
    leftovers = [
        p
        for p in (storage.root / meta.sha256[:2]).iterdir()
        if p.name.startswith(".tmp-")
    ]
    assert leftovers == []


def test_successful_store_publishes_image_and_sidecar(storage, png_bytes):
    meta = storage.store(png_bytes)
    image = storage.root / meta.sha256[:2] / f"{meta.sha256}.png"
    sidecar = storage.root / meta.sha256[:2] / f"{meta.sha256}.json"
    assert image.exists()
    assert sidecar.exists()
