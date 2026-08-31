"""Reference-set workflow routes (Milestone 5, HTMX pages).

Image add/remove/re-role are HTMX interactions that swap the #ref-images
fragment; draft creation, promotion, and copy are page-level transitions that
redirect.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_conn, get_storage, templates
from app.services.characters import CharacterNotFoundError, CharacterService
from app.services.ref_sets import RefSetError, RefSetNotFoundError, RefSetService
from app.storage import ImageStorage

router = APIRouter(prefix="/ref-sets", tags=["ref-sets"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_UPLOAD_MIME = {"image/png", "image/jpeg", "image/webp"}


def _images_fragment(
    request: Request, service: RefSetService, ref_set_id: int, error: str | None = None
) -> HTMLResponse:
    """Render the HTMX-swappable image list + upload form fragment."""
    ref_set = service.get(ref_set_id)
    images = service.images(ref_set_id)
    return templates.TemplateResponse(
        request,
        "ref_sets/_images.html",
        {"ref_set": ref_set, "images": images, "error": error},
    )


@router.get("/{ref_set_id}", response_class=HTMLResponse)
def ref_set_detail(
    ref_set_id: int,
    request: Request,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
) -> HTMLResponse:
    service = RefSetService(conn, storage)
    try:
        ref_set = service.get(ref_set_id)
    except RefSetNotFoundError:
        return HTMLResponse("Ref-set not found", status_code=404)

    character = CharacterService(conn).get(ref_set.character_id)
    canonical = service.get_canonical(ref_set.character_id)
    return templates.TemplateResponse(
        request,
        "ref_sets/detail.html",
        {
            "ref_set": ref_set,
            "character": character,
            "canonical": canonical,
            "images": service.images(ref_set_id),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/{ref_set_id}/images")
def upload_image(
    ref_set_id: int,
    request: Request,
    image: UploadFile = File(...),
    role: str = Form(...),
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
) -> HTMLResponse:
    """Upload image bytes into a draft and assign a role (HTMX fragment)."""
    service = RefSetService(conn, storage)
    error: str | None = None
    try:
        if image.content_type not in ALLOWED_UPLOAD_MIME:
            raise RefSetError("upload must be a PNG, JPEG, or WebP image")
        data = image.file.read(MAX_UPLOAD_BYTES + 1) if image.file else b""
        if len(data) > MAX_UPLOAD_BYTES:
            raise RefSetError("upload exceeds the 10 MB limit")
        service.add_image(ref_set_id, data, role, source_name=image.filename)
    except RefSetError as exc:
        error = str(exc)
    return _images_fragment(request, service, ref_set_id, error)


@router.post("/{ref_set_id}/images/{image_id}/remove")
def remove_image(
    ref_set_id: int,
    image_id: int,
    request: Request,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
) -> HTMLResponse:
    """Remove an image from a draft (HTMX fragment)."""
    service = RefSetService(conn, storage)
    error: str | None = None
    try:
        service.remove_image(ref_set_id, image_id)
    except RefSetError as exc:
        error = str(exc)
    return _images_fragment(request, service, ref_set_id, error)


@router.post("/{ref_set_id}/images/{image_id}/role")
def set_image_role(
    ref_set_id: int,
    image_id: int,
    request: Request,
    role: str = Form(...),
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
) -> HTMLResponse:
    """Re-role an image inside a draft (HTMX fragment)."""
    service = RefSetService(conn, storage)
    error: str | None = None
    try:
        service.set_image_role(ref_set_id, image_id, role)
    except RefSetError as exc:
        error = str(exc)
    return _images_fragment(request, service, ref_set_id, error)


@router.post("/{ref_set_id}/promote")
def promote_ref_set(
    ref_set_id: int,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
):
    """Promote a draft to canonical (single transaction, retires prior)."""
    service = RefSetService(conn, storage)
    try:
        promoted = service.promote(ref_set_id)
    except RefSetError as exc:
        return RedirectResponse(
            f"/ref-sets/{ref_set_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/characters/{promoted.character_id}", status_code=303)


@router.post("/{ref_set_id}/copy")
def copy_ref_set(
    ref_set_id: int,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
):
    """Copy a set's images into a fresh draft (next version)."""
    service = RefSetService(conn, storage)
    try:
        new_draft = service.copy_to_new_draft(ref_set_id)
    except RefSetError as exc:
        return RedirectResponse(
            f"/ref-sets/{ref_set_id}?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/ref-sets/{new_draft.id}", status_code=303)
