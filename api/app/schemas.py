"""Pydantic schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    """Normalized model pricing record returned by the API."""

    id: str = Field(
        ...,
        description="Provider-qualified model id (e.g. anthropic/claude-sonnet-4.6)",
    )
    name: str
    provider: str | None = None
    prompt_usd_per_mtok: float = Field(..., description="USD per 1M input tokens")
    completion_usd_per_mtok: float = Field(..., description="USD per 1M output tokens")
    request_usd: float = 0.0
    image_usd: float = 0.0
    context_length: int | None = None
    max_completion_tokens: int | None = None
    supports_tools: bool = False
    supports_vision: bool = False
    captured_at: datetime


class WrapperCost(BaseModel):
    """Effective per-Mtok cost through a given channel."""

    channel: Literal["openrouter_payg", "openrouter_byok", "kilo_pass", "kilo_byok"]
    prompt_usd_per_mtok: float
    completion_usd_per_mtok: float
    notes: str | None = None


class ModelComparison(BaseModel):
    model: ModelPricing
    channels: list[WrapperCost]


class RankedModel(BaseModel):
    model: ModelPricing
    score: float
    blended_usd_per_mtok: float = Field(
        ..., description="Weighted blended cost used for ranking"
    )
    rank: int


class KiloPlan(BaseModel):
    tier: str
    monthly_usd: float
    paid_credits_usd: float
    max_bonus_pct: float
    annual_usd: float | None = None
    annual_bonus_pct: float | None = None


class KiloProjection(BaseModel):
    tier: str
    streak_months: int
    paid_credits_usd: float
    bonus_pct: float
    bonus_credits_usd: float
    total_effective_credits_usd: float


class AccountProviderUsage(BaseModel):
    provider: Literal["openai", "anthropic"]
    configured: bool = False
    plan: str | None = None
    limit_usd: float | None = None
    spent_usd: float | None = None
    remaining_usd: float | None = None
    period_start: str | None = None
    error: str | None = None


class AccountsUsage(BaseModel):
    openai: AccountProviderUsage
    anthropic: AccountProviderUsage
    fetched_at: datetime


class DailyTopFive(BaseModel):
    generated_at: datetime
    models: list[RankedModel]
    projected_monthly_savings_usd: float
    baseline_assumption: str
