"""Pydantic schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    throughput_tps: float | None = Field(
        default=None, description="Default-route p50 throughput, tokens/sec (OpenRouter)"
    )
    latency_ms: float | None = Field(
        default=None, description="Default-route p50 latency to first token, ms (OpenRouter)"
    )
    speed_provider: str | None = Field(
        default=None, description="Provider the speed sample came from"
    )
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


class KiloBonusGrowth(BaseModel):
    welcome_pct: float
    baseline_pct: float
    step_pct: float
    cap_pct: float


class KiloTierPrimitive(BaseModel):
    """The only per-tier facts literally printed on kilo.ai/pricing.

    Everything else (max_bonus_pct, annual_usd, bonus_growth) is derived from
    these in code — see kilo_extract.reconstruct — because the page shows no
    per-tier annual prices, only monthly price + "Up to $X/mo in credits".
    """

    tier: str
    monthly_usd: float          # the "$X/mo" price
    max_credits_usd: float      # the "Up to $Y/mo in credits" figure


class KiloPricePrimitives(BaseModel):
    """Narrow LLM extraction target — only unambiguous, on-page numbers."""

    tiers: list[KiloTierPrimitive]
    annual_bonus_pct: float     # the "Annual 50% bonus" headline, as a fraction


class KiloExtractedPricing(BaseModel):
    """Reconstructed full pricing shape (from KiloPricePrimitives)."""

    plans: list[KiloPlan]
    bonus_growth: KiloBonusGrowth


class KiloProjection(BaseModel):
    tier: str
    streak_months: int
    paid_credits_usd: float
    bonus_pct: float
    bonus_credits_usd: float
    total_effective_credits_usd: float


class QuotaWindow(BaseModel):
    """One quota window within a provider's subscription.

    MiniMax returns a ``model_remains`` array where each entry has BOTH a
    5h interval (``current_interval_*``) and a weekly (``current_weekly_*``)
    counter for the same model. We expand each entry into 1-2 windows so
    the dashboard can render each quota on its own row instead of
    aggregating across them and reporting a misleading worst case.

    Attributes:
        name: short label for the row (e.g. "general", "video")
        period: window label (e.g. "5h", "weekly")
        usage: requests consumed in this window
        limit: requests allowed in this window
        remaining_percent: percent remaining in this window
    """

    name: str
    period: str
    usage: int
    limit: int
    remaining_percent: float


class AccountProviderUsage(BaseModel):
    provider: Literal[
        "openrouter",
        "kilo",
        "minimax",
        "deepseek",
    ]
    configured: bool = False
    plan: str | None = None
    limit_usd: float | None = None
    spent_usd: float | None = None
    remaining_usd: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    model_count: int | None = None
    currency: str | None = None
    dashboard_url: str | None = None
    # Non-USD usage fields. MiniMax tracks request counts and a remaining
    # percent per quota window instead of dollar amounts; some Anthropic /
    # OpenAI surfaces also expose usage counts alongside the credit-grant
    # window. These are populated when the vendor returns them and rendered
    # by the frontend only when present -- providers that report purely in
    # USD leave them None.
    usage_count: int | None = None
    usage_limit: int | None = None
    remaining_percent: float | None = None
    plan_models: list[str] | None = None
    quota_windows: list[QuotaWindow] | None = None
    # Credit composition (DeepSeek exposes this in /user/balance). When set,
    # the dashboard shows the paid / free split so the operator knows
    # whether the remaining balance is topped-up cash or free credits.
    granted_usd: float | None = None
    topped_up_usd: float | None = None
    error: str | None = None


class AccountsUsage(BaseModel):
    openrouter: AccountProviderUsage
    kilo: AccountProviderUsage
    minimax: AccountProviderUsage
    deepseek: AccountProviderUsage
    fetched_at: datetime


class ModelActivityItem(BaseModel):
    model_id: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class ActivityResponse(BaseModel):
    items: list[ModelActivityItem]
    fetched_at: datetime


class DailyTopFive(BaseModel):
    generated_at: datetime
    models: list[RankedModel]
    projected_monthly_savings_usd: float
    baseline_assumption: str
