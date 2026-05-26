"""Channel comparison endpoints (OR PAYG/BYOK, Kilo Pass/BYOK)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import KiloPlan, KiloProjection, ModelComparison
from app.services import kilo, openrouter
from app.services.pricing_calculator import compare

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("/{model_id:path}", response_model=ModelComparison)
async def compare_channels(
    model_id: str,
    kilo_tier: str = Query(default="pro"),
    kilo_streak_months: int = Query(default=8, ge=1, le=120),
    kilo_annual: bool = Query(default=False),
) -> ModelComparison:
    m = await openrouter.get_model(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"model not found: {model_id}")
    return compare(m, kilo_tier, kilo_streak_months, kilo_annual)


kilo_router = APIRouter(prefix="/kilo", tags=["kilo"])


@kilo_router.get("/plans", response_model=list[KiloPlan])
async def list_plans() -> list[KiloPlan]:
    return kilo.load_plans()


@kilo_router.get("/projection", response_model=KiloProjection)
async def projection(
    tier: str = Query(default="pro"),
    streak_months: int = Query(default=8, ge=1, le=120),
    annual: bool = Query(default=False),
) -> KiloProjection:
    try:
        return kilo.project(tier, streak_months, annual=annual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
