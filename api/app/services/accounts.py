"""Check API key validity and fetch live credit usage where available."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

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

            # total_credits and total_usage are both in USD
            total_credits = float(data.get("total_credits") or 0)
            total_usage = float(data.get("total_usage") or 0)
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
                "https://api.kilo.ai/api/gateway/models",
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


async def _check_openai() -> AccountProviderUsage:
    admin_key = _settings.openai_admin_key
    regular_key = _settings.openai_api_key
    if not admin_key and not regular_key:
        return AccountProviderUsage(provider="openai", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        if admin_key:
            # Use the cost report as both validation and data source
            try:
                start_time = int((datetime.now(UTC) - timedelta(days=30)).timestamp())
                period_start = (datetime.now(UTC) - timedelta(days=30)).strftime("%b %d")
                resp = await client.get(
                    "https://api.openai.com/v1/organization/costs",
                    headers={"Authorization": f"Bearer {admin_key}"},
                    params={"start_time": start_time, "limit": 30, "bucket_width": "1d"},
                )
                if resp.status_code == 401:
                    return AccountProviderUsage(
                        provider="openai", configured=True, error="Admin key invalid"
                    )
                resp.raise_for_status()
                buckets = resp.json().get("data", [])
                total = sum(
                    float(r.get("amount", {}).get("value", 0))
                    for b in buckets
                    for r in b.get("results", [])
                )
                return AccountProviderUsage(
                    provider="openai",
                    configured=True,
                    spent_usd=round(total, 4),
                    period_start=period_start,
                )
            except Exception as exc:
                log.warning("openai_costs_failed", error=str(exc))
                return AccountProviderUsage(
                    provider="openai", configured=True, error=str(exc)[:80]
                )
        else:
            # Regular key only — just validate
            try:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {regular_key}"},
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
    admin_key = _settings.anthropic_admin_key
    regular_key = _settings.anthropic_api_key
    if not admin_key and not regular_key:
        return AccountProviderUsage(provider="anthropic", configured=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        if not admin_key:
            # Regular key only — just validate
            try:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": regular_key, "anthropic-version": "2023-06-01"},
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

        # Fetch 30-day cost report with admin key
        try:
            now = datetime.now(UTC)
            starting_at = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            ending_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            period_start = (now - timedelta(days=30)).strftime("%b %d")
            resp = await client.get(
                "https://api.anthropic.com/v1/organizations/cost_report",
                headers={"x-api-key": admin_key, "anthropic-version": "2023-06-01"},
                params={"starting_at": starting_at, "ending_at": ending_at, "bucket_width": "1d"},
            )
            resp.raise_for_status()
            buckets = resp.json().get("data", [])
            total = sum(
                float(c.get("amount", {}).get("value", 0))
                for b in buckets
                for c in b.get("costs", [])
            )
            return AccountProviderUsage(
                provider="anthropic",
                configured=True,
                spent_usd=round(total, 4),
                period_start=period_start,
            )
        except Exception as exc:
            log.warning("anthropic_costs_failed", error=str(exc))
            return AccountProviderUsage(provider="anthropic", configured=True, error=str(exc)[:80])


_ACTIVITY_CACHE_KEY = "accounts:activity"
_ACTIVITY_CACHE_TTL = 900  # 15 min


async def get_activity() -> ActivityResponse:
    cached = await cache.get(_ACTIVITY_CACHE_KEY)
    if cached:
        return ActivityResponse.model_validate(cached)

    key = _settings.openrouter_api_key
    if not key:
        return ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                "https://openrouter.ai/api/v1/activity",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            raw = resp.json()
            log.debug("openrouter_activity_raw", keys=list(raw.keys()))

            # Response shape: {"data": [{model_id, requests, prompt_tokens,
            #   completion_tokens, total_cost / cost / ...}, ...]}
            entries = raw.get("data") or raw.get("activity") or []
            # Aggregate by model_id — API returns one row per key/date bucket
            agg: dict[str, ModelActivityItem] = {}
            for e in entries:
                model_id = e.get("model") or e.get("model_id") or ""
                if not model_id:
                    continue
                cost = float(e.get("total_cost") or e.get("cost") or e.get("usage") or 0)
                reqs = int(e.get("requests") or e.get("count") or 0)
                p_tok = int(e.get("prompt_tokens") or e.get("input_tokens") or 0)
                c_tok = int(e.get("completion_tokens") or e.get("output_tokens") or 0)
                if model_id in agg:
                    existing = agg[model_id]
                    agg[model_id] = ModelActivityItem(
                        model_id=model_id,
                        requests=existing.requests + reqs,
                        prompt_tokens=existing.prompt_tokens + p_tok,
                        completion_tokens=existing.completion_tokens + c_tok,
                        cost_usd=round(existing.cost_usd + cost, 6),
                    )
                else:
                    agg[model_id] = ModelActivityItem(
                        model_id=model_id,
                        requests=reqs,
                        prompt_tokens=p_tok,
                        completion_tokens=c_tok,
                        cost_usd=round(cost, 6),
                    )
            items = sorted(agg.values(), key=lambda x: x.cost_usd, reverse=True)
            result = ActivityResponse(items=items, fetched_at=datetime.now(UTC))
        except Exception as exc:
            log.warning("openrouter_activity_failed", error=str(exc))
            result = ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    await cache.set(_ACTIVITY_CACHE_KEY, result.model_dump(mode="json"), ttl=_ACTIVITY_CACHE_TTL)
    return result


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
