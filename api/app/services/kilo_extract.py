"""Extract structured Kilo Pass pricing from the live page text via an LLM.

Used by the kilo_diff CronJob when the page hash changes: turns the cleaned
visible text from fetch_pricing_hash() into a KiloExtractedPricing, validates
it against sane bounds, and renders an updated kilo_plans.yaml if the numbers
actually moved.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import KiloExtractedPricing

log = get_logger(__name__)
_settings = get_settings()

_REQUIRED_TIERS = {"starter", "pro", "expert"}
_PRICE_FIELDS = ("monthly_usd", "paid_credits_usd", "annual_usd")

_SYSTEM_PROMPT = """\
You read the visible text of the kilo.ai/pricing page and extract the Kilo \
Pass subscription tier figures as JSON. Only use numbers that are explicitly \
present in the given text — never estimate or invent a value.

Respond with ONLY a JSON object (no markdown fences, no commentary) shaped \
exactly like this:
{
  "plans": [
    {
      "tier": "starter" | "pro" | "expert",
      "monthly_usd": <monthly subscription price in USD>,
      "paid_credits_usd": <USD credits granted for the monthly price>,
      "max_bonus_pct": <max bonus credit fraction on monthly plans, e.g. 0.40 for 40%>,
      "annual_usd": <annual prepaid price in USD, or null if not stated>,
      "annual_bonus_pct": <bonus credit fraction on annual plans, or null if not stated>
    },
    ... one entry each for starter, pro, expert
  ],
  "bonus_growth": {
    "welcome_pct": <month-1 welcome bonus fraction, e.g. 0.50 for 50%>,
    "baseline_pct": <starting monthly bonus fraction from month 2>,
    "step_pct": <per-month bonus growth fraction>,
    "cap_pct": <max monthly bonus fraction cap, e.g. 0.40 for 40%>
  }
}
All percentages are fractions (40% -> 0.40), not whole numbers.
"""


def _build_request_payload(page_text: str) -> dict[str, Any]:
    return {
        "model": _settings.kilo_extraction_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": page_text},
        ],
    }


def _parse_extraction_response(raw: dict[str, Any]) -> KiloExtractedPricing:
    content = raw["choices"][0]["message"]["content"]
    data = json.loads(content)
    return KiloExtractedPricing.model_validate(data)


async def extract_pricing(page_text: str) -> KiloExtractedPricing:
    url = f"{_settings.openrouter_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {_settings.openrouter_api_key}"}
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        resp = await client.post(url, json=_build_request_payload(page_text))
        resp.raise_for_status()
        return _parse_extraction_response(resp.json())


def _plan_map(plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["tier"]: p for p in plans}


def sanity_check(current: dict[str, Any], extracted: KiloExtractedPricing) -> list[str]:
    """Return human-readable problems with the extraction. Empty list = pass."""
    problems: list[str] = []

    extracted_tiers = {p.tier for p in extracted.plans}
    if extracted_tiers != _REQUIRED_TIERS:
        problems.append(
            f"tier set mismatch: extracted {sorted(extracted_tiers)}, "
            f"expected {sorted(_REQUIRED_TIERS)}"
        )
        return problems  # further per-tier checks are meaningless without a matching tier set

    current_plans = _plan_map(current["plans"])
    for plan in extracted.plans:
        for field in ("monthly_usd", "paid_credits_usd", "max_bonus_pct"):
            value = getattr(plan, field)
            if value is None or value <= 0:
                problems.append(f"{plan.tier}.{field} missing or non-positive: {value!r}")
        if not (0 <= plan.max_bonus_pct <= 1):
            problems.append(f"{plan.tier}.max_bonus_pct out of [0,1]: {plan.max_bonus_pct}")
        if plan.annual_bonus_pct is not None and not (0 <= plan.annual_bonus_pct <= 1):
            problems.append(f"{plan.tier}.annual_bonus_pct out of [0,1]: {plan.annual_bonus_pct}")

        current_plan = current_plans.get(plan.tier)
        if current_plan is None:
            continue
        for field in _PRICE_FIELDS:
            new_value = getattr(plan, field)
            old_value = current_plan.get(field)
            if new_value is None or old_value in (None, 0):
                continue
            delta_pct = abs(new_value - old_value) / old_value
            if delta_pct > _settings.kilo_sanity_max_delta_pct:
                problems.append(
                    f"{plan.tier}.{field} moved {delta_pct:.0%} "
                    f"({old_value} -> {new_value}), exceeds "
                    f"{_settings.kilo_sanity_max_delta_pct:.0%} sanity threshold"
                )

    growth = extracted.bonus_growth
    for field in ("welcome_pct", "baseline_pct", "step_pct", "cap_pct"):
        value = getattr(growth, field)
        if not (0 <= value <= 1):
            problems.append(f"bonus_growth.{field} out of [0,1]: {value}")

    return problems


def diff_from_current(
    current: dict[str, Any], extracted: KiloExtractedPricing
) -> dict[str, Any] | None:
    """Return a per-field old->new diff, or None if nothing material changed."""
    diff: dict[str, Any] = {}

    current_plans = _plan_map(current["plans"])
    for plan in extracted.plans:
        old = current_plans.get(plan.tier, {})
        new = plan.model_dump()
        diff_fields = (
            "monthly_usd",
            "paid_credits_usd",
            "max_bonus_pct",
            "annual_usd",
            "annual_bonus_pct",
        )
        field_diff = {
            field: {"old": old.get(field), "new": new[field]}
            for field in diff_fields
            if old.get(field) != new[field]
        }
        if field_diff:
            diff[plan.tier] = field_diff

    old_growth = current.get("bonus_growth", {})
    new_growth = extracted.bonus_growth.model_dump()
    growth_diff = {
        field: {"old": old_growth.get(field), "new": new_growth[field]}
        for field in ("welcome_pct", "baseline_pct", "step_pct", "cap_pct")
        if old_growth.get(field) != new_growth[field]
    }
    if growth_diff:
        diff["bonus_growth"] = growth_diff

    return diff or None


def render_kilo_plans_yaml(extracted: KiloExtractedPricing, verified_date: str) -> str:
    """Render kilo_plans.yaml, preserving the hand-written header/inline comments.

    Template-based (not yaml.dump / ruamel round-trip) so the explanatory
    comments survive every auto-update instead of being dropped on rewrite.
    """
    plans = _plan_map([p.model_dump() for p in extracted.plans])
    g = extracted.bonus_growth

    def tier_block(tier: str) -> str:
        p = plans[tier]
        lines = [
            f"  - tier: {tier}",
            f"    monthly_usd: {p['monthly_usd']:.2f}",
            f"    paid_credits_usd: {p['paid_credits_usd']:.2f}",
        ]
        if tier == "starter":
            lines.append(
                f"    max_bonus_pct: {p['max_bonus_pct']:.2f}       "
                "# 40% by month 8 on monthly; 5% baseline +5%/mo"
            )
        else:
            lines.append(f"    max_bonus_pct: {p['max_bonus_pct']:.2f}")
        if p.get("annual_usd") is not None:
            suffix = "        # 12 x monthly, prepaid" if tier == "starter" else ""
            lines.append(f"    annual_usd: {p['annual_usd']:.2f}{suffix}")
        if p.get("annual_bonus_pct") is not None:
            suffix = "    # flat 50% bonus on annual" if tier == "starter" else ""
            lines.append(f"    annual_bonus_pct: {p['annual_bonus_pct']:.2f}{suffix}")
        return "\n".join(lines)

    tiers_yaml = "\n\n".join(tier_block(t) for t in ("starter", "pro", "expert"))

    return f"""\
# Static Kilo Pass tier definitions.
# Source: https://kilo.ai/pricing (verified {verified_date})
# A weekly CronJob (kilo_diff) hashes the live page and alerts on change.
# This file is auto-updated by the kilo_diff CronJob when the page hash
# changes and the extracted numbers pass sanity checks — see
# api/app/jobs/kilo_diff.py and api/app/services/kilo_extract.py.

plans:
{tiers_yaml}

# Bonus growth model for monthly plans.
# month 1: welcome bonus
# month n (n>=2): min(step_pct * n, cap_pct)
bonus_growth:
  welcome_pct: {g.welcome_pct:.2f}
  baseline_pct: {g.baseline_pct:.2f}
  step_pct: {g.step_pct:.2f}
  cap_pct: {g.cap_pct:.2f}
"""
