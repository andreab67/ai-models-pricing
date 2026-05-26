"""Compute effective per-Mtok cost across channels (OR PAYG/BYOK, Kilo)."""

from __future__ import annotations

from app.config import get_settings
from app.schemas import ModelComparison, ModelPricing, WrapperCost
from app.services.kilo import effective_discount

_settings = get_settings()


def _apply_markup(rate: float, pct: float) -> float:
    return round(rate * (1 + pct), 4)


def _apply_discount(rate: float, discount: float) -> float:
    """Discount of 0.20 means you only pay 80% of the rate."""
    return round(rate * (1 - discount), 4)


def channels_for(
    model: ModelPricing,
    kilo_tier: str = "pro",
    kilo_streak_months: int = 8,
    kilo_annual: bool = False,
) -> list[WrapperCost]:
    """All four channels for a given model + Kilo assumptions."""
    discount = effective_discount(kilo_tier, kilo_streak_months, annual=kilo_annual)
    return [
        WrapperCost(
            channel="openrouter_payg",
            prompt_usd_per_mtok=_apply_markup(
                model.prompt_usd_per_mtok, _settings.openrouter_payg_fee_pct
            ),
            completion_usd_per_mtok=_apply_markup(
                model.completion_usd_per_mtok, _settings.openrouter_payg_fee_pct
            ),
            notes=f"+{_settings.openrouter_payg_fee_pct*100:.1f}% credit purchase fee",
        ),
        WrapperCost(
            channel="openrouter_byok",
            prompt_usd_per_mtok=_apply_markup(
                model.prompt_usd_per_mtok, _settings.openrouter_byok_fee_pct
            ),
            completion_usd_per_mtok=_apply_markup(
                model.completion_usd_per_mtok, _settings.openrouter_byok_fee_pct
            ),
            notes=f"+{_settings.openrouter_byok_fee_pct*100:.1f}% past 1M reqs/mo",
        ),
        WrapperCost(
            channel="kilo_pass",
            prompt_usd_per_mtok=_apply_discount(model.prompt_usd_per_mtok, discount),
            completion_usd_per_mtok=_apply_discount(
                model.completion_usd_per_mtok, discount
            ),
            notes=(
                f"tier={kilo_tier}, "
                f"{'annual' if kilo_annual else f'month {kilo_streak_months}'}, "
                f"{discount*100:.1f}% effective discount"
            ),
        ),
        WrapperCost(
            channel="kilo_byok",
            prompt_usd_per_mtok=model.prompt_usd_per_mtok,
            completion_usd_per_mtok=model.completion_usd_per_mtok,
            notes="true passthrough",
        ),
    ]


def compare(
    model: ModelPricing,
    kilo_tier: str = "pro",
    kilo_streak_months: int = 8,
    kilo_annual: bool = False,
) -> ModelComparison:
    return ModelComparison(
        model=model,
        channels=channels_for(model, kilo_tier, kilo_streak_months, kilo_annual),
    )
