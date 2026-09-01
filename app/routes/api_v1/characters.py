"""Character endpoints for the /api/v1 JSON API."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import _character_out, _raise_for
from app.schemas import Character, CharacterInput
from app.services.characters import CharacterError, CharacterNotFoundError, CharacterService
from app.storage import ImageStorage

router = APIRouter(prefix="/api/v1", tags=["api-v1-characters"])


@router.get("/characters", response_model=list[Character])
def list_characters(conn=Depends(get_conn), storage=Depends(get_storage)):
    return [_character_out(conn, storage, c) for c in CharacterService(conn).list()]


@router.post("/characters", response_model=Character, status_code=201)
def create_character(payload: CharacterInput, conn=Depends(get_conn), storage=Depends(get_storage)):
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


@router.get("/characters/{character_id}", response_model=Character)
def get_character(character_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    try:
        character = CharacterService(conn).get(character_id)
    except CharacterNotFoundError as exc:
        _raise_for(exc)
    return _character_out(conn, storage, character)


@router.put("/characters/{character_id}", response_model=Character)
def update_character(
    character_id: int, payload: CharacterInput, conn=Depends(get_conn), storage=Depends(get_storage)
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