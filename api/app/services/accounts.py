"""Fetch current-month usage and credit balance from OpenAI and Anthropic."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import AccountProviderUsage, AccountsUsage
from app.services.cache import cache

log = get_logger(__name__)
_settings = get_settings()

_CACHE_KEY = "accounts:usage"
_CACHE_TTL = 300  # 5 min — avoid hammering billing APIs

_OPENAI_BILLING = "https://api.openai.com/dashboard/billing"
_ANTHROPIC_API = "https://api.anthropic.com/v1"


async def _fetch_openai() -> AccountProviderUsage:
    key = _settings.openai_api_key
    if not key:
        return AccountProviderUsage(provider="openai", configured=False)

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    headers = {"Authorization": f"Bearer {key}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            sub_resp = await client.get(
                f"{_OPENAI_BILLING}/subscription", headers=headers
            )
            sub_resp.raise_for_status()
            sub = sub_resp.json()

            usage_resp = await client.get(
                f"{_OPENAI_BILLING}/usage",
                headers=headers,
                params={
                    "start_date": month_start.strftime("%Y-%m-%d"),
                    "end_date": now.strftime("%Y-%m-%d"),
                },
            )
            usage_resp.raise_for_status()
            usage = usage_resp.json()

            hard_limit = float(sub.get("hard_limit_usd") or 0)
            # OpenAI returns usage in cents
            spent_usd = float(usage.get("total_usage") or 0) / 100.0
            plan_title = (sub.get("plan") or {}).get("title")

            return AccountProviderUsage(
                provider="openai",
                configured=True,
                plan=plan_title,
                limit_usd=hard_limit if hard_limit else None,
                spent_usd=round(spent_usd, 4),
                remaining_usd=round(hard_limit - spent_usd, 4) if hard_limit else None,
                period_start=month_start.date().isoformat(),
            )
        except Exception as exc:
            log.warning("openai_billing_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openai", configured=True, error=_short(exc)
            )


async def _fetch_anthropic() -> AccountProviderUsage:
    key = _settings.anthropic_api_key
    if not key:
        return AccountProviderUsage(provider="anthropic", configured=False)

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{_ANTHROPIC_API}/usage",
                headers=headers,
                params={
                    "start_time": month_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Try various field names Anthropic may use
            spent_usd = float(
                data.get("total_cost_usd")
                or data.get("total_cost")
                or _sum_model_costs(data)
                or 0
            )

            return AccountProviderUsage(
                provider="anthropic",
                configured=True,
                spent_usd=round(spent_usd, 4),
                period_start=month_start.date().isoformat(),
            )
        except Exception as exc:
            log.warning("anthropic_usage_failed", error=str(exc))
            return AccountProviderUsage(
                provider="anthropic", configured=True, error=_short(exc)
            )


def _sum_model_costs(data: dict) -> float:
    """Sum cost fields if Anthropic returns a per-model breakdown."""
    items = data.get("data") or data.get("usage") or []
    if not isinstance(items, list):
        return 0.0
    total = 0.0
    for item in items:
        if isinstance(item, dict):
            total += float(item.get("cost_usd") or item.get("total_cost") or 0)
    return total


def _short(exc: Exception) -> str:
    msg = str(exc)
    return msg[:120] if len(msg) > 120 else msg


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_CACHE_KEY)
    if cached:
        return AccountsUsage.model_validate(cached)

    openai_usage, anthropic_usage = await asyncio.gather(
        _fetch_openai(), _fetch_anthropic()
    )
    result = AccountsUsage(
        openai=openai_usage,
        anthropic=anthropic_usage,
        fetched_at=datetime.now(UTC),
    )
    await cache.set(_CACHE_KEY, result.model_dump(mode="json"), ttl=_CACHE_TTL)
    return result
