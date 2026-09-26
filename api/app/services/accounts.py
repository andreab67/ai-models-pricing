"""Check API key validity and fetch live credit usage where available."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import AccountProviderUsage, AccountsUsage, ActivityResponse, ModelActivityItem
from app.services.cache import cache
from app.services.kilo import load_plans

log = get_logger(__name__)
_settings = get_settings()

_CACHE_KEY = "accounts:usage"
_CACHE_TTL = 120  # 2 min — balance data should be fairly fresh
# A transient upstream error is cached only briefly, so one 5xx does not
# blank the widgets for the full TTL (but we still don't hammer upstream).
_FAILURE_CACHE_TTL = 30


def _num(v: object) -> float:
    """Coerce an OpenRouter /credits response field to a finite float.

    total_credits and total_usage come back as ints/floats/strings depending
    on account state, and OpenRouter occasionally returns the literals
    "NaN" / "Infinity" for broken billing periods. Any non-numeric or
    non-finite value yields 0.0 so the JSON we return stays valid and the
    frontend doesn't have to special-case missing balances.
    """
    try:
        # `object` is too wide for float(); we want runtime coercion.
        n = float(v) if v is not None else 0.0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return n if math.isfinite(n) else 0.0


async def _check_openrouter() -> AccountProviderUsage:
    key = _settings.openrouter_api_key
    if not key:
        return AccountProviderUsage(provider="openrouter", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="openrouter", configured=True, error="API key invalid"
                )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            # total_credits and total_usage are both in USD; coerce safely.
            # OpenRouter may return ints/floats/strings; non-finite
            # values ("NaN", "Infinity") get coerced to 0.0 by _num().
            total_credits = _num(data.get("total_credits"))
            total_usage = _num(data.get("total_usage"))
            remaining = total_credits - total_usage

            return AccountProviderUsage(
                provider="openrouter",
                configured=True,
                spent_usd=round(total_usage, 4),
                limit_usd=round(total_credits, 4) if total_credits else None,
                remaining_usd=round(remaining, 4) if total_credits else None,
            )
        except Exception as exc:
            log.warning("openrouter_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openrouter", configured=True, error=str(exc)[:80]
            )


async def _check_kilo() -> AccountProviderUsage:
    key = _settings.kilo_api_key
    tier = _settings.kilo_tier

    # Resolve plan details from local YAML
    plan_label: str | None = None
    limit_usd: float | None = None
    try:
        plans = load_plans()
        plan = next((p for p in plans if p.tier == tier), None)
        if plan:
            plan_label = f"{tier.capitalize()} ${plan.monthly_usd:.0f}/mo"
            limit_usd = plan.paid_credits_usd
    except Exception as exc:
        log.warning("kilo_plan_load_failed", error=str(exc))

    if not key:
        return AccountProviderUsage(
            provider="kilo",
            configured=False,
            plan=plan_label,
            limit_usd=limit_usd,
        )

    # Validate key and get model count — no balance endpoint in Kilo gateway API
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{_settings.kilo_base_url}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="kilo", configured=True, plan=plan_label,
                    limit_usd=limit_usd, error="API key invalid",
                )
            resp.raise_for_status()
            model_count = len(resp.json().get("data") or [])
            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                plan=plan_label,
                limit_usd=limit_usd,
                model_count=model_count or None,
            )
        except Exception as exc:
            log.warning("kilo_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="kilo", configured=True, plan=plan_label,
                limit_usd=limit_usd, error=str(exc)[:80],
            )


_ACTIVITY_CACHE_KEY = "accounts:activity"
_ACTIVITY_CACHE_TTL = 900  # 15 min


def _to_int(v: object) -> int:
    """Analytics query returns counts/tokens as strings; coerce safely."""
    try:
        # `object` is too wide for int()/float(); we want runtime coercion.
        return int(float(v)) if v is not None else 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


async def get_activity() -> ActivityResponse:
    cached = await cache.get(_ACTIVITY_CACHE_KEY)
    if cached:
        return ActivityResponse.model_validate(cached)

    # Beta analytics query requires a management key; fall back to regular key.
    # We use /analytics/query (not /activity) because /activity excludes the
    # current UTC day until it closes — analytics/query includes today, matching
    # the OpenRouter dashboard exactly.
    key = _settings.openrouter_admin_key or _settings.openrouter_api_key
    if not key:
        return ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    body = {
        "metrics": ["request_count", "total_usage", "tokens_prompt", "tokens_completion"],
        "dimensions": ["model"],
        "order_by": {"field": "total_usage", "direction": "desc"},
    }

    ok = False
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.post(
                "https://openrouter.ai/api/v1/analytics/query",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            # Shape: {"data": {"data": [{model, request_count, total_usage,
            #   tokens_prompt, tokens_completion}, ...], "metadata": {...}}}
            rows = (resp.json().get("data") or {}).get("data") or []
            items = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                model_id = r.get("model")
                if not isinstance(model_id, str):
                    continue
                items.append(
                    ModelActivityItem(
                        model_id=model_id,
                        requests=_to_int(r.get("request_count")),
                        prompt_tokens=_to_int(r.get("tokens_prompt")),
                        completion_tokens=_to_int(r.get("tokens_completion")),
                        cost_usd=round(float(r.get("total_usage") or 0), 6),
                    )
                )
            items.sort(key=lambda x: x.cost_usd, reverse=True)
            result = ActivityResponse(items=items, fetched_at=datetime.now(UTC))
            ok = True
        except Exception as exc:
            log.warning("openrouter_activity_failed", error=str(exc))
            result = ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    await cache.set(
        _ACTIVITY_CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_ACTIVITY_CACHE_TTL if ok else _FAILURE_CACHE_TTL,
    )
    return result


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_CACHE_KEY)
    if cached:
        return AccountsUsage.model_validate(cached)

    openrouter, kilo = await asyncio.gather(
        _check_openrouter(),
        _check_kilo(),
    )
    result = AccountsUsage(
        openrouter=openrouter,
        kilo=kilo,
        fetched_at=datetime.now(UTC),
    )
    any_error = any(p.error for p in (openrouter, kilo))
    await cache.set(
        _CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_FAILURE_CACHE_TTL if any_error else _CACHE_TTL,
    )
    return result
