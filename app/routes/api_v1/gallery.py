"""Merged candidate gallery and user-uploaded picture endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import (
    ALLOWED_UPLOAD_MIME,
    MAX_UPLOAD_BYTES,
    _raise_for,
    _serve_stored_image,
)
from app.schemas import GalleryItem, GalleryPicture, ImageDimensions
from app.services.candidates import CandidateService
from app.services.gallery import (
    GalleryPictureError,
    GalleryPictureService,
    GalleryPictureValidationError,
)
from app.storage import ImageStorageError

router = APIRouter(prefix="/api/v1", tags=["api-v1-gallery"])


def _picture_out(picture) -> GalleryPicture:
    return GalleryPicture(
        id=picture.id,
        title=picture.title,
        original_filename=picture.original_filename,
        dimensions=ImageDimensions(width=picture.image_width, height=picture.image_height),
        created_at=picture.created_at,
        archived_at=picture.archived_at,
        content_url=f"/api/v1/gallery-pictures/{picture.id}/content",
    )


@router.get("/gallery", response_model=list[GalleryItem])
def list_gallery(conn=Depends(get_conn), storage=Depends(get_storage)):
    items = [
        GalleryItem(
            source_type="candidate",
            source_id=row["candidate_id"],
            candidate_id=row["candidate_id"],
            gallery_picture_id=None,
            content_url=f"/api/v1/candidates/{row['candidate_id']}/content",
            scene_id=row["scene_id"],
            description=row["beat_text"],
            beat_text=row["beat_text"],
            aspect_ratio=row["aspect_ratio"],
            created_at=row["created_at"],
        )
        for row in CandidateService(conn).list_accepted()
    ]
    service = GalleryPictureService(conn, storage)
    items.extend(
        GalleryItem(
            source_type="upload",
            source_id=picture.id,
            candidate_id=None,
            gallery_picture_id=picture.id,
            content_url=f"/api/v1/gallery-pictures/{picture.id}/content",
            scene_id=None,
            description=picture.title,
            aspect_ratio=service.aspect_ratio(picture),
            created_at=picture.created_at,
        )
        for picture in service.list()
    )
    return sorted(items, key=lambda item: (item.created_at, item.source_id), reverse=True)


@router.post("/gallery-pictures", response_model=GalleryPicture, status_code=201)
def upload_gallery_picture(
    title: str = Form(...),
    image: UploadFile = File(...),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
):
    if image.content_type not in ALLOWED_UPLOAD_MIME:
        _raise_for(GalleryPictureValidationError("upload must be a PNG, JPEG, or WebP image"))
    data = image.file.read(MAX_UPLOAD_BYTES + 1) if image.file else b""
    if len(data) > MAX_UPLOAD_BYTES:
        _raise_for(GalleryPictureValidationError("upload exceeds the 10 MB limit"))
    try:
        picture = GalleryPictureService(conn, storage).upload(
            data, title, original_filename=image.filename
        )
    except GalleryPictureError as exc:
        _raise_for(exc)
    return _picture_out(picture)


@router.get("/gallery-pictures/{picture_id}/content")
def gallery_picture_content(
    picture_id: int, conn=Depends(get_conn), storage=Depends(get_storage)
):
    try:
        sha256 = GalleryPictureService(conn, storage).content_sha(picture_id)
        return _serve_stored_image(sha256, storage)
    except (GalleryPictureError, ImageStorageError) as exc:
        _raise_for(exc)


@router.delete("/gallery-pictures/{picture_id}", status_code=204)
def archive_gallery_picture(
    picture_id: int, conn=Depends(get_conn), storage=Depends(get_storage)
):
    try:
        GalleryPictureService(conn, storage).archive(picture_id)
    except GalleryPictureError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/gallery-pictures/{picture_id}/restore", response_model=GalleryPicture)
def restore_gallery_picture(
    picture_id: int, conn=Depends(get_conn), storage=Depends(get_storage)
):
    try:
        return _picture_out(GalleryPictureService(conn, storage).restore(picture_id))
    except GalleryPictureError as exc:
        _raise_for(exc)
