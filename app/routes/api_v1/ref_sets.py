"""Reference-set and reference-image endpoints for the /api/v1 JSON API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import (
    ALLOWED_UPLOAD_MIME,
    MAX_UPLOAD_BYTES,
    _raise_for,
    _ref_image_out,
    _ref_set_out,
    _serve_stored_image,
)
from app.schemas import RefImage, RefImageRoleUpdate, RefSet, RefSetSummary
from app.services.characters import CharacterNotFoundError, CharacterService
from app.services.ref_sets import (
    ImageRejectedError,
    RefSetError,
    RefSetNotFoundError,
    RefSetService,
)
from app.storage import ImageStorage

router = APIRouter(prefix="/api/v1", tags=["api-v1-ref-sets"])


@router.get("/characters/{character_id}/ref-sets", response_model=list[RefSetSummary])
def list_ref_sets(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    summaries = RefSetService(conn, storage).list_for_character(character_id)
    return [
        RefSetSummary(
            id=s.ref_set.id,
            character_id=s.ref_set.character_id,
            version=s.ref_set.version,
            status=s.ref_set.status,
            created_at=s.ref_set.created_at,
            image_count=s.image_count,
        )
        for s in summaries
    ]


@router.post("/characters/{character_id}/ref-sets", response_model=RefSet, status_code=201)
def create_ref_set_draft(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    service = RefSetService(conn, storage)
    draft = service.create_draft(character_id)
    return _ref_set_out(draft, service.images(draft.id))


@router.get("/ref-sets/{ref_set_id}", response_model=RefSet)
def get_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        ref_set = service.get(ref_set_id)
    except RefSetNotFoundError as exc:
        _raise_for(exc)
    return _ref_set_out(ref_set, service.images(ref_set_id))


@router.post("/ref-sets/{ref_set_id}/copy", response_model=RefSet, status_code=201)
def copy_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        new_draft = service.copy_to_new_draft(ref_set_id)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_set_out(new_draft, service.images(new_draft.id))


@router.post("/ref-sets/{ref_set_id}/promote", response_model=RefSet)
def promote_ref_set(ref_set_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = RefSetService(conn, storage)
    try:
        promoted = service.promote(ref_set_id)
    except RefSetError as exc:
        _raise_for(exc)
    return _ref_set_out(promoted, service.images(ref_set_id))


@router.post("/ref-sets/{ref_set_id}/images", response_model=RefImage, status_code=201)
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


@router.patch("/ref-sets/{ref_set_id}/images/{image_id}", response_model=RefImage)
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
    try:
        sha256 = RefSetService(conn, storage).content_sha(image_id)
    except RefSetError as exc:
        _raise_for(exc)
    return _serve_stored_image(sha256, storage)