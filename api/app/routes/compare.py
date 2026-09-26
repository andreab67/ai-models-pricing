"""Channel comparison endpoints (OR PAYG/BYOK, Kilo Pass/BYOK)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.schemas import KiloPlan, KiloProjection, ModelComparison, ModelPricing
from app.services import kilo, kilo_gateway, openrouter
from app.services.pricing_calculator import compare

KiloTier = Literal["starter", "pro", "expert"]

router = APIRouter(prefix="/compare", tags=["compare"])


@router.get("/{model_id:path}", response_model=ModelComparison)
async def compare_channels(
    model_id: str,
    kilo_tier: Annotated[KiloTier, Query()] = "pro",
    kilo_streak_months: int = Query(default=8, ge=1, le=120),
    kilo_annual: bool = Query(default=False),
) -> ModelComparison:
    m = await openrouter.get_model(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"model not found: {model_id}")
    try:
        return compare(m, kilo_tier, kilo_streak_months, kilo_annual)
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
