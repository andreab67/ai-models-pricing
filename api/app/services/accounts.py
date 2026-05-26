"""Check API key validity and fetch live credit usage where available."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import AccountProviderUsage, AccountsUsage
from app.services.cache import cache
from app.services.kilo import load_plans

log = get_logger(__name__)
_settings = get_settings()

_CACHE_KEY = "accounts:usage"
_CACHE_TTL = 120  # 2 min — balance data should be fairly fresh


async def _check_openrouter() -> AccountProviderUsage:
    key = _settings.openrouter_api_key
    if not key:
        return AccountProviderUsage(provider="openrouter", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="openrouter", configured=True, error="API key invalid"
                )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            # OpenRouter returns usage in credits; 1 credit = $0.000001 USD
            spent_usd = round(float(data.get("usage") or 0) / 1_000_000, 4)
            limit_credits = data.get("limit")
            limit_usd = round(float(limit_credits) / 1_000_000, 4) if limit_credits else None
            remaining_usd = round(float(data.get("limit_remaining") or 0) / 1_000_000, 4) if limit_credits else None

            return AccountProviderUsage(
                provider="openrouter",
                configured=True,
                plan=data.get("label"),
                spent_usd=spent_usd,
                limit_usd=limit_usd,
                remaining_usd=remaining_usd,
            )
        except Exception as exc:
            log.warning("openrouter_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openrouter", configured=True, error=str(exc)[:80]
            )


async def _check_kilo() -> AccountProviderUsage:
    tier = _settings.kilo_tier
    try:
        plans = load_plans()
        plan = next((p for p in plans if p.tier == tier), None)
        if plan:
            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                plan=f"{tier.capitalize()} ${plan.monthly_usd:.0f}/mo",
                limit_usd=plan.paid_credits_usd,
            )
    except Exception as exc:
        log.warning("kilo_check_failed", error=str(exc))
    return AccountProviderUsage(provider="kilo", configured=True, plan=tier)


async def _check_openai() -> AccountProviderUsage:
    key = _settings.openai_api_key
    if not key:
        return AccountProviderUsage(provider="openai", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="openai", configured=True, error="API key invalid"
                )
            resp.raise_for_status()
            return AccountProviderUsage(provider="openai", configured=True)
        except Exception as exc:
            log.warning("openai_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openai", configured=True, error=str(exc)[:80]
            )


async def _check_anthropic() -> AccountProviderUsage:
    key = _settings.anthropic_api_key
    if not key:
        return AccountProviderUsage(provider="anthropic", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="anthropic", configured=True, error="API key invalid"
                )
            resp.raise_for_status()
            return AccountProviderUsage(provider="anthropic", configured=True)
        except Exception as exc:
            log.warning("anthropic_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="anthropic", configured=True, error=str(exc)[:80]
            )


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_CACHE_KEY)
    if cached:
        return AccountsUsage.model_validate(cached)

    openrouter, kilo, openai, anthropic = await asyncio.gather(
        _check_openrouter(),
        _check_kilo(),
        _check_openai(),
        _check_anthropic(),
    )
    result = AccountsUsage(
        openrouter=openrouter,
        kilo=kilo,
        openai=openai,
        anthropic=anthropic,
        fetched_at=datetime.now(UTC),
    )
    await cache.set(_CACHE_KEY, result.model_dump(mode="json"), ttl=_CACHE_TTL)
    return result
