"""Domain models for the character/style library and reference-set workflow.

Plain frozen dataclasses mirroring the SQLite rows (see app/migrations).
Services return these so route handlers and templates never touch raw rows.

Design notes (agents.md non-negotiables):
  - lore_md is LOCAL-ONLY. It lives on Character but is deliberately absent
    from every model-facing payload (see CharacterService.model_payload).
  - visual_contract is the model-facing text, hard-capped at 60 words.
  - negative_traits is provider-facing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    id: int
    name: str
    slug: str
    lore_md: str
    visual_contract: str
    negative_traits: str
    default_style_id: int | None
    created_at: str
    # NULL == active. Archived characters stay in the DB (so panels that
    # reference them keep working) but are hidden from every list/picker.
    archived_at: str | None = None


@dataclass(frozen=True)
class Style:
    id: int
    name: str
    style_contract: str
    created_at: str
    # NULL == active. See Character.archived_at.
    archived_at: str | None = None

    @classmethod
    def from_row(cls, row) -> "Style":
        # display_name holds the human-facing name when an archived row's unique
        # `name` column has been renamed to its archived sentinel; fall back to
        # `name` for active rows (and legacy rows created before archiving).
        keys = row.keys()
        display = row["display_name"] if "display_name" in keys else None
        archived_at = row["archived_at"] if "archived_at" in keys else None
        return cls(
            id=row["id"],
            name=display if display else row["name"],
            style_contract=row["style_contract"],
            created_at=row["created_at"],
            archived_at=archived_at,
        )


@dataclass(frozen=True)
class RefSet:
    id: int
    character_id: int
    version: int
    status: str  # draft | canonical | retired
    created_at: str


@dataclass(frozen=True)
class RefImage:
    id: int
    ref_set_id: int
    sha256: str
    role: str
    weight: float
    embedding: bytes | None
    quality_flags: list[str]
    created_at: str

    @classmethod
    def from_row(cls, row) -> "RefImage":
        raw = row["quality_flags"] or "[]"
        try:
            flags = json.loads(raw)
        except json.JSONDecodeError:
            flags = []
        return cls(
            id=row["id"],
            ref_set_id=row["ref_set_id"],
            sha256=row["sha256"],
            role=row["role"],
            weight=row["weight"],
            embedding=row["embedding"],
            quality_flags=[str(f) for f in flags],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class RefSetSummary:
    """A ref_set plus its image count, for list/detail views."""

    ref_set: RefSet
    image_count: int


@dataclass(frozen=True)
class BaseStageTarget:
    id: int
    base_stage_id: int
    position: int
    description: str


@dataclass(frozen=True)
class BaseStage:
    id: int
    origin: str
    state: str
    description: str
    beat_text: str | None
    camera: str | None
    framing: str | None
    mood: str | None
    aspect_ratio: str
    style_id: int | None
    model: str | None
    image_size: str | None
    uploaded_sha256: str | None
    selected_candidate_id: int | None
    image_width: int | None
    image_height: int | None
    revision: int
    created_at: str
    archived_at: str | None
    targets: tuple[BaseStageTarget, ...]
    usage_count: int
