"""Unit tests for kilo pricing extraction, sanity checks, and yaml rendering."""

from __future__ import annotations

import json

import pytest
import yaml

from app.schemas import KiloExtractedPricing, KiloPricePrimitives
from app.services import kilo_extract


def _current(**overrides) -> dict:
    base = {
        "plans": [
            {
                "tier": "starter",
                "monthly_usd": 19.0,
                "paid_credits_usd": 19.0,
                "max_bonus_pct": 0.40,
                "annual_usd": 228.0,
                "annual_bonus_pct": 0.50,
            },
            {
                "tier": "pro",
                "monthly_usd": 49.0,
                "paid_credits_usd": 49.0,
                "max_bonus_pct": 0.40,
                "annual_usd": 588.0,
                "annual_bonus_pct": 0.50,
            },
            {
                "tier": "expert",
                "monthly_usd": 199.0,
                "paid_credits_usd": 199.0,
                "max_bonus_pct": 0.40,
                "annual_usd": 2388.0,
                "annual_bonus_pct": 0.50,
            },
        ],
        "bonus_growth": {
            "welcome_pct": 0.50,
            "baseline_pct": 0.05,
            "step_pct": 0.05,
            "cap_pct": 0.40,
        },
    }
    base.update(overrides)
    return base


def _extracted(**tier_overrides) -> KiloExtractedPricing:
    current = _current()
    plans = [dict(p) for p in current["plans"]]
    for tier, fields in tier_overrides.items():
        for p in plans:
            if p["tier"] == tier:
                p.update(fields)
    return KiloExtractedPricing.model_validate(
        {"plans": plans, "bonus_growth": current["bonus_growth"]}
    )


def test_sanity_check_passes_on_identical_values() -> None:
    assert kilo_extract.sanity_check(_current(), _extracted()) == []


def test_sanity_check_rejects_tier_set_mismatch() -> None:
    current = _current()
    extracted = KiloExtractedPricing.model_validate(
        {
            "plans": [
                {
                    "tier": "starter",
                    "monthly_usd": 19.0,
                    "paid_credits_usd": 19.0,
                    "max_bonus_pct": 0.4,
                },
                {
                    "tier": "pro",
                    "monthly_usd": 49.0,
                    "paid_credits_usd": 49.0,
                    "max_bonus_pct": 0.4,
                },
            ],
            "bonus_growth": current["bonus_growth"],
        }
    )
    problems = kilo_extract.sanity_check(current, extracted)
    assert any("tier set mismatch" in p for p in problems)


def test_sanity_check_rejects_out_of_range_bonus_pct() -> None:
    extracted = _extracted(starter={"max_bonus_pct": 1.5})
    problems = kilo_extract.sanity_check(_current(), extracted)
    assert any("max_bonus_pct out of [0,1]" in p for p in problems)


def test_sanity_check_rejects_large_price_delta() -> None:
    extracted = _extracted(starter={"monthly_usd": 19000.0})
    problems = kilo_extract.sanity_check(_current(), extracted)
    assert any("monthly_usd moved" in p for p in problems)


def test_sanity_check_allows_price_delta_within_threshold() -> None:
    extracted = _extracted(starter={"monthly_usd": 22.0})  # ~16% move, under 50% default
    assert kilo_extract.sanity_check(_current(), extracted) == []


def test_sanity_check_rejects_annual_bonus_delta_above_threshold() -> None:
    """Regression for finding BCK-002: a 0.50 -> 0.05 annual-bonus drop must
    fail the sanity delta check, not just the [0,1] range guard."""
    extracted = _extracted(starter={"annual_bonus_pct": 0.05})  # -90% move
    problems = kilo_extract.sanity_check(_current(), extracted)
    assert any("annual_bonus_pct moved" in p for p in problems), problems


def test_sanity_check_allows_annual_bonus_delta_within_threshold() -> None:
    extracted = _extracted(starter={"annual_bonus_pct": 0.55})  # +10% move, under 50% default
    assert kilo_extract.sanity_check(_current(), extracted) == []


def test_diff_from_current_returns_none_when_unchanged() -> None:
    assert kilo_extract.diff_from_current(_current(), _extracted()) is None


def test_diff_from_current_reports_changed_field() -> None:
    extracted = _extracted(pro={"monthly_usd": 59.0})
    diff = kilo_extract.diff_from_current(_current(), extracted)
    assert diff is not None
    assert diff["pro"]["monthly_usd"] == {"old": 49.0, "new": 59.0}
    assert "starter" not in diff
    assert "expert" not in diff


def test_render_kilo_plans_yaml_round_trips() -> None:
    extracted = _extracted()
    rendered = kilo_extract.render_kilo_plans_yaml(extracted, "2026-07-20")
    parsed = yaml.safe_load(rendered)

    assert {p["tier"] for p in parsed["plans"]} == {"starter", "pro", "expert"}
    starter = next(p for p in parsed["plans"] if p["tier"] == "starter")
    assert starter["monthly_usd"] == pytest.approx(19.0)
    assert parsed["bonus_growth"]["cap_pct"] == pytest.approx(0.40)
    assert "verified 2026-07-20" in rendered
    assert "40% by month 8 on monthly" in rendered
    assert "auto-updated by the kilo_diff CronJob" in rendered


_LIVE_PRIMITIVES = {
    "tiers": [
        {"tier": "starter", "monthly_usd": 19, "max_credits_usd": 26.6},
        {"tier": "pro", "monthly_usd": 49, "max_credits_usd": 68.6},
        {"tier": "expert", "monthly_usd": 199, "max_credits_usd": 278.6},
    ],
    "annual_bonus_pct": 0.5,
}


def test_reconstruct_reproduces_current_yaml() -> None:
    """The on-page primitives must rebuild the hand-maintained values exactly."""
    prim = KiloPricePrimitives.model_validate(_LIVE_PRIMITIVES)
    rebuilt = kilo_extract.reconstruct(prim)

    # identical to _current() -> a wording-only hash change yields no diff
    assert kilo_extract.diff_from_current(_current(), rebuilt) is None

    starter = next(p for p in rebuilt.plans if p.tier == "starter")
    assert starter.monthly_usd == pytest.approx(19.0)
    assert starter.paid_credits_usd == pytest.approx(19.0)
    assert starter.max_bonus_pct == pytest.approx(0.40)  # 26.6/19 - 1
    assert starter.annual_usd == pytest.approx(228.0)  # 19 x 12
    assert starter.annual_bonus_pct == pytest.approx(0.50)

    assert rebuilt.bonus_growth.cap_pct == pytest.approx(0.40)
    assert rebuilt.bonus_growth.step_pct == pytest.approx(0.05)  # 0.40 / 8
    assert rebuilt.bonus_growth.welcome_pct == pytest.approx(0.50)


def test_reconstruct_rejects_non_positive_monthly() -> None:
    prim = KiloPricePrimitives.model_validate(
        {
            "tiers": [
                {"tier": "starter", "monthly_usd": 0, "max_credits_usd": 26.6},
                {"tier": "pro", "monthly_usd": 49, "max_credits_usd": 68.6},
                {"tier": "expert", "monthly_usd": 199, "max_credits_usd": 278.6},
            ],
            "annual_bonus_pct": 0.5,
        }
    )
    with pytest.raises(ValueError, match="non-positive"):
        kilo_extract.reconstruct(prim)


def test_reconstruct_tracks_a_real_price_change() -> None:
    changed = {
        "tiers": [
            {"tier": "starter", "monthly_usd": 24, "max_credits_usd": 33.6},  # 24 -> 40% bonus
            {"tier": "pro", "monthly_usd": 49, "max_credits_usd": 68.6},
            {"tier": "expert", "monthly_usd": 199, "max_credits_usd": 278.6},
        ],
        "annual_bonus_pct": 0.5,
    }
    rebuilt = kilo_extract.reconstruct(KiloPricePrimitives.model_validate(changed))
    diff = kilo_extract.diff_from_current(_current(), rebuilt)
    assert diff is not None
    assert diff["starter"]["monthly_usd"] == {"old": 19.0, "new": 24.0}
    assert diff["starter"]["annual_usd"] == {"old": 228.0, "new": 288.0}


def test_parse_primitives_validates_shape() -> None:
    raw = {"choices": [{"message": {"content": json.dumps(_LIVE_PRIMITIVES)}}]}
    parsed = kilo_extract._parse_primitives(raw)
    assert isinstance(parsed, KiloPricePrimitives)
    assert {t.tier for t in parsed.tiers} == {"starter", "pro", "expert"}


def test_build_request_payload_uses_configured_model_and_json_mode() -> None:
    payload = kilo_extract._build_request_payload("some page text")
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][1]["content"] == "some page text"
    assert payload["model"]  # configured default, non-empty
