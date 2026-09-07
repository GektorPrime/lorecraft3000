"""Scene endpoints for the /api/v1 JSON API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response

from app.deps import get_conn, get_provider, get_storage, settings
from app.providers.base import ImageProvider
from app.routes.api_v1._common import (
    TIMEZONE_HEADER,
    _attachment_out,
    _candidate_out,
    _generation_out,
    _scene_out,
    _raise_for,
)
from app.schemas import (
    Generation,
    GenerationCreate,
    GenerationSummary,
    Scene,
    SceneInput,
    SceneModelInput,
    ScenePreview,
)
from app.services.costs import CostError, CostLedger
from app.services.generation import GenerationError, GenerationService
from app.services.scenes import SceneError, SceneNotFoundError, SceneService
from app.storage import ImageStorageError

router = APIRouter(prefix="/api/v1", tags=["api-v1-scenes"])


def _cast_to_dicts(cast) -> list[dict]:
    return [
        {
            "character_id": c.character_id,
            "role": c.role,
            "prominence": c.prominence,
            "base_stage_target_id": c.base_stage_target_id,
        }
        for c in cast
    ]


@router.get("/scenes", response_model=list[Scene])
def list_scenes(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [_scene_out(conn, storage, s) for s in SceneService(conn, settings).list()]


@router.post("/scenes", response_model=Scene, status_code=201)
def create_scene(payload: SceneInput, conn=Depends(get_conn), storage=Depends(get_storage)):
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
            base_stage_id=payload.base_stage_id,
        )
    except SceneError as exc:
        _raise_for(exc)
    return _scene_out(conn, storage, scene)


@router.get("/scenes/{scene_id}", response_model=Scene)
def get_scene(scene_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).get(scene_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    return _scene_out(conn, storage, scene)


@router.put("/scenes/{scene_id}", response_model=Scene)
def update_scene(scene_id: int, payload: SceneInput, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).update(
            scene_id,
            beat_text=payload.beat_text,
            camera=payload.camera,
            framing=payload.framing,
            mood=payload.mood,
            aspect_ratio=payload.aspect_ratio,
            cast=_cast_to_dicts(payload.cast),
            style_id=payload.style_id,
            model=payload.model,
            image_size=payload.image_size,
            base_stage_id=payload.base_stage_id,
        )
    except SceneError as exc:
        _raise_for(exc)
    return _scene_out(conn, storage, scene)


@router.patch("/scenes/{scene_id}/model", response_model=Scene)
def update_scene_model(
    scene_id: int,
    payload: SceneModelInput,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    try:
        scene = SceneService(conn, settings).update_model(scene_id, model=payload.model)
    except SceneError as exc:
        _raise_for(exc)
    return _scene_out(conn, storage, scene)


@router.post("/scenes/{scene_id}/duplicate", response_model=Scene, status_code=201)
def duplicate_scene(scene_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        scene = SceneService(conn, settings).duplicate(scene_id)
    except SceneError as exc:
        _raise_for(exc)
    return _scene_out(conn, storage, scene)


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    """Permanently delete a scene and its full generation history."""
    try:
        SceneService(conn, settings).delete(scene_id)
    except SceneError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.get("/scenes/{scene_id}/preview", response_model=ScenePreview)
def preview_scene(
    scene_id: int,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    timezone_name: str | None = Header(default=None, alias=TIMEZONE_HEADER),
):
    scenes = SceneService(conn, settings)
    try:
        scene = scenes.get(scene_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    try:
        preview = GenerationService(conn, storage, settings, None).preview(
            scene_id,
            model=scene.model,
            image_size=scene.image_size,
            tz_name=timezone_name,
        )
    except (GenerationError, CostError, ImageStorageError) as exc:
        return ScenePreview(
            scene_id=scene_id,
            model=scene.model,
            image_size=scene.image_size,
            prompt="",
            prompt_hash="",
            attachments=[],
            warnings=[],
            estimated_cost_cents=0,
            spent_today_cents=CostLedger(conn, settings).spent_today(timezone_name),
            remaining_after_cents=0,
            can_generate=False,
            blocked_reason=str(exc),
            base_stage_id=scene.base_stage_id,
            source_content_url=(
                f"/api/v1/base-stages/{scene.base_stage_id}/content"
                if scene.base_stage_id is not None
                else None
            ),
        )
    return ScenePreview(
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
        base_stage_id=scene.base_stage_id,
        source_content_url=(
            f"/api/v1/base-stages/{scene.base_stage_id}/content"
            if scene.base_stage_id is not None
            else None
        ),
    )


@router.get("/scenes/{scene_id}/generations", response_model=list[GenerationSummary])
def list_scene_generations(scene_id: int, conn=Depends(get_conn)) -> list[GenerationSummary]:
    try:
        SceneService(conn, settings).get(scene_id)
    except SceneNotFoundError as exc:
        _raise_for(exc)
    service = GenerationService(conn, None, settings, None)
    rows_with_candidates = service.list_for_scene_with_candidates(scene_id)
    return [
        GenerationSummary(
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
            candidates=[_candidate_out(c) for c in candidates],
        )
        for row, candidates in rows_with_candidates
    ]


@router.post("/scenes/{scene_id}/generate", response_model=Generation, status_code=201)
def generate_scene(
    scene_id: int,
    payload: GenerationCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    provider: ImageProvider = Depends(get_provider),
):
    try:
        SceneService(conn, settings).get(scene_id)
        outcome = GenerationService(conn, storage, settings, provider).generate(
            scene_id,
            idempotency_key=idempotency_key,
            expected_prompt_hash=payload.expected_prompt_hash,
        )
    except (SceneError, GenerationError, CostError, ImageStorageError) as exc:
        _raise_for(exc)
    service = GenerationService(conn, storage, settings, provider)
    row, candidates = service.get_with_candidates(outcome.generation_id)
    if outcome.replayed:
        response.status_code = 200
    return _generation_out(row, candidates)
