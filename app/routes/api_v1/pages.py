"""Comic page aggregate and rendered-media endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.deps import get_conn, get_storage
from app.routes.api_v1._common import _raise_for, _serve_stored_image
from app.schemas import (
    ComicPage, ComicPageCreate, ComicPagePanel, ComicPageUpdate,
    PageRender, PageRenderCreate,
)
from app.services.comic_pages import PageError, PageService
from app.services.page_rendering import PageRenderService
from app.storage import ImageStorageError

router = APIRouter(prefix="/api/v1", tags=["api-v1-pages"])


def _render_out(render) -> PageRender:
    return PageRender(
        id=render.id, page_id=render.page_id, page_revision=render.page_revision,
        width=render.width, height=render.height, layout=render.layout,
        created_at=render.created_at,
        content_url=f"/api/v1/page-renders/{render.id}/content",
        download_url=f"/api/v1/page-renders/{render.id}/download",
    )


def _page_out(page) -> ComicPage:
    return ComicPage(
        id=page.id, title=page.title, format=page.format,
        width_px=page.width_px, height_px=page.height_px,
        background_color=page.background_color, gutter_px=page.gutter_px,
        template_key=page.template_key, template_version=page.template_version,
        divider_values=page.divider_values, revision=page.revision,
        created_at=page.created_at, updated_at=page.updated_at,
        panels=[
            ComicPagePanel(
                id=panel.id, candidate_id=panel.candidate_id,
                slot_index=panel.slot_index, focal_x=panel.focal_x,
                focal_y=panel.focal_y, zoom=panel.zoom,
                content_url=f"/api/v1/candidates/{panel.candidate_id}/content",
            ) for panel in page.panels
        ],
        latest_render=_render_out(page.latest_render) if page.latest_render else None,
    )


@router.get("/pages", response_model=list[ComicPage])
def list_pages(conn=Depends(get_conn)):
    return [_page_out(page) for page in PageService(conn).list()]


@router.post("/pages", response_model=ComicPage, status_code=201)
def create_page(payload: ComicPageCreate, conn=Depends(get_conn)):
    try:
        return _page_out(PageService(conn).create(
            title=payload.title,
            format=payload.format,
            template_key=payload.template_key,
            candidate_id=payload.candidate_id,
        ))
    except PageError as exc:
        _raise_for(exc)


@router.get("/pages/{page_id}", response_model=ComicPage)
def get_page(page_id: int, conn=Depends(get_conn)):
    try:
        return _page_out(PageService(conn).get(page_id))
    except PageError as exc:
        _raise_for(exc)


@router.put("/pages/{page_id}", response_model=ComicPage)
def update_page(page_id: int, payload: ComicPageUpdate, conn=Depends(get_conn)):
    try:
        return _page_out(PageService(conn).update(
            page_id, expected_revision=payload.expected_revision, title=payload.title,
            format=payload.format, background_color=payload.background_color,
            gutter_px=payload.gutter_px, template_key=payload.template_key,
            template_version=payload.template_version,
            divider_values=payload.divider_values,
            panels=[panel.model_dump() for panel in payload.panels],
        ))
    except PageError as exc:
        _raise_for(exc)


@router.delete("/pages/{page_id}", status_code=204)
def delete_page(page_id: int, conn=Depends(get_conn)):
    try:
        PageService(conn).delete(page_id)
    except PageError as exc:
        _raise_for(exc)
    return Response(status_code=204)


@router.post("/pages/{page_id}/render", response_model=PageRender, status_code=201)
def render_page(
    page_id: int, payload: PageRenderCreate, response: Response,
    conn=Depends(get_conn), storage=Depends(get_storage),
):
    try:
        before = conn.execute(
            "SELECT id FROM page_render WHERE page_id=? AND page_revision=?",
            (page_id, payload.expected_revision),
        ).fetchone()
        render = PageRenderService(conn, storage).render(
            page_id, expected_revision=payload.expected_revision
        )
    except (PageError, ImageStorageError) as exc:
        _raise_for(exc)
    if before:
        response.status_code = 200
    return _render_out(render)


@router.get("/pages/{page_id}/renders", response_model=list[PageRender])
def list_page_renders(page_id: int, conn=Depends(get_conn)):
    try:
        return [_render_out(render) for render in PageService(conn).list_renders(page_id)]
    except PageError as exc:
        _raise_for(exc)


def _render_content(render_id: int, conn, storage, *, download: bool):
    try:
        row = PageService(conn).get_render_row(render_id)
        response = _serve_stored_image(row["sha256"], storage)
    except (PageError, ImageStorageError) as exc:
        _raise_for(exc)
    if download:
        response.headers["Content-Disposition"] = (
            f'attachment; filename="comic-page-{row["page_id"]}-r{row["page_revision"]}.png"'
        )
    return response


@router.get("/page-renders/{render_id}/content")
def page_render_content(render_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    return _render_content(render_id, conn, storage, download=False)


@router.get("/page-renders/{render_id}/download")
def page_render_download(render_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    return _render_content(render_id, conn, storage, download=True)
