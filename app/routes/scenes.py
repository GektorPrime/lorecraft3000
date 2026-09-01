"""Scene creation, no-spend preview, generation, and manual review routes."""

from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.deps import get_conn, get_provider, get_storage, settings, templates
from app.providers.base import ImageProvider
from app.services.characters import CharacterService
from app.services.costs import CostError, CostLedger
from app.services.generation import GenerationError, GenerationService
from app.services.scenes import ASPECT_RATIOS, SceneError, SceneNotFoundError, SceneService
from app.services.styles import StyleService
from app.storage import ImageStorage, ImageStorageError

router = APIRouter(tags=["scenes"])

MODELS = ("gemini-3.1-flash-image", "gemini-3-pro-image")
IMAGE_SIZES = ("1K", "2K", "4K")
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _scene_context(conn, values=None, error=None):
    return {
        "characters": CharacterService(conn).list(),
        "styles": StyleService(conn).list(),
        "models": MODELS,
        "image_sizes": IMAGE_SIZES,
        "aspect_ratios": ASPECT_RATIOS,
        "values": values or {},
        "error": error,
    }


def _parse_cast(form, characters) -> list[dict]:
    raw_order = str(form.get("cast_order", ""))
    try:
        ordered_ids = [int(value.strip()) for value in raw_order.split(",") if value.strip()]
    except ValueError as exc:
        raise SceneError("cast order must be comma-separated character IDs") from exc
    known = {character.id for character in characters}
    if any(character_id not in known for character_id in ordered_ids):
        raise SceneError("cast order contains an unknown character ID")
    return [
        {
            "character_id": character_id,
            "role": str(form.get(f"role_{character_id}", "")),
            "prominence": _parse_prominence(form.get(f"prominence_{character_id}", "1")),
        }
        for character_id in ordered_ids
    ]


def _parse_prominence(raw) -> int:
    try:
        value = int(str(raw))
    except ValueError as exc:
        raise SceneError("prominence must be a positive integer") from exc
    if value < 1:
        raise SceneError("prominence must be a positive integer")
    return value


@router.get("/scenes", response_class=HTMLResponse)
def list_scenes(request: Request, conn=Depends(get_conn)):
    ledger = CostLedger(conn, settings)
    return templates.TemplateResponse(
        request,
        "scenes/list.html",
        {
            "scenes": SceneService(conn, settings).list(),
            "spent_cents": ledger.spent_today(),
            "cap_cents": settings.daily_spend_cap_cents,
        },
    )


@router.get("/scenes/new", response_class=HTMLResponse)
def new_scene(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse(request, "scenes/form.html", _scene_context(conn))


@router.post("/scenes")
async def create_scene(request: Request, conn=Depends(get_conn)):
    form = await request.form()
    characters = CharacterService(conn).list()
    values = dict(form)
    try:
        cast = _parse_cast(form, characters)
        scene = SceneService(conn, settings).create(
            beat_text=str(form.get("beat_text", "")),
            camera=str(form.get("camera", "")),
            framing=str(form.get("framing", "")),
            mood=str(form.get("mood", "")),
            aspect_ratio=str(form.get("aspect_ratio", "3:2")),
            cast=cast,
            style_id=int(str(form.get("style_id", "0"))),
            model=str(form.get("model", settings.default_model)),
            image_size=str(form.get("image_size", settings.default_image_size)),
        )
    except (SceneError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "scenes/form.html",
            _scene_context(conn, values, str(exc)),
            status_code=422,
        )
    return RedirectResponse(f"/scenes/{scene.id}/preview", status_code=303)


@router.get("/scenes/{scene_id}/preview", response_class=HTMLResponse)
def preview_scene(
    scene_id: int,
    request: Request,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
):
    try:
        scene = SceneService(conn, settings).get(scene_id)
    except SceneNotFoundError:
        return HTMLResponse("Scene not found", status_code=404)
    notice = request.query_params.get("notice")
    error = None
    preview = None
    try:
        preview = GenerationService(conn, storage, settings, None).preview(
            scene_id, model=scene.model, image_size=scene.image_size
        )
    except (GenerationError, CostError, ImageStorageError) as exc:
        error = str(exc)
    generations = conn.execute(
        "SELECT * FROM generation WHERE scene_id = ? ORDER BY id DESC", (scene_id,)
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "scenes/preview.html",
        {
            "scene": scene, "preview": preview, "error": error,
            "notice": notice, "generations": generations,
        },
    )


@router.post("/scenes/{scene_id}/generate")
def generate_scene(
    scene_id: int,
    expected_prompt_hash: str = Form(...),
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
    provider: ImageProvider = Depends(get_provider),
):
    try:
        scene = SceneService(conn, settings).get(scene_id)
        outcome = GenerationService(conn, storage, settings, provider).generate(
            scene_id,
            model=scene.model,
            image_size=scene.image_size,
            expected_prompt_hash=expected_prompt_hash,
        )
    except (SceneError, GenerationError, CostError, ImageStorageError) as exc:
        return RedirectResponse(
            f"/scenes/{scene_id}/preview?notice={quote(str(exc))}", status_code=303
        )
    return RedirectResponse(f"/generations/{outcome.generation_id}", status_code=303)


@router.get("/generations/{generation_id}", response_class=HTMLResponse)
def generation_detail(
    generation_id: int,
    request: Request,
    conn=Depends(get_conn),
    storage: ImageStorage = Depends(get_storage),
):
    generation = conn.execute(
        "SELECT * FROM generation WHERE id = ?", (generation_id,)
    ).fetchone()
    if generation is None:
        return HTMLResponse("Generation not found", status_code=404)
    candidate = conn.execute(
        "SELECT * FROM candidate WHERE generation_id = ? ORDER BY idx LIMIT 1",
        (generation_id,),
    ).fetchone()
    request_data = json.loads(generation["request_json"])
    image_available = False
    if candidate is not None:
        try:
            storage.read(candidate["sha256"])
            image_available = True
        except ImageStorageError:
            pass
    return templates.TemplateResponse(
        request,
        "generations/detail.html",
        {
            "generation": generation,
            "candidate": candidate,
            "image_available": image_available,
            "request_data": request_data,
            "request_json": json.dumps(request_data, indent=2),
            "response_json": json.dumps(json.loads(generation["response_json"]), indent=2),
        },
    )


@router.post("/candidates/{candidate_id}/review")
async def review_candidate(candidate_id: int, request: Request, conn=Depends(get_conn)):
    form = await request.form()
    verdict = str(form.get("verdict", ""))
    if verdict not in {"accepted", "rejected"}:
        return HTMLResponse("Invalid review verdict", status_code=422)
    cursor = conn.execute(
        "UPDATE candidate SET review_status = ? WHERE id = ?", (verdict, candidate_id)
    )
    if cursor.rowcount != 1:
        conn.rollback()
        return HTMLResponse("Candidate not found", status_code=404)
    conn.commit()
    generation_id = conn.execute(
        "SELECT generation_id FROM candidate WHERE id = ?", (candidate_id,)
    ).fetchone()["generation_id"]
    return RedirectResponse(f"/generations/{generation_id}", status_code=303)


@router.get("/media/{sha256}")
def stored_media(sha256: str, storage: ImageStorage = Depends(get_storage)):
    try:
        data, metadata = storage.read(sha256)
    except ImageStorageError:
        return HTMLResponse("Image not found", status_code=404)
    mime = _MIME.get(metadata.get("format"), "application/octet-stream")
    return Response(data, media_type=mime)
