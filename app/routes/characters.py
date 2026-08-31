"""Character library routes: list, create, edit, detail (HTMX pages)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_conn, get_storage, templates
from app.services.characters import (
    CharacterError,
    CharacterNotFoundError,
    CharacterService,
    SlugCollisionError,
    VisualContractTooLongError,
)
from app.services.ref_sets import RefSetService
from app.services.styles import StyleService
from app.storage import ImageStorage

router = APIRouter(prefix="/characters", tags=["characters"])


def _parse_style_id(raw: str) -> int | None:
    """Parse the default_style_id form field ('' -> None)."""
    if not raw or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise CharacterError("default_style_id must be an integer") from exc


def _values_from_form(
    name: str,
    slug: str,
    lore_md: str,
    visual_contract: str,
    negative_traits: str,
    default_style_id: str,
) -> dict:
    try:
        parsed_style_id: int | str | None = _parse_style_id(default_style_id)
    except CharacterError:
        parsed_style_id = default_style_id
    return {
        "name": name,
        "slug": slug,
        "lore_md": lore_md,
        "visual_contract": visual_contract,
        "negative_traits": negative_traits,
        "default_style_id": parsed_style_id,
    }


def _values_from_character(character) -> dict:
    return {
        "name": character.name,
        "slug": character.slug,
        "lore_md": character.lore_md,
        "visual_contract": character.visual_contract,
        "negative_traits": character.negative_traits,
        "default_style_id": character.default_style_id,
    }


@router.get("", response_class=HTMLResponse)
def list_characters(
    request: Request, conn=Depends(get_conn)
) -> HTMLResponse:
    service = CharacterService(conn)
    styles = {s.id: s for s in StyleService(conn).list()}
    return templates.TemplateResponse(
        request,
        "characters/list.html",
        {"characters": service.list(), "styles": styles},
    )


@router.get("/new", response_class=HTMLResponse)
def new_character_form(request: Request, conn=Depends(get_conn)) -> HTMLResponse:
    styles = StyleService(conn).list()
    return templates.TemplateResponse(
        request,
        "characters/form.html",
        {
            "character": None,
            "styles": styles,
            "error": None,
            "values": {
                "name": "",
                "slug": "",
                "lore_md": "",
                "visual_contract": "",
                "negative_traits": "",
                "default_style_id": None,
            },
        },
    )


@router.post("")
def create_character(
    request: Request,
    name: str = Form(...),
    slug: str = Form(""),
    lore_md: str = Form(""),
    visual_contract: str = Form(""),
    negative_traits: str = Form(""),
    default_style_id: str = Form(""),
    conn=Depends(get_conn),
):
    service = CharacterService(conn)
    try:
        character = service.create(
            name=name,
            slug=slug or None,
            lore_md=lore_md,
            visual_contract=visual_contract,
            negative_traits=negative_traits,
            default_style_id=_parse_style_id(default_style_id),
        )
    except (SlugCollisionError, VisualContractTooLongError, CharacterError) as exc:
        styles = StyleService(conn).list()
        return templates.TemplateResponse(
            request,
            "characters/form.html",
            {
                "character": None,
                "styles": styles,
                "error": str(exc),
                "values": _values_from_form(
                    name, slug, lore_md, visual_contract, negative_traits, default_style_id
                ),
            },
            status_code=422,
        )
    return RedirectResponse(f"/characters/{character.id}", status_code=303)


@router.post("/{character_id}/ref-sets")
def create_ref_set_draft(
    character_id: int,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
):
    """Create a new DRAFT ref-set for a character (next version)."""
    try:
        CharacterService(conn).get(character_id)
    except CharacterNotFoundError:
        return HTMLResponse("Character not found", status_code=404)
    draft = RefSetService(conn, storage).create_draft(character_id)
    return RedirectResponse(f"/ref-sets/{draft.id}", status_code=303)


@router.get("/{character_id}", response_class=HTMLResponse)
def character_detail(
    character_id: int,
    request: Request,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
) -> HTMLResponse:
    service = CharacterService(conn)
    try:
        character = service.get(character_id)
    except CharacterNotFoundError:
        return HTMLResponse("Character not found", status_code=404)

    style_service = StyleService(conn)
    default_style = (
        style_service.get(character.default_style_id)
        if character.default_style_id is not None
        else None
    )
    ref_sets = RefSetService(conn, storage).list_for_character(character_id)
    return templates.TemplateResponse(
        request,
        "characters/detail.html",
        {
            "character": character,
            "default_style": default_style,
            "ref_sets": ref_sets,
        },
    )


@router.get("/{character_id}/edit", response_class=HTMLResponse)
def edit_character_form(
    character_id: int, request: Request, conn=Depends(get_conn)
) -> HTMLResponse:
    service = CharacterService(conn)
    try:
        character = service.get(character_id)
    except CharacterNotFoundError:
        return HTMLResponse("Character not found", status_code=404)
    styles = StyleService(conn).list()
    return templates.TemplateResponse(
        request,
        "characters/form.html",
        {
            "character": character,
            "styles": styles,
            "error": None,
            "values": _values_from_character(character),
        },
    )


@router.post("/{character_id}/edit")
def update_character(
    character_id: int,
    request: Request,
    name: str = Form(...),
    slug: str = Form(""),
    lore_md: str = Form(""),
    visual_contract: str = Form(""),
    negative_traits: str = Form(""),
    default_style_id: str = Form(""),
    conn=Depends(get_conn),
):
    service = CharacterService(conn)
    try:
        existing = service.get(character_id)
    except CharacterNotFoundError:
        return HTMLResponse("Character not found", status_code=404)
    try:
        character = service.update(
            character_id,
            name=name,
            slug=slug or None,
            lore_md=lore_md,
            visual_contract=visual_contract,
            negative_traits=negative_traits,
            default_style_id=_parse_style_id(default_style_id),
        )
    except (SlugCollisionError, VisualContractTooLongError, CharacterError) as exc:
        styles = StyleService(conn).list()
        return templates.TemplateResponse(
            request,
            "characters/form.html",
            {
                # The existing entity keeps the form on the EDIT action so a
                # corrected retry updates this character instead of creating a
                # duplicate; values below preserve the user's submission.
                "character": existing,
                "styles": styles,
                "error": str(exc),
                "values": _values_from_form(
                    name, slug, lore_md, visual_contract, negative_traits, default_style_id
                ),
            },
            status_code=422,
        )
    return RedirectResponse(f"/characters/{character.id}", status_code=303)
