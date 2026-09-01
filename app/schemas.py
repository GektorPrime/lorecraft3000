"""Typed Pydantic DTOs for the /api/v1 JSON API (issue #15).

These are the ONLY shapes the frontend ever sees. Two invariants held across
every DTO here:

  - No user-facing SHA-256 / content hash. Images are referenced by their
    opaque database id via a content URL (``/api/v1/ref-images/{id}/content``,
    ``/api/v1/candidates/{id}/content``); the sha256 stays an internal
    storage-layer detail (see app/storage.py, app/services/ref_sets.py).
  - lore_md remains local-only in the domain layer; it IS included here
    because these DTOs back the character library UI (which edits lore_md),
    but it is never sent by the prompt assembler (see
    CharacterService.model_payload, which excludes it).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# shared / options
# ---------------------------------------------------------------------------


class ErrorOut(BaseModel):
    message: str
    type: str


class OptionsSummaryOut(BaseModel):
    """Static configuration + live budget for driving frontend forms."""

    models: list[str]
    image_sizes: list[str]
    aspect_ratios: list[str]
    ref_image_roles: list[str]
    default_model: str
    default_image_size: str
    daily_spend_cap_cents: int
    spent_today_cents: int
    remaining_today_cents: int
    ref_image_weight_explanation: str
    ref_set_immutability_explanation: str
    panel_immutability_explanation: str


class BudgetOut(BaseModel):
    daily_spend_cap_cents: int
    spent_today_cents: int
    remaining_today_cents: int


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------


class CharacterCreate(BaseModel):
    name: str
    slug: str | None = None
    lore_md: str = ""
    visual_contract: str = ""
    negative_traits: str = ""
    default_style_id: int | None = None


class CharacterUpdate(CharacterCreate):
    pass


class CharacterOut(BaseModel):
    id: int
    name: str
    slug: str
    lore_md: str
    visual_contract: str
    negative_traits: str
    default_style_id: int | None
    created_at: str
    has_canonical_ref_set: bool
    avatar_url: str | None
    avatar_initials: str


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------


class StyleCreate(BaseModel):
    name: str
    style_contract: str = ""


class StyleUpdate(StyleCreate):
    pass


class StyleOut(BaseModel):
    id: int
    name: str
    style_contract: str
    created_at: str


# ---------------------------------------------------------------------------
# reference sets / images
# ---------------------------------------------------------------------------


class RefImageOut(BaseModel):
    id: int
    ref_set_id: int
    role: str
    weight: float
    quality_flags: list[str]
    created_at: str
    content_url: str


class RefImageRoleUpdate(BaseModel):
    role: str


class RefSetOut(BaseModel):
    id: int
    character_id: int
    version: int
    status: str
    created_at: str
    images: list[RefImageOut]


class RefSetSummaryOut(BaseModel):
    id: int
    character_id: int
    version: int
    status: str
    created_at: str
    image_count: int


# ---------------------------------------------------------------------------
# panels (scenes)
# ---------------------------------------------------------------------------


class CastMemberIn(BaseModel):
    character_id: int
    role: str = ""
    prominence: int = Field(default=1, ge=1)


class CastMemberOut(BaseModel):
    character_id: int
    role: str
    prominence: int
    name: str
    avatar_url: str | None
    avatar_initials: str


class PanelCreate(BaseModel):
    beat_text: str
    camera: str
    framing: str
    mood: str = ""
    aspect_ratio: str = "3:2"
    cast: list[CastMemberIn]
    style_id: int
    model: str
    image_size: str


class PanelUpdate(PanelCreate):
    pass


class PanelOut(BaseModel):
    id: int
    beat_text: str
    camera: str
    framing: str
    mood: str
    aspect_ratio: str
    cast: list[CastMemberOut]
    style_id: int
    model: str
    image_size: str
    created_at: str
    is_editable: bool
    generation_count: int


# ---------------------------------------------------------------------------
# generation / candidates
# ---------------------------------------------------------------------------


class GenerationAttachmentOut(BaseModel):
    image_number: int
    character_id: int
    character_name: str
    ref_set_id: int
    ref_set_version: int
    role: str


class PanelPreviewOut(BaseModel):
    scene_id: int
    model: str
    image_size: str
    prompt: str
    prompt_hash: str
    attachments: list[GenerationAttachmentOut]
    warnings: list[str]
    estimated_cost_cents: int
    spent_today_cents: int
    remaining_after_cents: int
    can_generate: bool
    blocked_reason: str | None = None


class GenerationCreate(BaseModel):
    expected_prompt_hash: str


class CandidateOut(BaseModel):
    id: int
    generation_id: int
    idx: int
    review_status: str
    content_url: str
    created_at: str


class CandidateReviewIn(BaseModel):
    verdict: str


class GenerationOut(BaseModel):
    id: int
    scene_id: int
    model: str
    image_size: str
    aspect_ratio: str
    prompt: str
    prompt_hash: str
    attachments: list[GenerationAttachmentOut]
    warnings: list[str]
    cost_usd_cents: int
    reserved_cost_usd_cents: int
    actual_cost_usd_cents: int | None
    state: str
    interaction_id: str | None
    error_text: str | None
    completed_at: str | None
    created_at: str
    candidates: list[CandidateOut]


class GenerationSummaryOut(BaseModel):
    id: int
    scene_id: int
    model: str
    cost_usd_cents: int
    reserved_cost_usd_cents: int
    actual_cost_usd_cents: int | None
    state: str
    error_text: str | None
    completed_at: str | None
    created_at: str
