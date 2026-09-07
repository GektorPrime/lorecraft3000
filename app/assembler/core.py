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
from app.services.validation import ALLOWED_ROLES


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


_ROLE_PRIORITY = {role: rank for rank, role in enumerate(ALLOWED_ROLES)}


def capabilities_for(model: str) -> ModelCapabilities:
    try:
        return MODEL_CAPABILITIES[model]
    except KeyError as exc:
        raise AssemblyError(f"unsupported image model: {model}") from exc


def allocate_references(
    cast: tuple[CastInput, ...],
    capabilities: ModelCapabilities,
    *,
    start_ordinal: int = 1,
) -> tuple[AllocatedReference, ...]:
    """Allocate at least one ref per character, then extras by prominence."""
    if not cast:
        raise AssemblyError("a scene must have at least one character")
    if len(cast) > capabilities.max_character_references:
        raise AssemblyError(
            f"{capabilities.model} has a budget of "
            f"{capabilities.max_character_references} character references, but the "
            f"scene has {len(cast)} characters; switch to Pro or split the scene"
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
    image_number = start_ordinal
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
        warnings.append("Pro is recommended for scenes with 3 or more characters")

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


def assemble_base_stage_prompt(
    *,
    model: str,
    image_size: str,
    description: str,
    beat_text: str,
    camera: str,
    framing: str,
    mood: str,
    targets: tuple[str, ...],
    style_contract: str,
) -> AssembledPrompt:
    """Assemble an identity-neutral, reusable composition prompt.

    A Base Stage deliberately carries no cast: it is generated before any
    identity is applied, so there are no canonical references to allocate and
    the prompt must never name a character. Scenes later apply identities to
    this image via assemble_staged_prompt(), which anchors it as Image 1.

    Targets are the ordered textual placeholders a scene maps characters onto,
    so they are part of the composition contract and of the prompt hash.
    """
    capabilities_for(model)  # reject unsupported models before any spend
    if not description.strip():
        raise AssemblyError("a base stage needs a description")
    if not targets:
        raise AssemblyError("a base stage needs at least one identity target")

    numbered_targets = [
        f"Figure {position}: {target.strip()}"
        for position, target in enumerate(targets, start=1)
    ]

    sections = ["BASE STAGE\n" + description.strip()]
    if beat_text.strip():
        sections.append("SCENE\n" + beat_text.strip())
    sections.append(
        "CAMERA\n"
        + f"Camera: {camera.strip()}. Framing: {framing.strip()}. "
        + f"Mood: {mood.strip()}."
    )
    sections.append("IDENTITY TARGETS\n" + "\n".join(numbered_targets))
    if style_contract.strip():
        sections.append("STYLE\n" + style_contract.strip())
    sections.append(
        "CONSTRAINTS\n"
        f"Show exactly {len(targets)} anonymous figures matching the identity "
        "targets above, each clearly distinguishable by position and action. "
        "Render one continuous event in one continuous location with consistent "
        "perspective, scale, directional light, atmosphere, ground contact, and "
        "depth falloff. Do not depict any named, famous, or recognizable person, "
        "and do not present the figures as a group portrait, a lineup, isolated "
        "vignettes, or separately posed subjects. No text, no speech bubbles, no "
        "captions, no lettering, no visible watermark."
    )
    text = "\n\n".join(sections)

    hash_material = {
        "model": model,
        "image_size": image_size,
        "text": text,
        "targets": list(targets),
    }
    prompt_hash = hashlib.sha256(
        json.dumps(hash_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AssembledPrompt(text, (), prompt_hash, ())


def assemble_staged_prompt(
    *,
    model: str,
    image_size: str,
    cast: tuple[CastInput, ...],
    base_stage_description: str,
    base_stage_sha256: str,
    target_map: dict[int, str],
    target_ids: dict[int, int],
    style_contract: str = "",
) -> AssembledPrompt:
    """Assemble a source-anchored scene without changing direct assembly."""
    capabilities = capabilities_for(model)
    attachments = allocate_references(cast, capabilities, start_ordinal=2)
    by_character: dict[int, list[AllocatedReference]] = {}
    for attachment in attachments:
        by_character.setdefault(attachment.character_id, []).append(attachment)

    declarations = [
        "Image 1 is the authoritative Base Stage/source composition. Use it as "
        "the exact visual and spatial foundation for the output."
    ]
    contracts: list[str] = []
    mappings: list[str] = []
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
            f"(ref-set v{member.ref_set_version}; roles: {roles}). Apply only "
            f"{member.name}'s facial identity, hair, build, and distinguishing traits. "
            f"Do not blend {member.name} with another character."
        )
        contract = f"{member.name}: {member.visual_contract.strip()}"
        if member.negative_traits.strip():
            contract += f" Avoid for {member.name}: {member.negative_traits.strip()}."
        contracts.append(contract)
        mappings.append(f"{member.name} -> {target_map[member.character_id]}")

    warnings: list[str] = []
    if len(cast) >= 3 and model != "gemini-3-pro-image":
        warnings.append("Pro is recommended for scenes with 3 or more characters")

    sections = [
        "REFERENCE DECLARATION\n" + "\n".join(declarations),
        "VISUAL CONTRACTS\n" + "\n".join(contracts),
        "BASE STAGE\n" + base_stage_description.strip(),
        "TARGET MAP\n" + "\n".join(mappings),
    ]
    if style_contract.strip():
        sections.append("STYLE\n" + style_contract.strip())
    sections.append(
        "PRESERVATION CONSTRAINTS\n"
        "Preserve Image 1's exact composition, pose, body position, scale, clothing, "
        "occlusion, perspective, lighting, environment, and painterly treatment. "
        "Apply facial identity, hair, and distinguishing traits from the named "
        "character references only. Do not enlarge, reposition, rotate, spotlight, "
        "or separately present any figure, and do not turn any figure toward the "
        "viewer. Keep every identity separate. No text, no speech bubbles, no "
        "captions, no lettering, no visible watermark."
    )
    text = "\n\n".join(sections)
    hash_material = {
        "model": model,
        "image_size": image_size,
        "text": text,
        "base_stage_sha256": base_stage_sha256,
        "target_map": [
            {
                "character_id": member.character_id,
                "base_stage_target_id": target_ids[member.character_id],
                "target_description": target_map[member.character_id],
            }
            for member in cast
        ],
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
