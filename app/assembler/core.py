"""Deterministic multi-character prompt assembly and reference budgeting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.domain.generation import (
    AllocatedReference,
    AssembledPrompt,
    CastInput,
    SceneInput,
)


@dataclass(frozen=True)
class ModelCapabilities:
    model: str
    max_character_references: int


MODEL_CAPABILITIES = {
    "gemini-3.1-flash-image": ModelCapabilities(
        "gemini-3.1-flash-image", 4
    ),
    "gemini-3-pro-image": ModelCapabilities("gemini-3-pro-image", 5),
    # OpenAI GPT image models accept up to 16 input images on their edit
    # endpoint; 5 character references matches the Pro budget and stays well
    # within that.
    "gpt-image-1": ModelCapabilities("gpt-image-1", 5),
    "gpt-image-1.5": ModelCapabilities("gpt-image-1.5", 5),
    "gpt-image-2": ModelCapabilities("gpt-image-2", 5),
}


class AssemblyError(Exception):
    """Raised before spending when a prompt cannot be assembled safely."""


_ROLE_PRIORITY = {
    "face_front": 0,
    "face_3q": 1,
    "face_profile": 2,
    "full_body": 3,
    "expression": 4,
    "outfit": 5,
}


def capabilities_for(model: str) -> ModelCapabilities:
    try:
        return MODEL_CAPABILITIES[model]
    except KeyError as exc:
        raise AssemblyError(f"unsupported image model: {model}") from exc


def allocate_references(
    cast: tuple[CastInput, ...], capabilities: ModelCapabilities
) -> tuple[AllocatedReference, ...]:
    """Allocate at least one ref per character, then extras by prominence."""
    if not cast:
        raise AssemblyError("a panel must have at least one character")
    if len(cast) > capabilities.max_character_references:
        raise AssemblyError(
            f"{capabilities.model} has a budget of "
            f"{capabilities.max_character_references} character references, but the "
            f"panel has {len(cast)} characters; switch to Pro or split the panel"
        )
    for member in cast:
        if not member.references:
            raise AssemblyError(
                f"{member.name} has no canonical reference images; curate a reference "
                "set before generating"
            )

    ordered_refs = {
        member.character_id: tuple(
            sorted(
                member.references,
                key=lambda ref: (
                    _ROLE_PRIORITY.get(ref.role, 99),
                    -ref.weight,
                    ref.sha256,
                ),
            )
        )
        for member in cast
    }
    selected: dict[int, list] = {
        member.character_id: [ordered_refs[member.character_id][0]] for member in cast
    }
    remaining = capabilities.max_character_references - len(cast)
    priority = sorted(
        enumerate(cast), key=lambda item: (-item[1].prominence, item[0])
    )
    next_index = {member.character_id: 1 for member in cast}
    while remaining:
        allocated_this_round = False
        for _, member in priority:
            index = next_index[member.character_id]
            references = ordered_refs[member.character_id]
            if index >= len(references):
                continue
            selected[member.character_id].append(references[index])
            next_index[member.character_id] += 1
            remaining -= 1
            allocated_this_round = True
            if not remaining:
                break
        if not allocated_this_round:
            break

    allocated: list[AllocatedReference] = []
    image_number = 1
    for member in cast:
        for ref in selected[member.character_id]:
            allocated.append(
                AllocatedReference(
                    image_number=image_number,
                    character_id=member.character_id,
                    character_name=member.name,
                    ref_set_id=member.ref_set_id,
                    ref_set_version=member.ref_set_version,
                    sha256=ref.sha256,
                    role=ref.role,
                )
            )
            image_number += 1
    return tuple(allocated)


def assemble_prompt(
    *,
    model: str,
    image_size: str,
    cast: tuple[CastInput, ...],
    scene: SceneInput,
    style_contract: str,
) -> AssembledPrompt:
    capabilities = capabilities_for(model)
    attachments = allocate_references(cast, capabilities)
    by_character: dict[int, list[AllocatedReference]] = {}
    for attachment in attachments:
        by_character.setdefault(attachment.character_id, []).append(attachment)

    declarations: list[str] = []
    contracts: list[str] = []
    staging: list[str] = []
    for member in cast:
        refs = by_character[member.character_id]
        numbers = [ref.image_number for ref in refs]
        image_range = (
            f"Image {numbers[0]}"
            if len(numbers) == 1
            else f"Images {numbers[0]}-{numbers[-1]}"
        )
        reference_phrase = (
            "is a canonical reference" if len(numbers) == 1
            else "are canonical references"
        )
        roles = ", ".join(ref.role for ref in refs)
        declarations.append(
            f"{image_range} {reference_phrase} for {member.name} "
            f"(ref-set v{member.ref_set_version}; roles: {roles}). Match "
            f"{member.name}'s face, build, and distinguishing traits exactly. "
            f"Do not blend {member.name} with another character."
        )
        contract = f"{member.name}: {member.visual_contract.strip()}"
        if member.negative_traits.strip():
            contract += f" Avoid for {member.name}: {member.negative_traits.strip()}."
        contracts.append(contract)
        role = member.scene_role.strip() or "present in the scene"
        staging.append(f"{member.name}: {role}")

    warnings: list[str] = []
    if len(cast) >= 3 and model != "gemini-3-pro-image":
        warnings.append("Pro is recommended for panels with 3 or more characters")

    distinct = len(cast)
    text = "\n\n".join(
        [
            "REFERENCE DECLARATION\n" + "\n".join(declarations),
            "VISUAL CONTRACTS\n" + "\n".join(contracts),
            "SCENE\n"
            + scene.beat_text.strip()
            + "\nCast staging: "
            + "; ".join(staging),
            "CAMERA\n"
            + f"Camera: {scene.camera.strip()}. Framing: {scene.framing.strip()}. "
            + f"Mood: {scene.mood.strip()}.",
            "STYLE\n" + style_contract.strip(),
            "CONSTRAINTS\n"
            + f"Show {distinct} distinct named character"
            + ("s" if distinct != 1 else "")
            + ". Keep every identity separate. No text, no speech bubbles, no "
            + "captions, no lettering, no visible watermark.",
        ]
    )
    hash_material = {
        "model": model,
        "image_size": image_size,
        "text": text,
        "attachments": [
            {
                "sha256": ref.sha256,
                "character_id": ref.character_id,
                "ref_set_id": ref.ref_set_id,
                "ref_set_version": ref.ref_set_version,
                "role": ref.role,
            }
            for ref in attachments
        ],
    }
    prompt_hash = hashlib.sha256(
        json.dumps(hash_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AssembledPrompt(text, attachments, prompt_hash, tuple(warnings))
