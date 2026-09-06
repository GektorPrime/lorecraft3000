from __future__ import annotations

import pytest

from app.assembler.core import (
    AssemblyError,
    assemble_base_stage_prompt,
    assemble_prompt,
    assemble_staged_prompt,
    capabilities_for,
)
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
    assert first.prompt_hash == "65d204236338161205f5d955e8a8e047df54f8e4333cb67bf7a3de436efc885a"


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


def test_turnaround_wins_when_capacity_is_tight():
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
            ReferenceInput("b" * 64, "full_body", 1.0),
            ReferenceInput("c" * 64, "turnaround", 1.0),
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
    assert result.attachments[0].role == "turnaround"


def test_staged_prompt_is_source_anchored_mapped_and_numbered_from_two():
    result = assemble_staged_prompt(
        model="gemini-3.1-flash-image",
        image_size="1K",
        cast=(_member(1, "ELIAS", refs=1),),
        base_stage_description="A traveler stands beneath a stone arch.",
        base_stage_sha256="a" * 64,
        target_map={1: "traveler beneath the arch"},
        target_ids={1: 101},
        style_contract="Victorian oil painting.",
    )

    assert result.text == """REFERENCE DECLARATION
Image 1 is the authoritative Base Stage/source composition. Use it as the exact visual and spatial foundation for the output.
Image 2 is a canonical reference for ELIAS (ref-set v2; roles: face_front). Apply only ELIAS's facial identity, hair, build, and distinguishing traits. Do not blend ELIAS with another character.

VISUAL CONTRACTS
ELIAS: Distinctive contract for ELIAS. Avoid for ELIAS: wrong hair.

BASE STAGE
A traveler stands beneath a stone arch.

TARGET MAP
ELIAS -> traveler beneath the arch

STYLE
Victorian oil painting.

PRESERVATION CONSTRAINTS
Preserve Image 1's exact composition, pose, body position, scale, clothing, occlusion, perspective, lighting, environment, and painterly treatment. Apply facial identity, hair, and distinguishing traits from the named character references only. Do not enlarge, reposition, rotate, spotlight, or separately present any figure, and do not turn any figure toward the viewer. Keep every identity separate. No text, no speech bubbles, no captions, no lettering, no visible watermark."""
    assert [attachment.image_number for attachment in result.attachments] == [2]


def test_staged_prompt_hash_covers_source_mapping_text_model_size_and_attachments():
    kwargs = {
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
        "cast": (_member(1, "ELIAS", refs=1),),
        "base_stage_description": "A stone arch.",
        "base_stage_sha256": "a" * 64,
        "target_map": {1: "figure beneath arch"},
        "target_ids": {1: 101},
    }
    baseline = assemble_staged_prompt(**kwargs).prompt_hash
    variants = [
        {**kwargs, "base_stage_sha256": "b" * 64},
        {**kwargs, "target_map": {1: "figure beside arch"}},
        {**kwargs, "target_ids": {1: 102}},
        {**kwargs, "base_stage_description": "A ruined stone arch."},
        {**kwargs, "model": "gemini-3-pro-image"},
        {**kwargs, "image_size": "2K"},
        {
            **kwargs,
            "cast": (_member(2, "MARA", refs=1),),
            "target_map": {2: "figure beneath arch"},
            "target_ids": {2: 101},
        },
    ]
    assert all(assemble_staged_prompt(**variant).prompt_hash != baseline for variant in variants)


def _base_stage_kwargs(**overrides):
    kwargs = {
        "model": "gemini-3.1-flash-image",
        "image_size": "1K",
        "description": "Four figures haul a machine up a ravine.",
        "beat_text": "They strain against the rope.",
        "camera": "twenty metres away",
        "framing": "wide environmental shot",
        "mood": "strenuous",
        "targets": ("figure above the slope", "figure beside the oak"),
        "style_contract": "Painted, not photographic.",
    }
    kwargs.update(overrides)
    return kwargs


def test_base_stage_prompt_is_identity_neutral_and_attachment_free():
    assembled = assemble_base_stage_prompt(**_base_stage_kwargs())

    # No cast exists yet, so nothing may be attached or identity-bearing.
    assert assembled.attachments == ()
    assert assembled.warnings == ()
    assert "REFERENCE DECLARATION" not in assembled.text
    assert "VISUAL CONTRACTS" not in assembled.text
    assert "Figure 1: figure above the slope" in assembled.text
    assert "Figure 2: figure beside the oak" in assembled.text
    assert "exactly 2 anonymous figures" in assembled.text
    assert "Painted, not photographic." in assembled.text
    assert "group portrait" in assembled.text


def test_base_stage_prompt_hash_covers_targets_model_and_size():
    baseline = assemble_base_stage_prompt(**_base_stage_kwargs())
    assert (
        assemble_base_stage_prompt(**_base_stage_kwargs()).prompt_hash
        == baseline.prompt_hash
    )
    for override in (
        {"targets": ("figure above the slope", "figure by the stream")},
        {"model": "gpt-image-2"},
        {"image_size": "2K"},
        {"description": "A different composition."},
        {"style_contract": "Another style."},
    ):
        assert (
            assemble_base_stage_prompt(**_base_stage_kwargs(**override)).prompt_hash
            != baseline.prompt_hash
        )


def test_base_stage_prompt_rejects_unusable_input():
    with pytest.raises(AssemblyError, match="at least one identity target"):
        assemble_base_stage_prompt(**_base_stage_kwargs(targets=()))
    with pytest.raises(AssemblyError, match="needs a description"):
        assemble_base_stage_prompt(**_base_stage_kwargs(description="  "))
    with pytest.raises(AssemblyError, match="unsupported image model"):
        assemble_base_stage_prompt(**_base_stage_kwargs(model="not-a-model"))
