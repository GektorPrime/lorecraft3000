"""Generation detail, candidate review, and candidate media endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.deps import get_conn, get_provider, get_storage, settings
from app.providers.base import ImageProvider
from app.routes.api_v1._common import (
    _candidate_out,
    _generation_out,
    _raise_for,
    _serve_stored_image,
)
from app.schemas import (
    Candidate,
    CandidateEditIn,
    CandidateReviewIn,
    GalleryItem,
    Generation,
)
from app.services.candidates import CandidateService
from app.services.generation import GenerationService

router = APIRouter(prefix="/api/v1", tags=["api-v1-generations"])


@router.get("/gallery", response_model=list[GalleryItem])
def list_gallery(conn=Depends(get_conn)) -> list[GalleryItem]:
    service = CandidateService(conn)
    return [
        GalleryItem(
            candidate_id=row["candidate_id"],
            content_url=f"/api/v1/candidates/{row['candidate_id']}/content",
            scene_id=row["scene_id"],
            beat_text=row["beat_text"],
            aspect_ratio=row["aspect_ratio"],
            created_at=row["created_at"],
        )
        for row in service.list_accepted()
    ]


@router.get("/generations/{generation_id}", response_model=Generation)
def get_generation(generation_id: int, conn=Depends(get_conn)):
    service = GenerationService(conn, None, None, None)
    try:
        row, candidates = service.get_with_candidates(generation_id)
    except Exception as exc:
        _raise_for(exc)
    return _generation_out(row, candidates)


@router.post("/candidates/{candidate_id}/review", response_model=Candidate)
def review_candidate(candidate_id: int, payload: CandidateReviewIn, conn=Depends(get_conn)):
    if payload.verdict not in {"accepted", "rejected"}:
        raise HTTPException(
            status_code=422,
            detail={"message": "verdict must be 'accepted' or 'rejected'", "type": "ValidationError"},
        )
    service = CandidateService(conn)
    try:
        row = service.review(candidate_id, payload.verdict)
    except Exception as exc:
        _raise_for(exc)
    return _candidate_out(row)


@router.post(
    "/candidates/{candidate_id}/edit", response_model=Generation, status_code=201
)
def edit_candidate(
    candidate_id: int,
    payload: CandidateEditIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    conn=Depends(get_conn),
    storage=Depends(get_storage),
    provider: ImageProvider = Depends(get_provider),
):
    """Create a new candidate by editing an existing one with an instruction.

    The edit runs on the same provider/model that produced the source image and
    is recorded as a child generation of the source, keeping the scene's attempt
    history a connected chain.
    """
    service = GenerationService(conn, storage, settings, provider)
    try:
        outcome = service.edit_candidate(
            candidate_id,
            payload.instruction,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_for(exc)
    row, candidates = service.get_with_candidates(outcome.generation_id)
    if outcome.replayed:
        response.status_code = 200
    return _generation_out(row, candidates)


@router.get("/candidates/{candidate_id}/content")
def candidate_content(candidate_id: int, conn=Depends(get_conn), storage=Depends(get_storage)):
    service = CandidateService(conn)
    try:
        sha256 = service.content_sha(candidate_id)
    except Exception as exc:
        _raise_for(exc)
    return _serve_stored_image(sha256, storage)