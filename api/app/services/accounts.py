"""Check API key validity and fetch live credit usage where available."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import AccountProviderUsage, AccountsUsage, ActivityResponse, ModelActivityItem
from app.services.cache import cache
from app.services.kilo import load_plans

log = get_logger(__name__)
_settings = get_settings()

_USAGE_CACHE_KEY = "accounts:usage"
_USAGE_CACHE_TTL = 120  # 2 min — balance data should be fairly fresh
# A transient upstream error is cached only briefly, so one 5xx does not
# blank the widgets for the full TTL (but we still don't hammer upstream).
_FAILURE_CACHE_TTL = 30

_OPENAI_COSTS_URL = "https://api.openai.com/v1/organization/costs"
_ANTHROPIC_COST_REPORT_URL = "https://api.anthropic.com/v1/organizations/cost_report"
_MAX_PAGES = 20


async def _openai_cost_buckets(
    client: httpx.AsyncClient, admin_key: str, *, days: int, group_by_line_item: bool
) -> list[dict[str, Any]] | None:
    """All daily cost buckets for the last ``days`` days, following pagination.

    Returns None when the key is rejected (401). Raises on other HTTP errors.
    """
    params: dict[str, Any] = {
        "start_time": int((datetime.now(UTC) - timedelta(days=days)).timestamp()),
        "bucket_width": "1d",
        "limit": days,
    }
    if group_by_line_item:
        params["group_by"] = "line_item"
    buckets: list[dict[str, Any]] = []
    for _ in range(_MAX_PAGES):
        resp = await client.get(
            _OPENAI_COSTS_URL,
            headers={"Authorization": f"Bearer {admin_key}"},
            params=params,
        )
        if resp.status_code == 401:
            return None
        resp.raise_for_status()
        body = resp.json()
        buckets.extend(body.get("data") or [])
        next_page = body.get("next_page")
        if not body.get("has_more") or not next_page:
            break
        params["page"] = next_page
    return buckets


def _openai_amount(result: dict[str, Any]) -> float:
    amount = result.get("amount")
    if not isinstance(amount, dict):
        return 0.0
    try:
        return float(amount.get("value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _openai_model_from_line_item(result: dict[str, Any]) -> str:
    """Model name from a grouped cost result.

    With ``group_by=line_item`` each result carries a ``line_item`` string
    such as ``"gpt-4o-2024-08-06, input"``; the part before the first comma
    is the model (or product) name.
    """
    line_item = result.get("line_item")
    if isinstance(line_item, str) and line_item.strip():
        return line_item.split(",", 1)[0].strip()
    return "unknown"


async def _anthropic_cost_buckets(
    client: httpx.AsyncClient, admin_key: str, *, days: int
) -> list[dict[str, Any]]:
    """All daily cost-report buckets for the last ``days`` days.

    The endpoint returns at most ``limit`` (max 31, default 7) buckets per
    page, so an unpaginated call silently truncates to about a week.
    """
    now = datetime.now(UTC)
    params: dict[str, Any] = {
        "starting_at": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1d",
        "limit": 31,
    }
    buckets: list[dict[str, Any]] = []
    for _ in range(_MAX_PAGES):
        resp = await client.get(
            _ANTHROPIC_COST_REPORT_URL,
            headers={"x-api-key": admin_key, "anthropic-version": "2023-06-01"},
            params=params,
        )
        resp.raise_for_status()
        body = resp.json()
        buckets.extend(body.get("data") or [])
        next_page = body.get("next_page")
        if not body.get("has_more") or not next_page:
            break
        params["page"] = next_page
    return buckets


def _anthropic_amount_usd(result: dict[str, Any]) -> float:
    """Cost-report amounts are decimal strings in the lowest currency unit (cents)."""
    try:
        return float(result.get("amount") or 0) / 100.0
    except (TypeError, ValueError):
        return 0.0


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
                period_start = (datetime.now(UTC) - timedelta(days=30)).strftime("%b %d")
                buckets = await _openai_cost_buckets(
                    client, admin_key, days=30, group_by_line_item=False
                )
                if buckets is None:
                    return AccountProviderUsage(
                        provider="openai", configured=True, error="Admin key invalid"
                    )
                total = sum(_openai_amount(r) for b in buckets for r in b.get("results", []))
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
            period_start = (datetime.now(UTC) - timedelta(days=30)).strftime("%b %d")
            buckets = await _anthropic_cost_buckets(client, admin_key, days=30)
            total = sum(
                _anthropic_amount_usd(r) for b in buckets for r in b.get("results", [])
            )
            return AccountProviderUsage(
                provider="anthropic",
                configured=True,
                spent_usd=round(total, 4),
                period_start=period_start,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                return AccountProviderUsage(
                    provider="anthropic", configured=True, error="Admin key invalid"
                )
            log.warning("anthropic_costs_failed", error=str(exc))
            return AccountProviderUsage(provider="anthropic", configured=True, error=str(exc)[:80])
        except Exception as exc:
            log.warning("anthropic_costs_failed", error=str(exc))
            return AccountProviderUsage(provider="anthropic", configured=True, error=str(exc)[:80])


_OPENROUTER_ACTIVITY_CACHE_KEY = "accounts:activity"
_OPENROUTER_ACTIVITY_CACHE_TTL = 900  # 15 min

_OPENAI_ACTIVITY_CACHE_KEY = "accounts:openai_activity"
_OPENAI_ACTIVITY_CACHE_TTL = 900  # 15 min


async def get_openai_activity() -> ActivityResponse:
    """Fetch OpenAI costs by model from the cost report API (last 30 days)."""
    cached = await cache.get(_OPENAI_ACTIVITY_CACHE_KEY)
    if cached:
        return ActivityResponse.model_validate(cached)

    admin_key = _settings.openai_admin_key
    if not admin_key:
        return ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    ok = False
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            buckets = await _openai_cost_buckets(
                client, admin_key, days=30, group_by_line_item=True
            )
            if buckets is None:
                raise RuntimeError("OpenAI admin key invalid")

            # Aggregate by model; the Costs API has no request/token counts.
            costs: dict[str, float] = {}
            for bucket in buckets:
                for r in bucket.get("results", []):
                    model_id = _openai_model_from_line_item(r)
                    costs[model_id] = costs.get(model_id, 0.0) + _openai_amount(r)

            items = sorted(
                (
                    ModelActivityItem(
                        model_id=model_id,
                        requests=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        cost_usd=round(cost, 4),
                    )
                    for model_id, cost in costs.items()
                ),
                key=lambda x: x.cost_usd,
                reverse=True,
            )
            result = ActivityResponse(items=items, fetched_at=datetime.now(UTC))
            ok = True
        except Exception as exc:
            log.warning("openai_activity_failed", error=str(exc))
            result = ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    await cache.set(
        _OPENAI_ACTIVITY_CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_OPENAI_ACTIVITY_CACHE_TTL if ok else _FAILURE_CACHE_TTL,
    )
    return result


async def get_activity() -> ActivityResponse:
    cached = await cache.get(_OPENROUTER_ACTIVITY_CACHE_KEY)
    if cached:
        return ActivityResponse.model_validate(cached)

    key = _settings.openrouter_api_key
    if not key:
        return ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    ok = False
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
            ok = True
        except Exception as exc:
            log.warning("openrouter_activity_failed", error=str(exc))
            result = ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    await cache.set(
        _OPENROUTER_ACTIVITY_CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_OPENROUTER_ACTIVITY_CACHE_TTL if ok else _FAILURE_CACHE_TTL,
    )
    return result


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_USAGE_CACHE_KEY)
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
    any_error = any(p.error for p in (openrouter, kilo, openai, anthropic))
    await cache.set(
        _USAGE_CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_FAILURE_CACHE_TTL if any_error else _USAGE_CACHE_TTL,
    )
    return result
