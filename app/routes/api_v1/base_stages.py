"""Upload-first Base Stage endpoints for the /api/v1 JSON API."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import (
    ALLOWED_UPLOAD_MIME,
    MAX_UPLOAD_BYTES,
    _base_stage_out,
    _raise_for,
    _serve_stored_image,
)
from app.schemas import BaseStage
from app.services.base_stages import (
    BaseStageError,
    BaseStageService,
    BaseStageValidationError,
)

router = APIRouter(prefix="/api/v1/base-stages", tags=["api-v1-base-stages"])


@router.get("", response_model=list[BaseStage])
def list_base_stages(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [_base_stage_out(stage) for stage in BaseStageService(conn, storage).list()]


@router.get("/archived", response_model=list[BaseStage])
def list_archived_base_stages(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [
        _base_stage_out(stage)
        for stage in BaseStageService(conn, storage).list_archived()
    ]


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
    try:
        stage = BaseStageService(conn, storage).upload(
            data,
            description,
            parsed_targets,
            source_name=image.filename,
        )
    except BaseStageError as exc:
        _raise_for(exc)
    return _base_stage_out(stage)


@router.get("/{base_stage_id}", response_model=BaseStage)
def get_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        stage = BaseStageService(conn, storage).get(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _base_stage_out(stage)


@router.delete("/{base_stage_id}", status_code=204)
def archive_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        BaseStageService(conn, storage).archive(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/{base_stage_id}/restore", response_model=BaseStage)
def restore_base_stage(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        stage = BaseStageService(conn, storage).restore(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _base_stage_out(stage)


@router.get("/{base_stage_id}/content")
def base_stage_content(base_stage_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        sha256 = BaseStageService(conn, storage).content_sha(base_stage_id)
    except BaseStageError as exc:
        _raise_for(exc)
    return _serve_stored_image(sha256, storage)
