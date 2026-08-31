from __future__ import annotations

import pytest

from app.assembler.core import AssemblyError, assemble_prompt, capabilities_for
from app.domain.generation import CastInput, ReferenceInput, SceneInput


def _member(character_id: int, name: str, refs: int = 2, prominence: int = 1):
    return CastInput(
        character_id=character_id,
        name=name,
        visual_contract=f"Distinctive contract for {name}.",
        negative_traits="wrong hair",
        ref_set_id=character_id * 10,
        ref_set_version=2,
        references=tuple(
            ReferenceInput(f"{character_id:02d}{i:062d}", "face_front")
            for i in range(refs)
        ),
        scene_role=f"role {name}",
        prominence=prominence,
    )


def _scene():
    return SceneInput("Meeting at the fire.", "eye level", "medium", "tense", "3:2")


def test_two_character_allocation_is_explicit_and_deterministic():
    cast = (_member(1, "ELIAS", prominence=2), _member(2, "MARA"))
    first = assemble_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=cast,
        scene=_scene(),
        style_contract="Victorian oil painting.",
    )
    second = assemble_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=cast,
        scene=_scene(),
        style_contract="Victorian oil painting.",
    )
    assert first == second
    assert "Images 1-2 are canonical references for ELIAS" in first.text
    assert "Images 3-4 are canonical references for MARA" in first.text
    assert [ref.character_name for ref in first.attachments] == [
        "ELIAS", "ELIAS", "MARA", "MARA"
    ]
    assert len(first.prompt_hash) == 64


def test_five_characters_fit_pro_but_not_flash():
    cast = tuple(_member(i, f"CHAR{i}", refs=1) for i in range(1, 6))
    pro = assemble_prompt(
        model="gemini-3-pro-image",
        image_size="1K",
        cast=cast,
        scene=_scene(),
        style_contract="Victorian oil painting.",
    )
    assert len(pro.attachments) == 5
    with pytest.raises(AssemblyError, match="switch to Pro or split"):
        assemble_prompt(
            model="gemini-3.1-flash-image",
            image_size="1K",
            cast=cast,
            scene=_scene(),
            style_contract="Victorian oil painting.",
        )


def test_missing_refs_and_empty_cast_fail_loudly():
    with pytest.raises(AssemblyError, match="at least one"):
        assemble_prompt(
            model="gemini-3.1-flash-image",
            image_size="1K",
            cast=(),
            scene=_scene(),
            style_contract="style",
        )
    member = _member(1, "ELIAS", refs=0)
    with pytest.raises(AssemblyError, match="no canonical reference images"):
        assemble_prompt(
            model="gemini-3.1-flash-image",
            image_size="1K",
            cast=(member,),
            scene=_scene(),
            style_contract="style",
        )


def test_three_character_flash_warns_about_pro():
    result = assemble_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=tuple(_member(i, f"C{i}", refs=1) for i in range(1, 4)),
        scene=_scene(),
        style_contract="style",
    )
    assert result.warnings == ("Pro is recommended for panels with 3 or more characters",)
    assert capabilities_for("gemini-3.1-flash-image").supports_media_resolution is False


def test_prompt_contains_constraints_but_no_unprovided_lore():
    result = assemble_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=(_member(1, "ELIAS"),),
        scene=_scene(),
        style_contract="Victorian oil painting.",
    )
    assert "No text, no speech bubbles, no captions, no lettering" in result.text
    assert "lore" not in result.text.lower()


def test_identity_face_roles_win_when_capacity_is_tight():
    member = CastInput(
        character_id=1,
        name="ELIAS",
        visual_contract="contract",
        negative_traits="",
        ref_set_id=1,
        ref_set_version=1,
        references=(
            ReferenceInput("f" * 64, "outfit", 10.0),
            ReferenceInput("a" * 64, "face_front", 1.0),
        ),
    )
    cast = (member,) + tuple(_member(i, f"C{i}", refs=1) for i in range(2, 5))
    result = assemble_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=cast,
        scene=_scene(),
        style_contract="style",
    )
    assert result.attachments[0].role == "face_front"
