"""Style bible routes: list, create, edit (HTMX pages)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_conn, templates
from app.services.styles import (
    StyleError,
    StyleNameCollisionError,
    StyleNotFoundError,
    StyleService,
)

router = APIRouter(prefix="/styles", tags=["styles"])


def _parse_ref_image_ids(raw: str) -> list[int]:
    """Parse the comma-separated ref_image_ids form field into ints."""
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise StyleError(
                f"ref_image_ids must be comma-separated integers, got '{part}'"
            )
    return ids


def _values_from_form(name: str, style_contract: str, ref_image_ids: str) -> dict:
    return {
        "name": name,
        "style_contract": style_contract,
        "ref_image_ids": ref_image_ids,
    }


def _values_from_style(style) -> dict:
    return {
        "name": style.name,
        "style_contract": style.style_contract,
        "ref_image_ids": ", ".join(str(i) for i in style.ref_image_ids),
    }


@router.get("", response_class=HTMLResponse)
def list_styles(request: Request, conn=Depends(get_conn)) -> HTMLResponse:
    service = StyleService(conn)
    return templates.TemplateResponse(
        request, "styles/list.html", {"styles": service.list()}
    )


@router.get("/new", response_class=HTMLResponse)
def new_style_form(request: Request, conn=Depends(get_conn)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "styles/form.html",
        {
            "style": None,
            "error": None,
            "values": {"name": "", "style_contract": "", "ref_image_ids": ""},
        },
    )


@router.post("")
def create_style(
    request: Request,
    name: str = Form(...),
    style_contract: str = Form(""),
    ref_image_ids: str = Form(""),
    conn=Depends(get_conn),
):
    service = StyleService(conn)
    try:
        style = service.create(
            name=name,
            style_contract=style_contract,
            ref_image_ids=_parse_ref_image_ids(ref_image_ids),
        )
    except (StyleNameCollisionError, StyleError) as exc:
        return templates.TemplateResponse(
            request,
            "styles/form.html",
            {
                "style": None,
                "error": str(exc),
                "values": _values_from_form(name, style_contract, ref_image_ids),
            },
            status_code=422,
        )
    return RedirectResponse("/styles", status_code=303)


@router.get("/{style_id}/edit", response_class=HTMLResponse)
def edit_style_form(
    style_id: int, request: Request, conn=Depends(get_conn)
) -> HTMLResponse:
    service = StyleService(conn)
    try:
        style = service.get(style_id)
    except StyleNotFoundError:
        return HTMLResponse("Style not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "styles/form.html",
        {
            "style": style,
            "error": None,
            "values": _values_from_style(style),
        },
    )


@router.post("/{style_id}/edit")
def update_style(
    style_id: int,
    request: Request,
    name: str = Form(...),
    style_contract: str = Form(""),
    ref_image_ids: str = Form(""),
    conn=Depends(get_conn),
):
    service = StyleService(conn)
    try:
        style = service.get(style_id)
    except StyleNotFoundError:
        return HTMLResponse("Style not found", status_code=404)
    try:
        service.update(
            style_id,
            name=name,
            style_contract=style_contract,
            ref_image_ids=_parse_ref_image_ids(ref_image_ids),
        )
    except (StyleNameCollisionError, StyleError) as exc:
        return templates.TemplateResponse(
            request,
            "styles/form.html",
            {
                # The existing entity keeps the form on the EDIT action so a
                # corrected retry updates this style instead of creating a
                # duplicate; values below preserve the user's submission.
                "style": style,
                "error": str(exc),
                "values": _values_from_form(name, style_contract, ref_image_ids),
            },
            status_code=422,
        )
    return RedirectResponse("/styles", status_code=303)