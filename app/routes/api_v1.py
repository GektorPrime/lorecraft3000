"""Typed JSON API for the React frontend (issue #15).

Every route here returns/accepts the Pydantic DTOs in app/schemas.py — never
raw sqlite3.Row objects or service dataclasses directly — so the wire shape is
explicit and versioned independently of the server-rendered Jinja routes in
app/routes/{characters,styles,ref_sets,scenes}.py, which remain for backward
compatibility.

All business logic stays in app/services/*; routes only translate between the
service layer and the API's typed request/response shapes, and map service
exceptions to a consistent error envelope
(``{"detail": {"message": ..., "type": ...}}``).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response

from app.deps import get_conn, get_provider, get_storage, settings
from app.providers.base import ImageProvider
from app.schemas import (
    BudgetOut,
    CandidateOut,
    CandidateReviewIn,
    CastMemberOut,
    CharacterCreate,
    CharacterOut,
    CharacterUpdate,
    GenerationAttachmentOut,
    GenerationOut,
    GenerationSummaryOut,
    OptionsSummaryOut,
    PanelCreate,
    PanelOut,
    PanelPreviewOut,
    PanelUpdate,
    RefImageOut,
    RefImageRoleUpdate,
    RefSetOut,
    RefSetSummaryOut,
    StyleCreate,
    StyleOut,
    StyleUpdate,
)
from app.services.avatars import AvatarService
from app.services.characters import (
    CharacterError,
    CharacterNotFoundError,
    CharacterService,
    InvalidStyleReferenceError,
    SlugCollisionError,
    VisualContractTooLongError,
)
from app.services.costs import (
    BudgetExceededError,
    CostError,
    CostLedger,
    GenerationPendingError,
    IdempotencyConflictError,
    SceneChangedError,
    UnknownPriceError,
)
from app.services.generation import GenerationError, GenerationService
from app.services.ref_sets import (
    ImageRejectedError,
    InvalidRoleError,
    RefSetError,
    RefSetNotDraftError,
    RefSetNotFoundError,
    RefSetService,
)
from app.services.scenes import (
    ASPECT_RATIOS,
    SceneError,
    SceneImmutableError,
    SceneNotFoundError,
    SceneService,
)
from app.services.styles import StyleError, StyleNameCollisionError, StyleNotFoundError, StyleService
from app.services.validation import ALLOWED_ROLES
from app.storage import ImageStorage, ImageStorageError

router = APIRouter(prefix="/api/v1", tags=["api-v1"])

MODELS = ("gemini-3.1-flash-image", "gemini-3-pro-image")
IMAGE_SIZES = ("1K", "2K", "4K")
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_MIME = {"image/png", "image/jpeg", "image/webp"}

REF_IMAGE_WEIGHT_EXPLANATION = (
    "Weight influences how a reference image is prioritized for extra "
    "reference slots after every cast member has one canonical reference. It "
    "does not affect an image's visual size, cropping, or position \u2014 only "
    "slot-allocation priority. Weight defaults to 1.0 and cannot be edited "
    "from the UI; it is a fixed value on the stored reference image."
)
REF_SET_IMMUTABILITY_EXPLANATION = (
    "A canonical reference set is permanent once promoted: its images, "
    "roles, and weights can never change, and it can never be deleted. To "
    "make changes, copy it into a new draft, edit the draft, then promote "
    "the draft \u2014 this retires the current canonical set (kept forever) "
    "and makes the new one canonical."
)
PANEL_IMMUTABILITY_EXPLANATION = (
    "A panel can be edited after failed generation attempts because each "
    "failure preserves its own request snapshot. A pending or successful "
    "generation locks the panel. Use Duplicate to create a new, editable "
    "panel while keeping the original and its complete attempt history."
)


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------

_ERROR_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (CharacterNotFoundError, 404),
    (StyleNotFoundError, 404),
    (RefSetNotFoundError, 404),
    (SceneNotFoundError, 404),
    (SlugCollisionError, 409),
    (StyleNameCollisionError, 409),
    (RefSetNotDraftError, 409),
    (SceneImmutableError, 409),
    (GenerationPendingError, 409),
    (IdempotencyConflictError, 409),
    (SceneChangedError, 409),
    (BudgetExceededError, 402),
    (VisualContractTooLongError, 422),
    (InvalidStyleReferenceError, 422),
    (InvalidRoleError, 422),
    (ImageRejectedError, 422),
    (UnknownPriceError, 422),
    (ImageStorageError, 404),
    (CharacterError, 422),
    (StyleError, 422),
    (RefSetError, 422),
    (SceneError, 422),
    (GenerationError, 422),
    (CostError, 422),
)


def _raise_for(exc: Exception) -> None:
    """Map a known service exception to a consistent HTTPException and raise it."""
    for exc_type, status_code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            raise HTTPException(
                status_code=status_code,
                detail={"message": str(exc), "type": type(exc).__name__},
            ) from exc
    raise HTTPException(
        status_code=500, detail={"message": str(exc), "type": type(exc).__name__}
    ) from exc


# ---------------------------------------------------------------------------
# shared builders
# ---------------------------------------------------------------------------


def _initials(name: str) -> str:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _ref_image_out(image) -> RefImageOut:
    return RefImageOut(
        id=image.id,
        ref_set_id=image.ref_set_id,
        role=image.role,
        weight=image.weight,
        quality_flags=image.quality_flags,
        created_at=image.created_at,
        content_url=f"/api/v1/ref-images/{image.id}/content",
    )


def _ref_set_out(ref_set, images) -> RefSetOut:
    return RefSetOut(
        id=ref_set.id,
        character_id=ref_set.character_id,
        version=ref_set.version,
        status=ref_set.status,
        created_at=ref_set.created_at,
        images=[_ref_image_out(img) for img in images],
    )


def _character_out(conn, storage: ImageStorage, character) -> CharacterOut:
    canonical = RefSetService(conn, storage).get_canonical(character.id)
    avatar = AvatarService(conn, storage).avatar_image_for(character.id)
    return CharacterOut(
        id=character.id,
        name=character.name,
        slug=character.slug,
        lore_md=character.lore_md,
        visual_contract=character.visual_contract,
        negative_traits=character.negative_traits,
        default_style_id=character.default_style_id,
        created_at=character.created_at,
        has_canonical_ref_set=canonical is not None,
        avatar_url=f"/api/v1/ref-images/{avatar.id}/content" if avatar else None,
        avatar_initials=_initials(character.name),
    )


def _cast_member_out(conn, storage: ImageStorage, entry: dict) -> CastMemberOut:
    character_id = int(entry["character_id"])
    try:
        name = CharacterService(conn).get(character_id).name
    except CharacterNotFoundError:
        name = f"Unknown character #{character_id}"
    avatar = AvatarService(conn, storage).avatar_image_for(character_id)
    return CastMemberOut(
        character_id=character_id,
        role=str(entry.get("role", "")),
        prominence=int(entry.get("prominence", 1)),
        name=name,
        avatar_url=f"/api/v1/ref-images/{avatar.id}/content" if avatar else None,
        avatar_initials=_initials(name),
    )


def _panel_out(conn, storage: ImageStorage, scene) -> PanelOut:
    scenes = SceneService(conn, settings)
    return PanelOut(
        id=scene.id,
        beat_text=scene.beat_text,
        camera=scene.camera,
        framing=scene.framing,
        mood=scene.mood,
        aspect_ratio=scene.aspect_ratio,
        cast=[_cast_member_out(conn, storage, entry) for entry in scene.cast],
        style_id=scene.style_id,
        model=scene.model,
        image_size=scene.image_size,
        created_at=scene.created_at,
        is_editable=scenes.is_editable(scene.id),
        generation_count=scenes.generation_count(scene.id),
    )


def _attachment_out(attachment: dict) -> GenerationAttachmentOut:
    return GenerationAttachmentOut(
        image_number=attachment["image_number"],
        character_id=attachment["character_id"],
        character_name=attachment["character_name"],
        ref_set_id=attachment["ref_set_id"],
        ref_set_version=attachment["ref_set_version"],
        role=attachment["role"],
    )


def _candidate_out(row) -> CandidateOut:
    return CandidateOut(
        id=row["id"],
        generation_id=row["generation_id"],
        idx=row["idx"],
        review_status=row["review_status"],
        content_url=f"/api/v1/candidates/{row['id']}/content",
        created_at=row["created_at"],
    )


def _generation_out(conn, row) -> GenerationOut:
    request_data = json.loads(row["request_json"] or "{}")
    warnings = list(request_data.get("warnings", []))
    if row["warning_text"]:
        warnings.append(row["warning_text"])
    candidates = conn.execute(
        "SELECT * FROM candidate WHERE generation_id = ? ORDER BY idx", (row["id"],)
    ).fetchall()
    return GenerationOut(
        id=row["id"],
        scene_id=row["scene_id"],
        model=row["model"],
        image_size=request_data.get("image_size", ""),
        aspect_ratio=request_data.get("aspect_ratio", ""),
        prompt=request_data.get("prompt", ""),
        prompt_hash=row["prompt_hash"],
        attachments=[_attachment_out(a) for a in request_data.get("attachments", [])],
        warnings=warnings,
        cost_usd_cents=row["cost_usd_cents"],
        reserved_cost_usd_cents=row["reserved_cost_usd_cents"],
        actual_cost_usd_cents=row["actual_cost_usd_cents"],
        state=row["state"],
        interaction_id=row["interaction_id"],
        error_text=row["error_text"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        candidates=[_candidate_out(c) for c in candidates],
    )


def _serve_stored_image(sha256: str, storage: ImageStorage) -> Response:
    try:
        data, metadata = storage.read(sha256)
    except ImageStorageError as exc:
        _raise_for(exc)
    mime = _MIME.get(metadata.get("format"), "application/octet-stream")
    return Response(data, media_type=mime)


# ---------------------------------------------------------------------------
# options / budget
# ---------------------------------------------------------------------------


@router.get("/options/summary", response_model=OptionsSummaryOut)
def options_summary(conn=Depends(get_conn)) -> OptionsSummaryOut:
    ledger = CostLedger(conn, settings)
    spent = ledger.spent_today()
    return OptionsSummaryOut(
        models=list(MODELS),
        image_sizes=list(IMAGE_SIZES),
        aspect_ratios=list(ASPECT_RATIOS),
        ref_image_roles=list(ALLOWED_ROLES),
        default_model=settings.default_model,
        default_image_size=settings.default_image_size,
        daily_spend_cap_cents=settings.daily_spend_cap_cents,
        spent_today_cents=spent,
        remaining_today_cents=settings.daily_spend_cap_cents - spent,
        ref_image_weight_explanation=REF_IMAGE_WEIGHT_EXPLANATION,
        ref_set_immutability_explanation=REF_SET_IMMUTABILITY_EXPLANATION,
        panel_immutability_explanation=PANEL_IMMUTABILITY_EXPLANATION,
    )


@router.get("/budget", response_model=BudgetOut)
def budget(conn=Depends(get_conn)) -> BudgetOut:
    ledger = CostLedger(conn, settings)
    spent = ledger.spent_today()
    return BudgetOut(
        daily_spend_cap_cents=settings.daily_spend_cap_cents,
        spent_today_cents=spent,
        remaining_today_cents=settings.daily_spend_cap_cents - spent,
    )


# ---------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------


@router.get("/characters", response_model=list[CharacterOut])
def list_characters(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [_character_out(conn, storage, c) for c in CharacterService(conn).list()]


@router.post("/characters", response_model=CharacterOut, status_code=201)
def create_character(payload: CharacterCreate, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        character = CharacterService(conn).create(
            name=payload.name,
            slug=payload.slug,
            lore_md=payload.lore_md,
            visual_contract=payload.visual_contract,
            negative_traits=payload.negative_traits,
            default_style_id=payload.default_style_id,
        )
    except CharacterError as exc:
        _raise_for(exc)
    return _character_out(conn, storage, character)


@router.get("/characters/{character_id}", response_model=CharacterOut)
def get_character(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        character = CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    return _character_out(conn, storage, character)


@router.put("/characters/{character_id}", response_model=CharacterOut)
def update_character(
    character_id: int, payload: CharacterUpdate, conn=Depends(get_conn), storage=Depends(get_storage)
):
    try:
        character = CharacterService(conn).update(
            character_id,
            name=payload.name,
            slug=payload.slug,
            lore_md=payload.lore_md,
            visual_contract=payload.visual_contract,
            negative_traits=payload.negative_traits,
            default_style_id=payload.default_style_id,
        )
    except CharacterError as exc:
        _raise_for(exc)
    return _character_out(conn, storage, character)


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------


@router.get("/styles", response_model=list[StyleOut])
def list_styles(conn=Depends(get_conn)):
    return [StyleOut(**s.__dict__) for s in StyleService(conn).list()]


@router.post("/styles", response_model=StyleOut, status_code=201)
def create_style(payload: StyleCreate, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).create(
            name=payload.name,
            style_contract=payload.style_contract,
            ref_image_ids=payload.ref_image_ids,
        )
    except StyleError as exc:
        _raise_for(exc)
    return StyleOut(**style.__dict__)


@router.get("/styles/{style_id}", response_model=StyleOut)
def get_style(style_id: int, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).get(style_id)
    except StyleNotFoundError as exc:
        _raise_for(exc)
    return StyleOut(**style.__dict__)


@router.put("/styles/{style_id}", response_model=StyleOut)
def update_style(style_id: int, payload: StyleUpdate, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).update(
            style_id,
            name=payload.name,
            style_contract=payload.style_contract,
            ref_image_ids=payload.ref_image_ids,
        )
    except StyleError as exc:
        _raise_for(exc)
    return StyleOut(**style.__dict__)


# ---------------------------------------------------------------------------
# reference sets / images
# ---------------------------------------------------------------------------


@router.get("/characters/{character_id}/ref-sets", response_model=list[RefSetSummaryOut])
def list_ref_sets(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    summaries = RefSetService(conn, storage).list_for_character(character_id)
    return [
        RefSetSummaryOut(
            id=s.ref_set.id,
            character_id=s.ref_set.character_id,
            version=s.ref_set.version,
            status=s.ref_set.status,
            created_at=s.ref_set.created_at,
            image_count=s.image_count,
        )
        for s in summaries
    ]


@router.post("/characters/{character_id}/ref-sets", response_model=RefSetOut, status_code=201)
def create_ref_set_draft(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    service = RefSetService(conn, storage)
    draft = service.create_draft(character_id)
    return _ref_set_out(draft, service.images(draft.id))


@router.get("/ref-sets/{ref_set_id}", response_model=RefSetOut)
def get_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        ref_set = service.get(ref_set_id)
    except RefSetNotFoundError as exc:
        _raise_for(exc)
    return _ref_set_out(ref_set, service.images(ref_set_id))


@router.post("/ref-sets/{ref_set_id}/copy", response_model=RefSetOut, status_code=201)
def copy_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        new_draft = service.copy_to_new_draft(ref_set_id)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_set_out(new_draft, service.images(new_draft.id))


@router.post("/ref-sets/{ref_set_id}/promote", response_model=RefSetOut)
def promote_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        promoted = service.promote(ref_set_id)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_set_out(promoted, service.images(ref_set_id))


@router.post("/ref-sets/{ref_set_id}/images", response_model=RefImageOut, status_code=201)
def upload_ref_image(
    ref_set_id: int,
    role: str = Form(...),
    image: UploadFile = File(...),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    service = RefSetService(conn, storage)
    if image.content_type not in ALLOWED_UPLOAD_MIME:
        _raise_for(ImageRejectedError("upload must be a PNG, JPEG, or WebP image"))
    data = image.file.read(MAX_UPLOAD_BYTES + 1) if image.file else b""
    if len(data) > MAX_UPLOAD_BYTES:
        _raise_for(ImageRejectedError("upload exceeds the 10 MB limit"))
    try:
        ref_image = service.add_image(ref_set_id, data, role, source_name=image.filename)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_image_out(ref_image)


@router.patch("/ref-sets/{ref_set_id}/images/{image_id}", response_model=RefImageOut)
def re_role_ref_image(
    ref_set_id: int,
    image_id: int,
    payload: RefImageRoleUpdate,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    service = RefSetService(conn, storage)
    try:
        ref_image = service.set_image_role(ref_set_id, image_id, payload.role)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_image_out(ref_image)


@router.delete("/ref-sets/{ref_set_id}/images/{image_id}", status_code=204)
def remove_ref_image(ref_set_id: int, image_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        service.remove_image(ref_set_id, image_id)
    except RefSetError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.get("/ref-images/{image_id}/content")
def ref_image_content(image_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    row = conn.execute("SELECT sha256 FROM ref_image WHERE id = ?", (image_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"ref image {image_id} not found", "type": "RefImageNotFoundError"},
        )
    return _serve_stored_image(row["sha256"], storage)


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------


def _cast_to_dicts(cast) -> list[dict]:
    return [{"character_id": c.character_id, "role": c.role, "prominence": c.prominence} for c in cast]


@router.get("/panels", response_model=list[PanelOut])
def list_panels(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [_panel_out(conn, storage, s) for s in SceneService(conn, settings).list()]


@router.post("/panels", response_model=PanelOut, status_code=201)
def create_panel(payload: PanelCreate, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).create(
            beat_text=payload.beat_text,
            camera=payload.camera,
            framing=payload.framing,
            mood=payload.mood,
            aspect_ratio=payload.aspect_ratio,
            cast=_cast_to_dicts(payload.cast),
            style_id=payload.style_id,
            model=payload.model,
            image_size=payload.image_size,
        )
    except SceneError as exc:
        _raise_for(exc)
    return _panel_out(conn, storage, scene)


@router.get("/panels/{panel_id}", response_model=PanelOut)
def get_panel(panel_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).get(panel_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    return _panel_out(conn, storage, scene)


@router.put("/panels/{panel_id}", response_model=PanelOut)
def update_panel(panel_id: int, payload: PanelUpdate, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).update(
            panel_id,
            beat_text=payload.beat_text,
            camera=payload.camera,
            framing=payload.framing,
            mood=payload.mood,
            aspect_ratio=payload.aspect_ratio,
            cast=_cast_to_dicts(payload.cast),
            style_id=payload.style_id,
            model=payload.model,
            image_size=payload.image_size,
        )
    except SceneError as exc:
        _raise_for(exc)
    return _panel_out(conn, storage, scene)


@router.post("/panels/{panel_id}/duplicate", response_model=PanelOut, status_code=201)
def duplicate_panel(panel_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).duplicate(panel_id)
    except SceneError as exc:
        _raise_for(exc)
    return _panel_out(conn, storage, scene)


@router.get("/panels/{panel_id}/preview", response_model=PanelPreviewOut)
def preview_panel(panel_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    scenes = SceneService(conn, settings)
    try:
        scene = scenes.get(panel_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    try:
        preview = GenerationService(conn, storage, settings, None).preview(
            panel_id, model=scene.model, image_size=scene.image_size
        )
    except (GenerationError, CostError, ImageStorageError) as exc:
        return PanelPreviewOut(
            scene_id=panel_id,
            model=scene.model,
            image_size=scene.image_size,
            prompt="",
            prompt_hash="",
            attachments=[],
            warnings=[],
            estimated_cost_cents=0,
            spent_today_cents=CostLedger(conn, settings).spent_today(),
            remaining_after_cents=0,
            can_generate=False,
            blocked_reason=str(exc),
        )
    return PanelPreviewOut(
        scene_id=preview.scene_id,
        model=preview.model,
        image_size=preview.image_size,
        prompt=preview.prompt,
        prompt_hash=preview.prompt_hash,
        attachments=[_attachment_out(a) for a in preview.attachments],
        warnings=list(preview.warnings),
        estimated_cost_cents=preview.estimated_cost_cents,
        spent_today_cents=preview.spent_today_cents,
        remaining_after_cents=preview.remaining_after_cents,
        can_generate=True,
        blocked_reason=None,
    )


@router.get(
    "/panels/{panel_id}/generations", response_model=list[GenerationSummaryOut]
)
def list_panel_generations(
    panel_id: int, conn=Depends(get_conn)
) -> list[GenerationSummaryOut]:
    try:
        SceneService(conn, settings).get(panel_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    rows = conn.execute(
        "SELECT * FROM generation WHERE scene_id = ? ORDER BY id DESC", (panel_id,)
    ).fetchall()
    return [
        GenerationSummaryOut(
            id=row["id"],
            scene_id=row["scene_id"],
            model=row["model"],
            cost_usd_cents=row["cost_usd_cents"],
            reserved_cost_usd_cents=row["reserved_cost_usd_cents"],
            actual_cost_usd_cents=row["actual_cost_usd_cents"],
            state=row["state"],
            error_text=row["error_text"],
            completed_at=row["completed_at"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.post("/panels/{panel_id}/generate", response_model=GenerationOut, status_code=201)
def generate_panel(
    panel_id: int,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    provider: ImageProvider = Depends(get_provider),
):
    try:
        scene = SceneService(conn, settings).get(panel_id)
        outcome = GenerationService(conn, storage, settings, provider).generate(
            panel_id,
            model=scene.model,
            image_size=scene.image_size,
            idempotency_key=idempotency_key,
        )
    except (SceneError, GenerationError, CostError, ImageStorageError) as exc:
        _raise_for(exc)
    row = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (outcome.generation_id,)
    ).fetchone()
    if outcome.replayed:
        response.status_code = 200
    return _generation_out(conn, row)


# ---------------------------------------------------------------------------
# generations / candidates
# ---------------------------------------------------------------------------


@router.get("/generations/{generation_id}", response_model=GenerationOut)
def get_generation(generation_id: int, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM generation WHERE id = ?", (generation_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"generation {generation_id} not found",
                "type": "GenerationNotFoundError",
            },
        )
    return _generation_out(conn, row)


@router.post("/candidates/{candidate_id}/review", response_model=CandidateOut)
def review_candidate(candidate_id: int, payload: CandidateReviewIn, conn=Depends(get_conn)):
    if payload.verdict not in {"accepted", "rejected"}:
        raise HTTPException(
            status_code=422,
            detail={"message": "verdict must be 'accepted' or 'rejected'", "type": "ValidationError"},
        )
    cursor = conn.execute(
        "UPDATE candidate SET review_status = ? WHERE id = ?", (payload.verdict, candidate_id)
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise HTTPException(
            status_code=404,
            detail={"message": f"candidate {candidate_id} not found", "type": "CandidateNotFoundError"},
        )
    conn.commit()
    row = conn.execute("SELECT * FROM candidate WHERE id = ?", (candidate_id,)).fetchone()
    return _candidate_out(row)


@router.get("/candidates/{candidate_id}/content")
def candidate_content(candidate_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    row = conn.execute("SELECT sha256 FROM candidate WHERE id = ?", (candidate_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"message": f"candidate {candidate_id} not found", "type": "CandidateNotFoundError"},
        )
    return _serve_stored_image(row["sha256"], storage)
