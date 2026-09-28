"""Check API key validity and fetch live credit usage where available.

Each provider has an async checker that returns an ``AccountProviderUsage``
record. Checkers are deliberately forgiving: they always return a populated
record (configured=True/False plus an optional ``error``) so a single failed
provider never breaks the dashboard. Fields that the provider does not expose
are left as ``None`` instead of being fabricated.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import (
    AccountProviderUsage,
    AccountsUsage,
    ActivityResponse,
    ModelActivityItem,
    QuotaWindow,
)
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
    """Coerce a provider balance field to a finite float.

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
        return AccountProviderUsage(
            provider="openrouter",
            configured=False,
            dashboard_url="https://openrouter.ai/settings/credits",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="openrouter",
                    configured=True,
                    dashboard_url="https://openrouter.ai/settings/credits",
                    error="API key invalid",
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
                currency="USD",
                dashboard_url="https://openrouter.ai/settings/credits",
                spent_usd=round(total_usage, 4),
                limit_usd=round(total_credits, 4) if total_credits else None,
                remaining_usd=round(remaining, 4) if total_credits else None,
            )
        except Exception as exc:
            log.warning("openrouter_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openrouter",
                configured=True,
                dashboard_url="https://openrouter.ai/settings/credits",
                error=str(exc)[:80],
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
            dashboard_url="https://kilo.ai/dashboard",
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
                    provider="kilo",
                    configured=True,
                    plan=plan_label,
                    limit_usd=limit_usd,
                    dashboard_url="https://kilo.ai/dashboard",
                    error="API key invalid",
                )
            resp.raise_for_status()
            model_count = len(resp.json().get("data") or [])
            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                plan=plan_label,
                limit_usd=limit_usd,
                model_count=model_count or None,
                dashboard_url="https://kilo.ai/dashboard",
            )
        except Exception as exc:
            log.warning("kilo_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                plan=plan_label,
                limit_usd=limit_usd,
                dashboard_url="https://kilo.ai/dashboard",
                error=str(exc)[:80],
            )


async def _check_minimax() -> AccountProviderUsage:
    """MiniMax Token Plan / coding plan balance probe.

    The mmx CLI calls an internal endpoint on api.minimax.chat to render the
    ``quota show`` view; we attempt the same surface with the user's API key.

    The live endpoint returns per-plan request counts and a remaining
    percent rather than USD amounts. We aggregate across plans and surface
    the worst (lowest) remaining percent so the dashboard shows a single
    status number rather than one row per plan.
    """
    key = _settings.minimax_api_key
    if not key:
        return AccountProviderUsage(
            provider="minimax",
            configured=False,
            dashboard_url="https://MiniMax.io/user-center/basic-information/interface-key",
        )

    headers = {"Authorization": f"Bearer {key}"}
    endpoints = (
        # Coding Plan / Token Plan quota surface used by mmx CLI.
        "https://api.MiniMax.chat/v1/api/openplatform/coding_plan/remains",
        # Some accounts use the public host.
        "https://api.MiniMax.io/v1/api/openplatform/coding_plan/remains",
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in endpoints:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 401:
                    return AccountProviderUsage(
                        provider="minimax",
                        configured=True,
                        dashboard_url=(
                            "https://MiniMax.io/user-center/basic-information/interface-key"
                        ),
                        error="API key invalid",
                    )
                if resp.status_code >= 400:
                    log.debug(
                        "minimax_check_status",
                        url=url,
                        status=resp.status_code,
                    )
                    continue
                data: dict[str, Any] = resp.json()
                # The live endpoint shape (api.MiniMax.io, confirmed against a
                # real coding-plan key 2026-09) is:
                #   {"base_resp": {"status_code": 0, ...},
                #    "model_remains": [
                #      {"model_name": "general",
                #       "current_interval_usage_count": 2,
                #       "current_interval_total_count": 3,
                #       "current_interval_remaining_percent": 86,
                #       "current_weekly_usage_count": 20,
                #       "current_weekly_total_count": 21,
                #       "current_weekly_remaining_percent": 98,
                #       ...}, ...]}
                # The .chat host often returns a base_resp error envelope
                # because that surface wants a session cookie, not a bare
                # API key. Fall through to the .io host before declaring
                # failure so we don't lie about quota unreachable.
                base = data.get("base_resp") if isinstance(data.get("base_resp"), dict) else None
                if base and base.get("status_code") not in (0, None):
                    log.debug(
                        "minimax_base_resp_error",
                        url=url,
                        code=base.get("status_code"),
                        msg=base.get("status_msg"),
                    )
                    continue
                plans = data.get("model_remains")
                if isinstance(plans, list) and plans:
                    windows: list[QuotaWindow] = []
                    worst_pct: float | None = None
                    for p in plans:
                        if not isinstance(p, dict):
                            continue
                        # Each model_remains entry carries BOTH a 5h interval
                        # and a weekly counter for the same model. We expand
                        # each entry into 1-2 windows so the dashboard can
                        # render each quota on its own row -- showing only
                        # the worst case across windows hides the fact that
                        # a healthy 5h window and a partly-used weekly window
                        # belong to the same model.
                        name = p.get("model_name")
                        if not isinstance(name, str) or not name:
                            name = "unknown"

                        interval_usage = _to_int(p.get("current_interval_usage_count"))
                        interval_limit = _to_int(p.get("current_interval_total_count"))
                        interval_pct_raw = p.get("current_interval_remaining_percent")
                        interval_pct = (
                            float(interval_pct_raw) if interval_pct_raw is not None else None
                        )

                        weekly_usage = _to_int(p.get("current_weekly_usage_count"))
                        weekly_limit = _to_int(p.get("current_weekly_total_count"))
                        weekly_pct_raw = p.get("current_weekly_remaining_percent")
                        weekly_pct = (
                            float(weekly_pct_raw) if weekly_pct_raw is not None else None
                        )

                        # Only emit a window when both the limit AND the
                        # remaining percent are present -- a window with
                        # usage but no limit would be a misleading "1 / ?"
                        # on the dashboard.
                        if interval_limit > 0 and interval_pct is not None:
                            windows.append(
                                QuotaWindow(
                                    name=name,
                                    period="5h",
                                    usage=interval_usage,
                                    limit=interval_limit,
                                    remaining_percent=interval_pct,
                                )
                            )
                            if worst_pct is None or interval_pct < worst_pct:
                                worst_pct = interval_pct
                        if weekly_limit > 0 and weekly_pct is not None:
                            windows.append(
                                QuotaWindow(
                                    name=name,
                                    period="weekly",
                                    usage=weekly_usage,
                                    limit=weekly_limit,
                                    remaining_percent=weekly_pct,
                                )
                            )
                            if worst_pct is None or weekly_pct < worst_pct:
                                worst_pct = weekly_pct

                    return AccountProviderUsage(
                        provider="minimax",
                        configured=True,
                        currency="REQS",
                        dashboard_url=(
                            "https://MiniMax.io/user-center/basic-information/interface-key"
                        ),
                        # plan badge is fixed (single Token Plan subscription);
                        # the model_remains array is a list of QUOTA WINDOWS
                        # inside that subscription, not a list of plans.
                        plan="Token Plan",
                        quota_windows=windows or None,
                        remaining_percent=round(worst_pct, 1) if worst_pct is not None else None,
                    )
                # HTTP 200, no error envelope, no plan rows. Key is valid but
                # the surface returned nothing structured -- report active.
                return AccountProviderUsage(
                    provider="minimax",
                    configured=True,
                    dashboard_url=(
                        "https://MiniMax.io/user-center/basic-information/interface-key"
                    ),
                )
            except Exception as exc:
                log.warning("minimax_check_failed", url=url, error=str(exc))
                continue

        return AccountProviderUsage(
            provider="minimax",
            configured=True,
            dashboard_url=(
                "https://MiniMax.io/user-center/basic-information/interface-key"
            ),
            error="quota endpoint unreachable",
        )


async def _check_anthropic() -> AccountProviderUsage:
    """Anthropic balance probe.

    Anthropic exposes ``/v1/organizations/{org_id}/billing/balance`` but the
    org_id is tenant-scoped; with the admin key we first look up the org id
    via ``/v1/organizations`` and then query the balance. Falls back to a
    plain key-validity probe when no admin key is configured.
    """
    admin_key = _settings.anthropic_admin_key
    user_key = _settings.anthropic_api_key
    key = admin_key or user_key
    if not key:
        return AccountProviderUsage(
            provider="anthropic",
            configured=False,
            dashboard_url="https://console.anthropic.com/settings/billing",
        )

    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            orgs_resp = await client.get(
                "https://api.anthropic.com/v1/organizations",
                headers=headers,
            )
            if orgs_resp.status_code == 401:
                return AccountProviderUsage(
                    provider="anthropic",
                    configured=True,
                    dashboard_url="https://console.anthropic.com/settings/billing",
                    error="API key invalid",
                )
            if orgs_resp.status_code == 403:
                return AccountProviderUsage(
                    provider="anthropic",
                    configured=True,
                    dashboard_url="https://console.anthropic.com/settings/billing",
                    error="admin key required for billing",
                )
            orgs_resp.raise_for_status()
            orgs = (orgs_resp.json() or {}).get("data") or []
            if not orgs:
                return AccountProviderUsage(
                    provider="anthropic",
                    configured=True,
                    dashboard_url="https://console.anthropic.com/settings/billing",
                    error="no organization for this key",
                )
            org_id = orgs[0].get("id")
            if not isinstance(org_id, str):
                return AccountProviderUsage(
                    provider="anthropic",
                    configured=True,
                    dashboard_url="https://console.anthropic.com/settings/billing",
                    error="organization id missing",
                )
            bal_resp = await client.get(
                f"https://api.anthropic.com/v1/organizations/{org_id}/billing/balance",
                headers=headers,
            )
            bal_resp.raise_for_status()
            bal = bal_resp.json() or {}
            # ``available_credit`` is returned in DOLLARS (e.g. 50.0 means
            # $50 remaining). Older docs sometimes showed cents; the live admin
            # endpoint has used dollars since 2025. If Anthropic ever rotates
            # this back, multiply through here rather than at the UI layer.
            remaining_usd = _num(bal.get("available_credit") or bal.get("balance"))
            used_usd = _num(bal.get("used_credit") or bal.get("used"))
            currency = str(bal.get("currency") or "USD")
            return AccountProviderUsage(
                provider="anthropic",
                configured=True,
                currency=currency,
                dashboard_url="https://console.anthropic.com/settings/billing",
                spent_usd=round(used_usd, 4) if used_usd else None,
                remaining_usd=round(remaining_usd, 4) if remaining_usd else None,
            )
        except Exception as exc:
            log.warning("anthropic_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="anthropic",
                configured=True,
                dashboard_url="https://console.anthropic.com/settings/billing",
                error=str(exc)[:80],
            )


async def _check_openai() -> AccountProviderUsage:
    """OpenAI billing probe.

    ``/v1/dashboard/billing/credit_grants`` returns the active grant window
    (total_granted, total_used, total_available, period_start/end). Requires
    an admin key (``sk-admin-...``); with a regular key the endpoint returns
    403 and we surface that as ``error`` so the user knows to rotate.
    """
    admin_key = _settings.openai_admin_key
    user_key = _settings.openai_api_key
    key = admin_key or user_key
    if not key:
        return AccountProviderUsage(
            provider="openai",
            configured=False,
            dashboard_url="https://platform.openai.com/account/billing/overview",
        )

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://api.openai.com/v1/dashboard/billing/credit_grants",
                headers=headers,
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="openai",
                    configured=True,
                    dashboard_url="https://platform.openai.com/account/billing/overview",
                    error="API key invalid",
                )
            if resp.status_code == 403:
                return AccountProviderUsage(
                    provider="openai",
                    configured=user_key and not admin_key,
                    dashboard_url="https://platform.openai.com/account/billing/overview",
                    error="admin key required for billing",
                )
            resp.raise_for_status()
            grants = resp.json() or {}
            total_granted = _num(grants.get("total_granted"))
            total_used = _num(grants.get("total_used"))
            total_available = _num(grants.get("total_available"))
            return AccountProviderUsage(
                provider="openai",
                configured=True,
                currency="USD",
                dashboard_url="https://platform.openai.com/account/billing/overview",
                spent_usd=round(total_used, 4) if total_used else None,
                limit_usd=round(total_granted, 4) if total_granted else None,
                remaining_usd=round(total_available, 4) if total_available else None,
                period_start=str(grants.get("period_start") or "") or None,
                period_end=str(grants.get("period_end") or "") or None,
            )
        except Exception as exc:
            log.warning("openai_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="openai",
                configured=True,
                dashboard_url="https://platform.openai.com/account/billing/overview",
                error=str(exc)[:80],
            )


async def _check_deepseek() -> AccountProviderUsage:
    """DeepSeek user balance probe.

    ``GET /user/balance`` returns a list of currency entries with
    ``total_balance`` and ``topped_up_balance`` (string USD). No admin key is
    required — the user key is enough.
    """
    key = _settings.deepseek_api_key
    if not key:
        return AccountProviderUsage(
            provider="deepseek",
            configured=False,
            dashboard_url="https://platform.deepseek.com/usage",
        )

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers=headers,
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="deepseek",
                    configured=True,
                    dashboard_url="https://platform.deepseek.com/usage",
                    error="API key invalid",
                )
            resp.raise_for_status()
            entries = (resp.json() or {}).get("balance_infos") or []
            # DeepSeek returns multiple currencies (USD + CNY); prefer USD.
            usd = next(
                (e for e in entries if str(e.get("currency", "")).upper() == "USD"),
                entries[0] if entries else None,
            )
            if not usd:
                return AccountProviderUsage(
                    provider="deepseek",
                    configured=True,
                    dashboard_url="https://platform.deepseek.com/usage",
                )
            total = _num(usd.get("total_balance"))
            granted = _num(usd.get("granted_balance"))
            topped_up = _num(usd.get("topped_up_balance"))
            spent = (granted + topped_up) - total
            return AccountProviderUsage(
                provider="deepseek",
                configured=True,
                currency=str(usd.get("currency") or "USD"),
                dashboard_url="https://platform.deepseek.com/usage",
                spent_usd=round(spent, 4) if spent > 0 else 0.0,
                remaining_usd=round(total, 4) if total else None,
            )
        except Exception as exc:
            log.warning("deepseek_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="deepseek",
                configured=True,
                dashboard_url="https://platform.deepseek.com/usage",
                error=str(exc)[:80],
            )


async def _check_alibaba() -> AccountProviderUsage:
    """Alibaba DashScope (Bailian) account probe.

    DashScope does not expose a public per-user balance REST endpoint that
    is reliably documented; we validate the key against the free
    ``GET /api/v1/models`` metadata endpoint (200 on valid key, 401/403 on
    bad key) and surface a deep link to the console billing page for actual
    spend numbers. We deliberately do NOT call the billable text-generation
    endpoint here -- that would charge real tokens and pollute usage history.
    """
    key = _settings.alibaba_api_key
    if not key:
        return AccountProviderUsage(
            provider="alibaba",
            configured=False,
            dashboard_url="https://bailian.console.aliyun.com/",
        )

    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                "https://dashscope.aliyuncs.com/api/v1/models",
                headers=headers,
            )
            if resp.status_code in (401, 403):
                return AccountProviderUsage(
                    provider="alibaba",
                    configured=True,
                    dashboard_url="https://bailian.console.aliyun.com/",
                    error="API key invalid",
                )
            resp.raise_for_status()
            return AccountProviderUsage(
                provider="alibaba",
                configured=True,
                currency="CNY",
                dashboard_url="https://bailian.console.aliyun.com/",
            )
        except Exception as exc:
            log.warning("alibaba_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="alibaba",
                configured=True,
                dashboard_url="https://bailian.console.aliyun.com/",
                error=str(exc)[:80],
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
                        # _num, not float(): one malformed or non-finite
                        # total_usage must not blank the whole usage table.
                        cost_usd=round(_num(r.get("total_usage")), 6),
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

    openrouter, kilo, minimax, anthropic, openai, deepseek, alibaba = (
        await asyncio.gather(
            _check_openrouter(),
            _check_kilo(),
            _check_minimax(),
            _check_anthropic(),
            _check_openai(),
            _check_deepseek(),
            _check_alibaba(),
            return_exceptions=False,
        )
    )
    result = AccountsUsage(
        openrouter=openrouter,
        kilo=kilo,
        minimax=minimax,
        anthropic=anthropic,
        openai=openai,
        deepseek=deepseek,
        alibaba=alibaba,
        fetched_at=datetime.now(UTC),
    )
    any_error = any(p.error for p in (openrouter, kilo))
    await cache.set(
        _CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_FAILURE_CACHE_TTL if any_error else _CACHE_TTL,
    )
    return result
