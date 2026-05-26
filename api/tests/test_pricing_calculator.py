"""Unit tests for the channel cost calculator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas import ModelPricing
from app.services import pricing_calculator


@pytest.fixture
def sonnet() -> ModelPricing:
    return ModelPricing(
        id="anthropic/claude-sonnet-4.6",
        name="Claude Sonnet 4.6",
        provider="anthropic",
        prompt_usd_per_mtok=3.0,
        completion_usd_per_mtok=15.0,
        context_length=1_000_000,
        supports_tools=True,
        supports_vision=True,
        captured_at=datetime.now(UTC),
    )


def test_openrouter_payg_adds_5_5_percent(sonnet: ModelPricing) -> None:
    channels = pricing_calculator.channels_for(sonnet)
    payg = next(c for c in channels if c.channel == "openrouter_payg")
    assert payg.prompt_usd_per_mtok == pytest.approx(3.0 * 1.055, rel=1e-3)
    assert payg.completion_usd_per_mtok == pytest.approx(15.0 * 1.055, rel=1e-3)


def test_openrouter_byok_adds_5_percent(sonnet: ModelPricing) -> None:
    channels = pricing_calculator.channels_for(sonnet)
    byok = next(c for c in channels if c.channel == "openrouter_byok")
    assert byok.prompt_usd_per_mtok == pytest.approx(3.0 * 1.05, rel=1e-3)


def test_kilo_byok_is_passthrough(sonnet: ModelPricing) -> None:
    channels = pricing_calculator.channels_for(sonnet)
    kbyok = next(c for c in channels if c.channel == "kilo_byok")
    assert kbyok.prompt_usd_per_mtok == sonnet.prompt_usd_per_mtok
    assert kbyok.completion_usd_per_mtok == sonnet.completion_usd_per_mtok


def test_kilo_pass_applies_discount_at_month_8(sonnet: ModelPricing) -> None:
    # At streak month 8 monthly, bonus = 40% -> discount = 1 - 1/1.4 ≈ 0.2857
    channels = pricing_calculator.channels_for(
        sonnet, kilo_tier="pro", kilo_streak_months=8, kilo_annual=False
    )
    kp = next(c for c in channels if c.channel == "kilo_pass")
    expected = 3.0 * (1 - (1 - 1 / 1.4))
    assert kp.prompt_usd_per_mtok == pytest.approx(expected, rel=1e-3)


def test_kilo_pass_annual_is_50_pct_bonus(sonnet: ModelPricing) -> None:
    channels = pricing_calculator.channels_for(
        sonnet, kilo_tier="pro", kilo_streak_months=1, kilo_annual=True
    )
    kp = next(c for c in channels if c.channel == "kilo_pass")
    expected = 3.0 * (1 - (1 - 1 / 1.5))
    assert kp.prompt_usd_per_mtok == pytest.approx(expected, rel=1e-3)
