"""Kilo Pass plan math + live page diff detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import yaml
from bs4 import BeautifulSoup

from app.config import get_settings
from app.logging import get_logger
from app.schemas import KiloPlan, KiloProjection

log = get_logger(__name__)
_settings = get_settings()


def _load_yaml() -> dict:
    path: Path = _settings.kilo_plans_path
    if not path.exists():
        raise FileNotFoundError(f"Kilo plans file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_plans() -> list[KiloPlan]:
    data = _load_yaml()
    return [KiloPlan.model_validate(p) for p in data["plans"]]


def monthly_bonus_pct(streak_months: int, growth: dict) -> float:
    """Return Kilo's published bonus % for a given subscription streak.

    Month 1 = welcome bonus (50%).
    Month n (n>=2) = min(step_pct * n, cap_pct) — anchored to Kilo's published
    "40% max bonus unlocked by month 8".
    """
    if streak_months <= 0:
        return 0.0
    if streak_months == 1:
        return float(growth["welcome_pct"])
    # Kilo's published schedule caps at 40% by month 8 with +5%/month steps.
    # The simplest formula matching that anchor is step * n, starting from m2.
    # (Their "starts at 5%" marketing line implies m2=5% which contradicts a
    # 40% cap at m8; we honor the cap-month since that's the load-bearing one.)
    pct = float(growth["step_pct"]) * streak_months
    return min(pct, float(growth["cap_pct"]))


def project(tier: str, streak_months: int, annual: bool = False) -> KiloProjection:
    data = _load_yaml()
    plans = {p["tier"]: p for p in data["plans"]}
    if tier not in plans:
        raise ValueError(f"Unknown tier: {tier}")
    p = plans[tier]

    if annual:
        bonus_pct = float(p["annual_bonus_pct"])
        # annual plans pay 12x upfront, but bonus is per-month
        paid_credits = float(p["paid_credits_usd"])
    else:
        bonus_pct = monthly_bonus_pct(streak_months, data["bonus_growth"])
        paid_credits = float(p["paid_credits_usd"])

    bonus_credits = round(paid_credits * bonus_pct, 4)
    return KiloProjection(
        tier=tier,
        streak_months=streak_months,
        paid_credits_usd=paid_credits,
        bonus_pct=bonus_pct,
        bonus_credits_usd=bonus_credits,
        total_effective_credits_usd=round(paid_credits + bonus_credits, 4),
    )


def effective_discount(tier: str, streak_months: int, annual: bool = False) -> float:
    """Return the effective per-dollar discount vs. straight passthrough.

    e.g. 0.40 bonus means $1 paid yields $1.40 of credits -> 28.6% discount.
    """
    proj = project(tier, streak_months, annual=annual)
    if proj.total_effective_credits_usd <= 0:
        return 0.0
    return 1 - (proj.paid_credits_usd / proj.total_effective_credits_usd)


# --- live page diff ---------------------------------------------------------


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def fetch_pricing_hash() -> tuple[str, str]:
    """Return (hash, visible_text) of the Kilo pricing page.

    Used by the weekly CronJob to detect tier changes.
    """
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": _settings.kilo_diff_user_agent},
    ) as client:
        resp = await client.get(_settings.kilo_pricing_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # strip script/style noise so the hash is stable across cache busters
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        return _hash_text(text), text
