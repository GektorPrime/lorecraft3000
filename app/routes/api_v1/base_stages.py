"""Base Stage endpoints for the /api/v1 JSON API.

Uploaded stages are ready immediately; generated stages are drafts that must be
previewed, generated, and explicitly published before any panel can use them.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import Response

from app.deps import get_conn, get_provider, get_storage, settings
from app.routes.api_v1._common import (
    ALLOWED_UPLOAD_MIME,
    MAX_UPLOAD_BYTES,
    TIMEZONE_HEADER,
    _base_stage_out,
    _candidate_out,
    _generation_out,
    _raise_for,
    _serve_stored_image,
)
from app.schemas import (
    BaseStage,
    BaseStageGeneratedInput,
    BaseStagePreview,
    BaseStagePublishIn,
    Generation,
    GenerationCreate,
    GenerationSummary,
)
from app.services.base_stages import (
    BaseStageError,
    BaseStageService,
    BaseStageValidationError,
)
from app.services.costs import CostError, CostLedger
from app.services.generation import GenerationError, GenerationService
from app.storage import ImageStorageError

router = APIRouter(prefix="/api/v1/base-stages", tags=["api-v1-base-stages"])


def _stage_out(service: BaseStageService, stage) -> BaseStage:
    """Serialize a stage with its editability and attempt count."""
    return _base_stage_out(
        stage,
        is_editable=service.is_editable(stage.id),
        generation_count=len(
            service.conn.execute(
                "SELECT 1 FROM generation WHERE base_stage_id = ?", (stage.id,)
            ).fetchall()
        ),
    )


@router.get("", response_model=list[BaseStage])
def list_base_stages(conn=Depends(get_conn), storage=Depends(get_storage)):
    service = BaseStageService(conn, storage, settings)
    return [_stage_out(service, stage) for stage in service.list()]


@router.get("/archived", response_model=list[BaseStage])
def list_archived_base_stages(conn=Depends(get_conn), storage=Depends(get_storage)):
    service = BaseStageService(conn, storage, settings)
    return [_stage_out(service, stage) for stage in service.list_archived()]


@router.post("/generated", response_model=BaseStage, status_code=201)
def create_generated_base_stage(
    payload: BaseStageGeneratedInput,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.create_generated(
            description=payload.description,
            beat_text=payload.beat_text,
            camera=payload.camera,
            framing=payload.framing,
            mood=payload.mood,
            aspect_ratio=payload.aspect_ratio,
            style_id=payload.style_id,
            model=payload.model,
            image_size=payload.image_size,
            targets=payload.targets,
        )
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.post("/upload", response_model=BaseStage, status_code=201)
def upload_base_stage(
    description: str = Form(...),
    targets: str = Form(...),
    image: UploadFile = File(...),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    if image.content_type not in ALLOWED_UPLOAD_MIME:
        _raise_for(BaseStageValidationError("upload must be a PNG, JPEG, or WebP image"))
    data = image.file.read(MAX_UPLOAD_BYTES + 1) if image.file else b""
    if len(data) > MAX_UPLOAD_BYTES:
        _raise_for(BaseStageValidationError("upload exceeds the 10 MB limit"))
    try:
        parsed_targets = json.loads(targets)
    except (json.JSONDecodeError, TypeError) as exc:
        _raise_for(BaseStageValidationError(f"targets must be valid JSON: {exc}"))
    if not isinstance(parsed_targets, list):
        _raise_for(BaseStageValidationError("targets must be a JSON array of strings"))
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.upload(
            data,
            description,
            parsed_targets,
            source_name=image.filename,
        )
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.get("/{base_stage_id}", response_model=BaseStage)
def get_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.get(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.put("/{base_stage_id}", response_model=BaseStage)
def update_base_stage(
    base_stage_id: int,
    payload: BaseStageGeneratedInput,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.update(
            base_stage_id,
            description=payload.description,
            beat_text=payload.beat_text,
            camera=payload.camera,
            framing=payload.framing,
            mood=payload.mood,
            aspect_ratio=payload.aspect_ratio,
            style_id=payload.style_id,
            model=payload.model,
            image_size=payload.image_size,
            targets=payload.targets,
        )
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.post("/{base_stage_id}/duplicate", response_model=BaseStage, status_code=201)
def duplicate_base_stage(
    base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)
):
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.duplicate(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.delete("/{base_stage_id}", status_code=204)
def archive_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        BaseStageService(conn, storage, settings).archive(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/{base_stage_id}/restore", response_model=BaseStage)
def restore_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.restore(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)


@router.get("/{base_stage_id}/content")
def base_stage_content(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        sha256 = BaseStageService(conn, storage, settings).content_sha(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _serve_stored_image(sha256, storage)


@router.get("/{base_stage_id}/preview", response_model=BaseStagePreview)
def preview_base_stage(
    base_stage_id: int,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    timezone_name: str | None = Header(default=None, alias=TIMEZONE_HEADER),
):
    """Exact no-spend preflight for a generated draft."""
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.get(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    try:
        preview = GenerationService(conn, storage, settings, None).preview_base_stage(
            base_stage_id, tz_name=timezone_name
        )
    except (GenerationError, CostError, ImageStorageError) as exc:
        return BaseStagePreview(
            base_stage_id=base_stage_id,
            model=stage.model or settings.default_model,
            image_size=stage.image_size or settings.default_image_size,
            aspect_ratio=stage.aspect_ratio,
            prompt="",
            prompt_hash="",
            warnings=[],
            estimated_cost_cents=0,
            spent_today_cents=CostLedger(conn, settings).spent_today(timezone_name),
            remaining_after_cents=0,
            can_generate=False,
            blocked_reason=str(exc),
        )
    return BaseStagePreview(
        base_stage_id=base_stage_id,
        model=preview.model,
        image_size=preview.image_size,
        aspect_ratio=stage.aspect_ratio,
        prompt=preview.prompt,
        prompt_hash=preview.prompt_hash,
        warnings=list(preview.warnings),
        estimated_cost_cents=preview.estimated_cost_cents,
        spent_today_cents=preview.spent_today_cents,
        remaining_after_cents=preview.remaining_after_cents,
        can_generate=True,
        blocked_reason=None,
    )


@router.get("/{base_stage_id}/generations", response_model=list[GenerationSummary])
def list_base_stage_generations(
    base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)
) -> list[GenerationSummary]:
    try:
        BaseStageService(conn, storage, settings).get(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    service = GenerationService(conn, storage, settings, None)
    return [
        GenerationSummary(
            id=row["id"],
            scene_id=row["scene_id"],
            base_stage_id=row["base_stage_id"],
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
        for row, candidates in service.list_for_base_stage_with_candidates(base_stage_id)
    ]


@router.post(
    "/{base_stage_id}/generate", response_model=Generation, status_code=201
)
def generate_base_stage(
    base_stage_id: int,
    payload: GenerationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    provider=Depends(get_provider),
):
    """Spend once on a reviewed composition prompt. No identities are involved."""
    try:
        BaseStageService(conn, storage, settings).get(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    service = GenerationService(conn, storage, settings, provider)
    try:
        outcome = service.generate_base_stage(
            base_stage_id,
            idempotency_key=idempotency_key,
            expected_prompt_hash=payload.expected_prompt_hash,
        )
    except (GenerationError, CostError, ImageStorageError) as exc:
        _raise_for(exc)
    row, candidates = service.get_with_candidates(outcome.generation_id)
    return _generation_out(row, candidates)


@router.post("/{base_stage_id}/publish", response_model=BaseStage)
def publish_base_stage(
    base_stage_id: int,
    payload: BaseStagePublishIn,
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    """Promote one succeeded candidate to this stage's permanent source image."""
    service = BaseStageService(conn, storage, settings)
    try:
        stage = service.publish(base_stage_id, payload.candidate_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _stage_out(service, stage)
