"""Focused tests for the upload-first Base Stage service."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services import base_stages as base_stage_module
from app.services.base_stages import (
    BaseStageNotFoundError,
    BaseStageService,
    BaseStageValidationError,
    MAX_DESCRIPTION_LENGTH,
    MAX_IMAGE_WIDTH,
    MAX_TARGET_DESCRIPTION_LENGTH,
    MAX_TARGETS,
)
from tests.conftest import make_png_bytes


def _png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _animated_png() -> bytes:
    output = io.BytesIO()
    frames = [Image.new("RGB", (8, 8), color) for color in ((1, 2, 3), (4, 5, 6))]
    frames[0].save(output, format="PNG", save_all=True, append_images=frames[1:])
    return output.getvalue()


def test_upload_list_get_and_content_hash(conn, storage, png_bytes):
    service = BaseStageService(conn, storage)
    stage = service.upload(
        png_bytes,
        "  A moonlit bridge  ",
        ["  figure at left ", "figure at right"],
        source_name="bridge.png",
    )

    assert stage.origin == "upload"
    assert stage.state == "ready"
    assert stage.description == "A moonlit bridge"
    assert stage.aspect_ratio == "1:1"
    assert (stage.image_width, stage.image_height) == (8, 8)
    assert [target.position for target in stage.targets] == [0, 1]
    assert [target.description for target in stage.targets] == [
        "figure at left",
        "figure at right",
    ]
    assert service.get(stage.id) == stage
    assert service.list() == [stage]
    assert service.content_sha(stage.id) == storage.store(png_bytes).sha256


def test_environment_only_upload_and_nearest_ratio(conn, storage):
    stage = BaseStageService(conn, storage).upload(_png(160, 91), "Landscape", [])
    assert stage.targets == ()
    assert stage.aspect_ratio == "16:9"


def test_archive_restore_and_archived_get(conn, storage, png_bytes):
    service = BaseStageService(conn, storage)
    stage = service.upload(png_bytes, "Room", [])
    archived = service.archive(stage.id)
    assert archived.archived_at is not None
    assert service.list() == []
    assert service.list_archived() == [archived]
    assert service.get(stage.id).id == stage.id
    assert service.content_sha(stage.id) == stage.uploaded_sha256

    restored = service.restore(stage.id)
    assert restored.archived_at is None
    assert service.list_archived() == []
    assert service.list() == [restored]


@pytest.mark.parametrize(
    ("description", "targets", "message"),
    [
        (" ", [], "description is required"),
        ("x" * (MAX_DESCRIPTION_LENGTH + 1), [], "at most 2000"),
        ("room", [" "], "must not be blank"),
        ("room", ["Person", " person "], "case-insensitive"),
        ("room", ["x" * (MAX_TARGET_DESCRIPTION_LENGTH + 1)], "at most 500"),
        ("room", [str(i) for i in range(MAX_TARGETS + 1)], "at most 8"),
    ],
)
def test_upload_validation(conn, storage, png_bytes, description, targets, message):
    with pytest.raises(BaseStageValidationError, match=message):
        BaseStageService(conn, storage).upload(png_bytes, description, targets)


def test_rejects_animation_dimensions_and_pixels(conn, storage, monkeypatch):
    service = BaseStageService(conn, storage)
    with pytest.raises(BaseStageValidationError, match="animated"):
        service.upload(_animated_png(), "Animated", [])
    with pytest.raises(BaseStageValidationError, match="width exceeds"):
        service.upload(_png(MAX_IMAGE_WIDTH + 1, 1), "Too wide", [])

    monkeypatch.setattr(base_stage_module, "MAX_IMAGE_PIXELS", 63)
    with pytest.raises(BaseStageValidationError, match="pixel limit"):
        service.upload(make_png_bytes(), "Too many pixels", [])


def test_missing_stage_has_clean_error(conn, storage):
    with pytest.raises(BaseStageNotFoundError, match="base stage 404 not found"):
        BaseStageService(conn, storage).get(404)
