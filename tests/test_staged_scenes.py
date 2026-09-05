from __future__ import annotations

import pytest

from app.services.base_stages import BaseStageService
from app.services.characters import CharacterService
from app.services.scenes import SceneError, SceneImmutableError, SceneService
from tests.conftest import make_png_bytes


def _stage(storage, conn, description="A pair crosses the bridge."):
    return BaseStageService(conn, storage).upload(
        make_png_bytes(), description, ["left traveler", "right traveler"]
    )


def _characters(conn):
    return (
        CharacterService(conn).create(name="Elias", slug="elias"),
        CharacterService(conn).create(name="Mara", slug="mara"),
    )


def _cast(stage, characters):
    return [
        {
            "character_id": character.id,
            "base_stage_target_id": target.id,
            "role": "ignored free-form role",
        }
        for character, target in zip(characters, stage.targets)
    ]


def _create(service, stage, cast):
    return service.create(
        beat_text=None,
        camera=None,
        framing=None,
        mood=None,
        aspect_ratio="1:1",
        cast=cast,
        style_id=None,
        model="gemini-3.1-flash-image",
        image_size="1K",
        base_stage_id=stage.id,
    )


def test_staged_scene_normalizes_composition_and_duplicate_preserves_archived_stage(
    conn, storage, settings
):
    service = SceneService(conn, settings)
    stage = _stage(storage, conn)
    characters = _characters(conn)
    scene = _create(service, stage, _cast(stage, characters))

    assert scene.base_stage_id == stage.id
    assert scene.beat_text == stage.description
    assert scene.camera == scene.framing == scene.mood == ""
    assert scene.aspect_ratio == stage.aspect_ratio
    assert scene.style_id is None
    assert all(member["role"] == "" for member in scene.cast)

    BaseStageService(conn, storage).archive(stage.id)
    retained = service.update(
        scene.id,
        beat_text="ignored",
        camera="ignored",
        framing="ignored",
        mood="ignored",
        aspect_ratio="9:16",
        cast=_cast(stage, characters),
        style_id=999,
        model=scene.model,
        image_size=scene.image_size,
        base_stage_id=stage.id,
    )
    assert retained.base_stage_id == stage.id
    duplicate = service.duplicate(scene.id)
    assert duplicate.base_stage_id == stage.id
    assert duplicate.cast == scene.cast


@pytest.mark.parametrize("mutation, message", [
    (lambda cast, other: cast[:1], "cast count"),
    (lambda cast, other: [{**cast[0]}, {**cast[1], "base_stage_target_id": cast[0]["base_stage_target_id"]}], "mapped only once"),
    (lambda cast, other: [{**cast[0]}, {**cast[1], "base_stage_target_id": other.targets[0].id}], "selected base stage"),
    (lambda cast, other: [{**cast[0]}, {**cast[1], "character_id": cast[0]["character_id"]}], "character may appear only once"),
])
def test_staged_scene_rejects_incomplete_duplicate_cross_stage_and_duplicate_character(
    conn, storage, settings, mutation, message
):
    service = SceneService(conn, settings)
    stage = _stage(storage, conn)
    other = _stage(storage, conn, "Another pair waits.")
    cast = _cast(stage, _characters(conn))
    with pytest.raises(SceneError, match=message):
        _create(service, stage, mutation(cast, other))


def test_archived_stage_cannot_be_newly_selected_and_locked_association_is_immutable(
    conn, storage, settings
):
    service = SceneService(conn, settings)
    first = _stage(storage, conn)
    characters = _characters(conn)
    scene = _create(service, first, _cast(first, characters))
    archived = _stage(storage, conn, "An archived arrangement.")
    BaseStageService(conn, storage).archive(archived.id)
    with pytest.raises(SceneError, match="archived"):
        _create(service, archived, _cast(archived, characters))

    second = _stage(storage, conn, "A new arrangement.")
    conn.execute(
        "INSERT INTO generation (scene_id, model, state) VALUES (?, ?, 'pending')",
        (scene.id, scene.model),
    )
    conn.commit()
    with pytest.raises(SceneImmutableError):
        service.update(
            scene.id,
            beat_text=None,
            camera=None,
            framing=None,
            mood=None,
            aspect_ratio="3:2",
            cast=_cast(second, characters),
            style_id=None,
            model=scene.model,
            image_size=scene.image_size,
            base_stage_id=second.id,
        )


def test_direct_scene_contract_is_unchanged(conn, settings):
    character = CharacterService(conn).create(name="Elias", slug="elias")
    style_id = conn.execute("SELECT id FROM style ORDER BY id LIMIT 1").fetchone()[0]
    service = SceneService(conn, settings)
    with pytest.raises(SceneError, match="action/beat"):
        service.create(
            beat_text=None,
            camera="eye level",
            framing="medium",
            mood="",
            aspect_ratio="3:2",
            cast=[{"character_id": character.id}],
            style_id=style_id,
            model="gemini-3.1-flash-image",
            image_size="1K",
        )
