"""Check whether OpenAI and Anthropic API keys are configured and valid."""

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
_CACHE_TTL = 300


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
            return AccountProviderUsage(provider="openai", configured=True, error=str(exc)[:80])


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
            return AccountProviderUsage(provider="anthropic", configured=True, error=str(exc)[:80])


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_CACHE_KEY)
    if cached:
        return AccountsUsage.model_validate(cached)

    openai_usage, anthropic_usage = await asyncio.gather(
        _check_openai(), _check_anthropic()
    )
    result = AccountsUsage(
        openai=openai_usage,
        anthropic=anthropic_usage,
        fetched_at=datetime.now(UTC),
    )
    await cache.set(_CACHE_KEY, result.model_dump(mode="json"), ttl=_CACHE_TTL)
    return result
