"""Channel comparison endpoints (OR PAYG/BYOK, Kilo Pass/BYOK)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.schemas import KiloPlan, KiloProjection, ModelComparison, ModelPricing
from app.services import kilo, kilo_gateway, openrouter
from app.services.pricing_calculator import compare

KiloTier = Literal["starter", "pro", "expert"]

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("/{model_id:path}", response_model=ModelComparison)
async def compare_channels(
    model_id: str,
    kilo_tier: Annotated[KiloTier | None, Query()] = None,
    kilo_streak_months: int | None = Query(default=None, ge=1, le=120),
    kilo_annual: bool = Query(default=False),
) -> ModelComparison:
    """Compare a model across the four channels.

    Omitted Kilo assumptions default to the configured ``KILO_TIER`` at the
    steady-state streak (the month the bonus reaches its cap, derived from
    kilo_plans.yaml). The month-1 welcome bonus is one-off, so defaulting to
    it overstated the recurring Kilo Pass discount (33.3% vs 28.6% today).
    """
    m = await openrouter.get_model(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"model not found: {model_id}")
    tier = kilo_tier or get_settings().kilo_tier
    try:
        streak = kilo_streak_months or kilo.steady_state_streak(kilo.load_bonus_growth())
        return compare(m, tier, streak, kilo_annual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


kilo_router = APIRouter(prefix="/kilo", tags=["kilo"])


@kilo_router.get("/plans", response_model=list[KiloPlan])
async def list_plans() -> list[KiloPlan]:
    return kilo.load_plans()


@kilo_router.get("/models", response_model=list[ModelPricing])
async def list_kilo_models() -> list[ModelPricing]:
    return await kilo_gateway.fetch_models()


@kilo_router.get("/models/{model_id:path}", response_model=ModelPricing)
async def get_kilo_model(model_id: str) -> ModelPricing:
    m = await kilo_gateway.get_model(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"model not available on Kilo: {model_id}")
    return m


@kilo_router.get("/projection", response_model=KiloProjection)
async def projection(
    tier: Annotated[KiloTier, Query()] = "pro",
    streak_months: int = Query(default=8, ge=1, le=120),
    annual: bool = Query(default=False),
) -> KiloProjection:
    try:
        return kilo.project(tier, streak_months, annual=annual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
