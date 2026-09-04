"""Shared helpers for the /api/v1 resource routers.

Every resource router (app/routes/api_v1/*.py) uses these error mapping helpers,
DTO builders, and upload limits so the split routers behave exactly like the
former single router in app/routes/api_v1.py.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import Response

from app.deps import settings
from app.services.avatars import AvatarService

# Browser timezone (IANA name) used to compute the user-local daily budget
# boundary. Supplied by the React client; absent/invalid values fall back to
# UTC so the server never depends on its own system timezone.
TIMEZONE_HEADER = "X-Timezone"
from app.services.candidates import CandidateError, CandidateNotFoundError
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
    GenerationPendingError,
    IdempotencyConflictError,
    SceneChangedError,
    UnknownPriceError,
)
from app.services.generation import GenerationError, GenerationNotFoundError, PreviewChangedError
from app.services.ref_sets import (
    ImageRejectedError,
    InvalidRoleError,
    RefImageNotFoundError,
    RefSetError,
    RefSetNotDraftError,
    RefSetNotFoundError,
    RefSetService,
)
from app.services.scenes import SceneError, SceneImmutableError, SceneNotFoundError, SceneService
from app.services.styles import (
    StyleArchivedError,
    StyleError,
    StyleNameCollisionError,
    StyleNotFoundError,
    StyleService,
)
from app.storage import ImageStorage, ImageStorageError

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
    "generation locks its visual definition. The model for future attempts "
    "can still be changed from Preview when no generation is in progress. "
    "Use Duplicate to change the remaining fields while keeping the original "
    "and its complete attempt history."
)

# Most-specific error types must be listed before their base classes so the
# mapper picks the intended status code (e.g. GenerationNotFoundError (404)
# before GenerationError (422)).
_ERROR_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (CharacterNotFoundError, 404),
    (StyleNotFoundError, 404),
    (RefSetNotFoundError, 404),
    (RefImageNotFoundError, 404),
    (SceneNotFoundError, 404),
    (GenerationNotFoundError, 404),
    (CandidateNotFoundError, 404),
    (SlugCollisionError, 409),
    (StyleNameCollisionError, 409),
    (StyleArchivedError, 409),
    (RefSetNotDraftError, 409),
    (SceneImmutableError, 409),
    (GenerationPendingError, 409),
    (IdempotencyConflictError, 409),
    (SceneChangedError, 409),
    (PreviewChangedError, 409),
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
    (CandidateError, 422),
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


def raise_not_found(message: str, exc_type_name: str = "NotFoundError") -> None:
    """Raise the standard 404 error envelope for a missing resource."""
    raise HTTPException(
        status_code=404,
        detail={"message": message, "type": exc_type_name},
    )


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


def _ref_image_out(image) -> "RefImage":
    from app.schemas import RefImage

    return RefImage(
        id=image.id,
        ref_set_id=image.ref_set_id,
        role=image.role,
        weight=image.weight,
        quality_flags=image.quality_flags,
        created_at=image.created_at,
        content_url=f"/api/v1/ref-images/{image.id}/content",
    )


def _ref_set_out(ref_set, images) -> "RefSet":
    from app.schemas import RefSet

    return RefSet(
        id=ref_set.id,
        character_id=ref_set.character_id,
        version=ref_set.version,
        status=ref_set.status,
        created_at=ref_set.created_at,
        images=[_ref_image_out(img) for img in images],
    )


def _character_out(conn, storage: ImageStorage, character) -> "Character":
    from app.schemas import Character

    canonical = RefSetService(conn, storage).get_canonical(character.id)
    avatar = AvatarService(conn, storage).avatar_image_for(character.id)
    return Character(
        id=character.id,
        name=character.name,
        slug=character.slug,
        lore_md=character.lore_md,
        visual_contract=character.visual_contract,
        negative_traits=character.negative_traits,
        default_style_id=character.default_style_id,
        created_at=character.created_at,
        archived_at=character.archived_at,
        has_canonical_ref_set=canonical is not None,
        avatar_url=f"/api/v1/ref-images/{avatar.id}/content" if avatar else None,
        avatar_initials=_initials(character.name),
    )


def _cast_member_out(conn, storage: ImageStorage, entry: dict) -> "CastMember":
    from app.schemas import CastMember

    character_id = int(entry["character_id"])
    try:
        name = CharacterService(conn).get(character_id).name
    except CharacterNotFoundError:
        name = f"Unknown character #{character_id}"
    avatar = AvatarService(conn, storage).avatar_image_for(character_id)
    return CastMember(
        character_id=character_id,
        role=str(entry.get("role", "")),
        prominence=int(entry.get("prominence", 1)),
        name=name,
        avatar_url=f"/api/v1/ref-images/{avatar.id}/content" if avatar else None,
        avatar_initials=_initials(name),
    )


def _panel_out(conn, storage: ImageStorage, scene) -> "Panel":
    from app.schemas import Panel

    scenes = SceneService(conn, settings)
    return Panel(
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


def _attachment_out(attachment: dict) -> "GenerationAttachment":
    from app.schemas import GenerationAttachment

    return GenerationAttachment(
        image_number=attachment["image_number"],
        character_id=attachment["character_id"],
        character_name=attachment["character_name"],
        ref_set_id=attachment["ref_set_id"],
        ref_set_version=attachment["ref_set_version"],
        role=attachment["role"],
    )


def _candidate_out(row) -> "Candidate":
    from app.schemas import Candidate

    identity_scores = None
    raw = row["identity_scores"]
    if raw:
        try:
            identity_scores = json.loads(raw)
        except json.JSONDecodeError:
            identity_scores = None
    return Candidate(
        id=row["id"],
        generation_id=row["generation_id"],
        idx=row["idx"],
        review_status=row["review_status"],
        content_url=f"/api/v1/candidates/{row['id']}/content",
        created_at=row["created_at"],
        identity_scores=identity_scores,
    )


def _generation_out(row, candidates) -> "Generation":
    from app.schemas import Generation

    request_data = json.loads(row["request_json"] or "{}")
    warnings = list(request_data.get("warnings", []))
    if row["warning_text"]:
        warnings.append(row["warning_text"])
    return Generation(
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
