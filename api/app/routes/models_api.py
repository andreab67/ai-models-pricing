"""Model catalog + history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ModelPricing, RankedModel
from app.services import openrouter, ranker

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelPricing])
async def list_models(
    refresh: bool = Query(default=False, description="Bypass cache"),
) -> list[ModelPricing]:
    return await openrouter.list_models(use_cache=not refresh)


@router.get("/top", response_model=list[RankedModel])
async def top_models(n: int = Query(default=10, ge=1, le=50)) -> list[RankedModel]:
    models = await openrouter.list_models()
    return ranker.top_n(models, n=n)


@router.get("/{model_id:path}", response_model=ModelPricing)
async def get_model(model_id: str) -> ModelPricing:
    m = await openrouter.get_model(model_id)
    if m is None:
        raise HTTPException(status_code=404, detail=f"model not found: {model_id}")
    return m


@router.get("/{model_id:path}/history", response_model=list[ModelPricing])
async def history(
    model_id: str,
    days: int = Query(default=30, ge=1, le=365),
) -> list[ModelPricing]:
    return await openrouter.get_history(model_id, days=days)
