"""Panel aggregate and rendered-media endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import _raise_for, _serve_stored_image
from app.schemas import (
    Panel, PanelCreate, PanelRender, PanelRenderCreate, PanelSlot, PanelUpdate,
)
from app.services.panel_rendering import PanelRenderService
from app.services.panels import PanelError, PanelService
from app.storage import ImageStorageError

router = APIRouter(prefix="/api/v1", tags=["api-v1-panels"])


def _render_out(render) -> PanelRender:
    return PanelRender(
        id=render.id, panel_id=render.panel_id, panel_revision=render.panel_revision,
        width=render.width, height=render.height, layout=render.layout,
        created_at=render.created_at,
        content_url=f"/api/v1/panel-renders/{render.id}/content",
        download_url=f"/api/v1/panel-renders/{render.id}/download",
    )


def _panel_out(panel) -> Panel:
    return Panel(
        id=panel.id, title=panel.title, format=panel.format,
        width_px=panel.width_px, height_px=panel.height_px,
        background_color=panel.background_color, gutter_px=panel.gutter_px,
        frame_px=panel.frame_px, revision=panel.revision,
        created_at=panel.created_at, updated_at=panel.updated_at,
        slots=[
            PanelSlot(
                id=slot.id, candidate_id=slot.candidate_id,
                slot_index=slot.slot_index, x0=slot.x0, y0=slot.y0,
                x1=slot.x1, y1=slot.y1, focal_x=slot.focal_x,
                focal_y=slot.focal_y, zoom=slot.zoom,
                content_url=(f"/api/v1/candidates/{slot.candidate_id}/content"
                             if slot.candidate_id is not None else None),
            ) for slot in panel.slots
        ],
        latest_render=_render_out(panel.latest_render) if panel.latest_render else None,
    )


@router.get("/panels", response_model=list[Panel])
def list_panels(conn=Depends(get_conn)):
    return [_panel_out(panel) for panel in PanelService(conn).list()]


@router.post("/panels", response_model=Panel, status_code=201)
def create_panel(payload: PanelCreate, conn=Depends(get_conn)):
    try:
        return _panel_out(PanelService(conn).create(
            title=payload.title,
            format=payload.format,
            rows=payload.rows,
            columns=payload.columns,
            candidate_id=payload.candidate_id,
        ))
    except PanelError as exc:
        _raise_for(exc)


@router.get("/panels/{panel_id}", response_model=Panel)
def get_panel(panel_id: int, conn=Depends(get_conn)):
    try:
        return _panel_out(PanelService(conn).get(panel_id))
    except PanelError as exc:
        _raise_for(exc)


@router.put("/panels/{panel_id}", response_model=Panel)
def update_panel(panel_id: int, payload: PanelUpdate, conn=Depends(get_conn)):
    try:
        return _panel_out(PanelService(conn).update(
            panel_id, expected_revision=payload.expected_revision, title=payload.title,
            format=payload.format, background_color=payload.background_color,
            gutter_px=payload.gutter_px, frame_px=payload.frame_px,
            slots=[slot.model_dump() for slot in payload.slots],
        ))
    except PanelError as exc:
        _raise_for(exc)


@router.delete("/panels/{panel_id}", status_code=204)
def delete_panel(panel_id: int, conn=Depends(get_conn)):
    try:
        PanelService(conn).delete(panel_id)
    except PanelError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/panels/{panel_id}/render", response_model=PanelRender, status_code=201)
def render_panel(
    panel_id: int, payload: PanelRenderCreate, response: Response,
    conn=Depends(get_conn), storage=Depends(get_storage),
):
    try:
        before = conn.execute(
            "SELECT id FROM panel_render WHERE panel_id=? AND panel_revision=?",
            (panel_id, payload.expected_revision),
        ).fetchone()
        render = PanelRenderService(conn, storage).render(
            panel_id, expected_revision=payload.expected_revision
        )
    except (PanelError, ImageStorageError) as exc:
        _raise_for(exc)
    if before:
        response.status_code = 200
    return _render_out(render)


@router.get("/panels/{panel_id}/renders", response_model=list[PanelRender])
def list_panel_renders(panel_id: int, conn=Depends(get_conn)):
    try:
        return [_render_out(render) for render in PanelService(conn).list_renders(panel_id)]
    except PanelError as exc:
        _raise_for(exc)


def _render_content(render_id: int, conn, storage, *, download: bool):
    try:
        row = PanelService(conn).get_render_row(render_id)
        response = _serve_stored_image(row["sha256"], storage)
    except (PanelError, ImageStorageError) as exc:
        _raise_for(exc)
    if download:
        response.headers["Content-Disposition"] = (
            f'attachment; filename="panel-{row["panel_id"]}-r{row["panel_revision"]}.png"'
        )
    return response


@router.get("/panel-renders/{render_id}/content")
def panel_render_content(render_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    return _render_content(render_id, conn, storage, download=False)


@router.get("/panel-renders/{render_id}/download")
def panel_render_download(render_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    return _render_content(render_id, conn, storage, download=True)
