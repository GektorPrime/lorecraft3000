"""Style endpoints for the /api/v1 JSON API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.deps import get_conn
from app.routes.api_v1._common import _raise_for
from app.schemas import Style, StyleInput
from app.services.styles import (
    StyleError,
    StyleNotFoundError,
    StyleService,
)

router = APIRouter(prefix="/api/v1", tags=["api-v1-styles"])


@router.get("/styles", response_model=list[Style])
def list_styles(conn=Depends(get_conn)):
    return [Style(**s.__dict__) for s in StyleService(conn).list()]


@router.get("/styles/archived", response_model=list[Style])
def list_archived_styles(conn=Depends(get_conn)):
    return [Style(**s.__dict__) for s in StyleService(conn).list_archived()]


@router.post("/styles", response_model=Style, status_code=201)
def create_style(payload: StyleInput, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).create(
            name=payload.name,
            style_contract=payload.style_contract,
        )
    except StyleError as exc:
        _raise_for(exc)
    return Style(**style.__dict__)


@router.get("/styles/{style_id}", response_model=Style)
def get_style(style_id: int, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).get(style_id)
    except StyleNotFoundError as exc:
        _raise_for(exc)
    return Style(**style.__dict__)


@router.delete("/styles/{style_id}", status_code=204)
def archive_style(style_id: int, conn=Depends(get_conn)):
    """Archive (soft-delete) a style. Existing panels keep referencing it."""
    try:
        StyleService(conn).archive(style_id)
    except StyleError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/styles/{style_id}/restore", response_model=Style)
def restore_style(style_id: int, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).restore(style_id)
    except StyleError as exc:
        _raise_for(exc)
    return Style(**style.__dict__)


@router.put("/styles/{style_id}", response_model=Style)
def update_style(style_id: int, payload: StyleInput, conn=Depends(get_conn)):
    try:
        style = StyleService(conn).update(
            style_id,
            name=payload.name,
            style_contract=payload.style_contract,
        )
    except StyleError as exc:
        _raise_for(exc)
    return Style(**style.__dict__)