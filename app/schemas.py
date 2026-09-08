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


class OptionsSummary(BaseModel):
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
    scene_immutability_explanation: str


class Budget(BaseModel):
    daily_spend_cap_cents: int
    spent_today_cents: int
    remaining_today_cents: int


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------


class CharacterInput(BaseModel):
    name: str
    slug: str | None = None
    lore_md: str = ""
    visual_contract: str = ""
    negative_traits: str = ""
    default_style_id: int | None = None


class Character(BaseModel):
    id: int
    name: str
    slug: str
    lore_md: str
    visual_contract: str
    negative_traits: str
    default_style_id: int | None
    created_at: str
    archived_at: str | None = None
    has_canonical_ref_set: bool
    avatar_url: str | None
    avatar_initials: str


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------


class StyleInput(BaseModel):
    name: str
    style_contract: str = ""


class Style(BaseModel):
    id: int
    name: str
    style_contract: str
    created_at: str
    archived_at: str | None = None


# ---------------------------------------------------------------------------
# reference sets / images
# ---------------------------------------------------------------------------


class RefImage(BaseModel):
    id: int
    ref_set_id: int
    role: str
    weight: float
    quality_flags: list[str]
    created_at: str
    content_url: str


class RefImageRoleUpdate(BaseModel):
    role: str


class RefSet(BaseModel):
    id: int
    character_id: int
    version: int
    status: str
    created_at: str
    images: list[RefImage]


class RefSetSummary(BaseModel):
    id: int
    character_id: int
    version: int
    status: str
    created_at: str
    image_count: int


# ---------------------------------------------------------------------------
# scenes (scenes)
# ---------------------------------------------------------------------------


class CastMemberInput(BaseModel):
    character_id: int
    role: str = ""
    prominence: int = Field(default=1, ge=1)
    base_stage_target_id: int | None = None


class CastMember(BaseModel):
    character_id: int
    role: str
    prominence: int
    name: str
    avatar_url: str | None
    avatar_initials: str
    base_stage_target_id: int | None = None


class SceneBaseStageTarget(BaseModel):
    id: int
    position: int
    description: str


class SceneBaseStage(BaseModel):
    id: int
    state: str
    description: str
    aspect_ratio: str
    style_id: int | None
    content_url: str
    targets: list[SceneBaseStageTarget]
    archived_at: str | None


class SceneInput(BaseModel):
    beat_text: str | None = None
    camera: str | None = None
    framing: str | None = None
    mood: str | None = None
    aspect_ratio: str = "3:2"
    cast: list[CastMemberInput]
    style_id: int | None = None
    model: str
    image_size: str
    base_stage_id: int | None = None


class SceneModelInput(BaseModel):
    model: str


class Scene(BaseModel):
    id: int
    beat_text: str
    camera: str
    framing: str
    mood: str
    aspect_ratio: str
    cast: list[CastMember]
    style_id: int | None
    base_stage_id: int | None
    base_stage: SceneBaseStage | None
    model: str
    image_size: str
    created_at: str
    is_editable: bool
    generation_count: int
    latest_attempt_preview_url: str | None


class SceneSummary(BaseModel):
    """Lightweight scene reference used where a full scene payload is overkill,
    e.g. "which scenes use this Base Stage"."""

    id: int
    beat_text: str
    created_at: str
    is_editable: bool
    generation_count: int
    latest_attempt_preview_url: str | None


# ---------------------------------------------------------------------------
# generation / candidates
# ---------------------------------------------------------------------------


class GenerationAttachment(BaseModel):
    image_number: int
    character_id: int
    character_name: str
    ref_set_id: int
    ref_set_version: int
    role: str


class ScenePreview(BaseModel):
    scene_id: int
    model: str
    image_size: str
    prompt: str
    prompt_hash: str
    attachments: list[GenerationAttachment]
    warnings: list[str]
    estimated_cost_cents: int
    spent_today_cents: int
    remaining_after_cents: int
    can_generate: bool
    blocked_reason: str | None = None
    base_stage_id: int | None = None
    source_content_url: str | None = None


class GenerationCreate(BaseModel):
    expected_prompt_hash: str


class Candidate(BaseModel):
    id: int
    generation_id: int
    idx: int
    review_status: str
    content_url: str
    created_at: str
    identity_scores: dict[str, object] | None = None


class CandidateReviewIn(BaseModel):
    verdict: str


class CandidateEditIn(BaseModel):
    instruction: str = Field(min_length=1)


class Generation(BaseModel):
    id: int
    # Exactly one owner is set: a scene (scene_id) or a Base Stage.
    scene_id: int | None = None
    base_stage_id: int | None = None
    model: str
    image_size: str
    aspect_ratio: str
    prompt: str
    prompt_hash: str
    attachments: list[GenerationAttachment]
    warnings: list[str]
    cost_usd_cents: int
    reserved_cost_usd_cents: int
    actual_cost_usd_cents: int | None
    state: str
    interaction_id: str | None
    error_text: str | None
    completed_at: str | None
    created_at: str
    candidates: list[Candidate]


class GenerationSummary(BaseModel):
    id: int
    scene_id: int | None = None
    base_stage_id: int | None = None
    model: str
    cost_usd_cents: int
    reserved_cost_usd_cents: int
    actual_cost_usd_cents: int | None
    state: str
    error_text: str | None
    completed_at: str | None
    created_at: str
    candidates: list[Candidate]


class GalleryItem(BaseModel):
    candidate_id: int
    content_url: str
    scene_id: int
    beat_text: str
    aspect_ratio: str
    created_at: str


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------


class PanelCreate(BaseModel):
    title: str
    format: str
    rows: int = Field(default=1, ge=1, le=8)
    columns: int = Field(default=1, ge=1, le=8)
    candidate_id: int | None = None


class PanelSlotInput(BaseModel):
    candidate_id: int | None
    slot_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    focal_x: float = 0.5
    focal_y: float = 0.5
    zoom: float = 1.0


class PanelUpdate(BaseModel):
    expected_revision: int
    title: str
    format: str
    background_color: str
    gutter_px: int
    frame_px: int
    slots: list[PanelSlotInput]


class PanelRenderCreate(BaseModel):
    expected_revision: int


class PanelSlot(BaseModel):
    id: int
    candidate_id: int | None
    slot_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    focal_x: float
    focal_y: float
    zoom: float
    content_url: str | None


class PanelRender(BaseModel):
    id: int
    panel_id: int
    panel_revision: int
    width: int
    height: int
    layout: dict[str, object]
    created_at: str
    content_url: str
    download_url: str


class Panel(BaseModel):
    id: int
    title: str
    format: str
    width_px: int
    height_px: int
    background_color: str
    gutter_px: int
    frame_px: int
    revision: int
    created_at: str
    updated_at: str
    slots: list[PanelSlot]
    latest_render: PanelRender | None


# ---------------------------------------------------------------------------
# Base Stages
# ---------------------------------------------------------------------------


class BaseStageTarget(BaseModel):
    id: int
    position: int
    description: str


class ImageDimensions(BaseModel):
    width: int
    height: int


class BaseStage(BaseModel):
    id: int
    origin: str
    state: str
    description: str
    beat_text: str | None
    camera: str | None
    framing: str | None
    mood: str | None
    style_id: int | None
    model: str | None
    image_size: str | None
    selected_candidate_id: int | None
    aspect_ratio: str
    dimensions: ImageDimensions | None
    content_url: str | None
    targets: list[BaseStageTarget]
    usage_count: int
    revision: int
    created_at: str
    archived_at: str | None
    is_editable: bool = False
    generation_count: int = 0


class BaseStageGeneratedInput(BaseModel):
    """Composition for a generated Base Stage draft.

    Identity targets are required: they are injected into the prompt and are
    what a scene later maps its cast onto.
    """

    description: str
    beat_text: str
    camera: str
    framing: str
    mood: str = ""
    aspect_ratio: str = "3:2"
    style_id: int
    model: str
    image_size: str
    targets: list[str] = Field(min_length=1)


class BaseStagePublishIn(BaseModel):
    candidate_id: int


class BaseStagePreview(BaseModel):
    base_stage_id: int
    model: str
    image_size: str
    aspect_ratio: str
    prompt: str
    prompt_hash: str
    warnings: list[str]
    estimated_cost_cents: int
    spent_today_cents: int
    remaining_after_cents: int
    can_generate: bool
    blocked_reason: str | None = None
