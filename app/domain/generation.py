"""Provider-independent generation domain values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceInput:
    sha256: str
    role: str
    weight: float = 1.0


@dataclass(frozen=True)
class CastInput:
    character_id: int
    name: str
    visual_contract: str
    negative_traits: str
    ref_set_id: int
    ref_set_version: int
    references: tuple[ReferenceInput, ...]
    scene_role: str = ""
    prominence: int = 1


@dataclass(frozen=True)
class SceneInput:
    beat_text: str
    camera: str
    framing: str
    mood: str
    aspect_ratio: str


@dataclass(frozen=True)
class AllocatedReference:
    image_number: int
    character_id: int
    character_name: str
    ref_set_id: int
    ref_set_version: int
    sha256: str
    role: str


@dataclass(frozen=True)
class AssembledPrompt:
    text: str
    attachments: tuple[AllocatedReference, ...]
    prompt_hash: str
    warnings: tuple[str, ...]
