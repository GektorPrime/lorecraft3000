"""Options/budget endpoints for the /api/v1 JSON API."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_conn, settings
from app.models import ModelRegistry
from app.routes.api_v1._common import (
    PANEL_IMMUTABILITY_EXPLANATION,
    REF_IMAGE_WEIGHT_EXPLANATION,
    REF_SET_IMMUTABILITY_EXPLANATION,
)
from app.schemas import Budget, OptionsSummary
from app.services.costs import CostLedger
from app.services.validation import ALLOWED_ROLES

router = APIRouter(prefix="/api/v1", tags=["api-v1-options"])


@router.get("/options/summary", response_model=OptionsSummary)
def options_summary(conn=Depends(get_conn)) -> OptionsSummary:
    registry = ModelRegistry(settings)
    ledger = CostLedger(conn, settings)
    spent = ledger.spent_today()
    return OptionsSummary(
        models=list(registry.models),
        image_sizes=list(registry.image_sizes),
        aspect_ratios=list(registry.aspect_ratios),
        ref_image_roles=list(ALLOWED_ROLES),
        default_model=settings.default_model,
        default_image_size=settings.default_image_size,
        daily_spend_cap_cents=settings.daily_spend_cap_cents,
        spent_today_cents=spent,
        remaining_today_cents=settings.daily_spend_cap_cents - spent,
        ref_image_weight_explanation=REF_IMAGE_WEIGHT_EXPLANATION,
        ref_set_immutability_explanation=REF_SET_IMMUTABILITY_EXPLANATION,
        panel_immutability_explanation=PANEL_IMMUTABILITY_EXPLANATION,
    )


@router.get("/budget", response_model=Budget)
def budget(conn=Depends(get_conn)) -> Budget:
    ledger = CostLedger(conn, settings)
    spent = ledger.spent_today()
    return Budget(
        daily_spend_cap_cents=settings.daily_spend_cap_cents,
        spent_today_cents=spent,
        remaining_today_cents=settings.daily_spend_cap_cents - spent,
    )