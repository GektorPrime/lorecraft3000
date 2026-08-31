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
from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class Style:
    id: int
    name: str
    style_contract: str
    ref_image_ids: list[int]
    created_at: str

    @classmethod
    def from_row(cls, row) -> "Style":
        """Build a Style from a sqlite3.Row, parsing ref_image_ids JSON."""
        raw = row["ref_image_ids"] or "[]"
        try:
            ids = json.loads(raw)
        except json.JSONDecodeError:
            ids = []
        return cls(
            id=row["id"],
            name=row["name"],
            style_contract=row["style_contract"],
            ref_image_ids=[int(i) for i in ids],
            created_at=row["created_at"],
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