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

log = get_logger(__name__)
_settings = get_settings()

_CACHE_KEY = "accounts:usage"
_CACHE_TTL = 120  # 2 min — balance data should be fairly fresh


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
    """Kilo Pass usage probe.

    Two API surfaces are useful here:

    1. The gateway ``/models`` endpoint on ``api.kilo.ai`` returns the
       list of accessible models -- surface the count.
    2. The Cloud user object on ``app.kilo.ai/api/user`` returns lifetime
       microdollar counts (``microdollars_used``,
       ``total_microdollars_acquired``). Microdollars are 1e-6 USD.

    Remaining credit is ``total_microdollars_acquired - microdollars_used``.
    That is the same figure the Kilo console shows as "Remaining Personal
    Credits" -- verified against the live console at 349.05 - 325.27 =
    $23.78.

    Do NOT use ``kilo_pass_threshold`` as a limit. It is the spend level at
    which Kilo Pass benefits kick in, NOT a budget: it is unrelated to the
    credit balance, so ``threshold - used`` renders a confident, completely
    fabricated "remaining" figure. An earlier revision did exactly that and
    showed $16.35 where the console showed $23.78.

    The console's per-cycle *Personal workspace* breakdown (this month's
    usage / paid / available bonus / renews-in-N-days) is only fetched by
    the Cloud console's client-side React fetch -- it requires a browser
    session cookie, not the API key. Kilo does not expose that surface
    publicly, so the card reports lifetime credit rather than this month's
    allowance.
    """
    key = _settings.kilo_api_key

    if not key:
        return AccountProviderUsage(
            provider="kilo",
            configured=False,
            dashboard_url="https://kilo.ai/dashboard",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Gateway API: model count
            resp = await client.get(
                f"{_settings.kilo_base_url}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 401:
                return AccountProviderUsage(
                    provider="kilo",
                    configured=True,
                    error="API key invalid",
                )
            resp.raise_for_status()
            model_count = len(resp.json().get("data") or [])

            # Cloud API: lifetime personal credit, returned in microdollars.
            # The per-cycle "Personal workspace" breakdown the console shows is
            # browser-session-only and unreachable with an API key, so the card
            # reports lifetime rather than this month's allowance. The 6s
            # timeout here is generous; on normal hits this is <500ms.
            try:
                user_resp = await client.get(
                    "https://app.kilo.ai/api/user",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Accept": "application/json",
                    },
                    timeout=6.0,
                )
            except Exception as exc:
                log.warning("kilo_user_fetch_failed", error=str(exc))
                user_resp = None

            spent_usd: float | None = None
            limit_usd: float | None = None
            if user_resp is not None and user_resp.status_code == 200:
                user = user_resp.json() or {}
                spent_raw = user.get("microdollars_used")
                acquired_raw = user.get("total_microdollars_acquired")
                if spent_raw is not None:
                    spent_usd = round(float(spent_raw) / 1_000_000, 4)
                if acquired_raw is not None:
                    # Lifetime credits acquired is the real denominator:
                    # remaining = acquired - used is the console's
                    # "Remaining Personal Credits" figure.
                    limit_usd = round(float(acquired_raw) / 1_000_000, 4)

            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                currency="USD",
                spent_usd=spent_usd,
                limit_usd=limit_usd,
                remaining_usd=round(limit_usd - spent_usd, 4)
                if (spent_usd is not None and limit_usd is not None)
                else None,
                model_count=model_count or None,
                error=None,
                # Kilo exposes no per-cycle allowance via the API key, so we
                # label the numbers as lifetime credit rather than implying
                # they are this month's budget.
                plan="Lifetime credit" if spent_usd is not None else None,
            )
        except Exception as exc:
            log.warning("kilo_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="kilo",
                configured=True,
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

                        # Only require the remaining percent to emit a
                        # window. The limit can legitimately be 0 for an
                        # "unlimited" allowance (e.g. the operator's
                        # general plan returns total_count=0 with a real
                        # remaining percent); dropping those hides the
                        # healthy quota from the dashboard. A usage > 0
                        # with limit = 0 would be a vendor bug -- we
                        # surface those with limit=0 and let the UI
                        # render the row without a "/limit" suffix.
                        if interval_pct is not None:
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
                        if weekly_pct is not None:
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


async def _check_deepseek() -> AccountProviderUsage:
    """DeepSeek user balance probe.

    ``GET /user/balance`` returns:

    .. code-block:: json

        {
          "is_available": true,
          "balance_infos": [
            {"currency": "USD",
             "total_balance": "2.75",
             "granted_balance": "0.00",
             "topped_up_balance": "2.75"}
          ]
        }

    Per the API reference, ``total_balance`` is "the total available balance,
    INCLUDING the granted balance and the topped-up balance" -- i.e.
    ``total == granted + topped_up`` by construction. An earlier revision
    derived ``spent = granted + topped_up - total``, which is therefore
    identically zero and rendered a "Used" row that was never a real spend
    figure. DeepSeek exposes no usage/spend total on this endpoint, so we
    report no ``spent_usd`` at all rather than fabricate one.

    We do surface ``is_available``: when it is false the balance cannot cover
    an API call, which is the operationally meaningful alarm state.

    DeepSeek returns multiple currencies (USD + CNY); we prefer USD. Each
    entry breaks the total into *granted* (free credits the vendor gave)
    vs *topped-up* (cash the operator paid in). We surface both so the
    card shows whether the remaining balance is bonus cash or real money.
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
            payload = resp.json() or {}
            entries = payload.get("balance_infos") or []
            # Prefer USD; fall back to the first entry if no USD present.
            usd = next(
                (e for e in entries if str(e.get("currency", "")).upper() == "USD"),
                entries[0] if entries else None,
            )
            if not usd:
                return AccountProviderUsage(
                    provider="deepseek",
                    configured=True,
                    currency=str(payload.get("currency") or "USD"),
                    dashboard_url="https://platform.deepseek.com/usage",
                )
            total = _num(usd.get("total_balance"))
            granted = _num(usd.get("granted_balance"))
            topped_up = _num(usd.get("topped_up_balance"))
            # `is_available` is DeepSeek's own "balance can cover a call"
            # flag. False is the alarm state, but it does NOT invalidate the
            # balance figures -- so it goes in `warning`, not `error`, and the
            # card still shows the remaining balance and its paid/free split.
            # `is not False` (rather than truthiness) so an explicit null
            # field is treated as "unknown", not as a false alarm.
            available = payload.get("is_available", True) is not False
            return AccountProviderUsage(
                provider="deepseek",
                configured=True,
                currency=str(usd.get("currency") or "USD"),
                dashboard_url="https://platform.deepseek.com/usage",
                # No spent_usd: DeepSeek's balance endpoint is a snapshot,
                # not a ledger (see the docstring). Deriving a spend figure
                # from it is impossible.
                remaining_usd=round(total, 4) if total else None,
                granted_usd=round(granted, 4) if granted else None,
                topped_up_usd=round(topped_up, 4) if topped_up else None,
                warning=None if available else "balance too low for API calls",
            )
        except Exception as exc:
            log.warning("deepseek_check_failed", error=str(exc))
            return AccountProviderUsage(
                provider="deepseek",
                configured=True,
                dashboard_url="https://platform.deepseek.com/usage",
                error=str(exc)[:80],
            )


async def _check_anthropic() -> AccountProviderUsage:
    """Stub — Anthropic was removed from the dashboard (see MR !19). The
    admin API's billing endpoints require an org-scoped admin key with the
    ``billing:read`` scope, which the operator's existing key does not have.
    The browser session is the only path to subscription usage. Kept here
    as a no-op stub so internal callers that still import the symbol don't
    break — the function returns an unconfigured record.
    """
    return AccountProviderUsage(
        provider="anthropic",
        configured=False,
        dashboard_url="https://console.anthropic.com/settings/billing",
    )


async def _check_openai() -> AccountProviderUsage:
    """Stub — OpenAI was removed from the dashboard (see MR !19). The
    /v1/dashboard/billing/credit_grants endpoint now requires a browser
    session key; admin/project secret keys return 403. Browser-only.
    """
    return AccountProviderUsage(
        provider="openai",
        configured=False,
        dashboard_url="https://platform.openai.com/account/billing/overview",
    )


async def _check_alibaba() -> AccountProviderUsage:
    """Stub — Alibaba DashScope / Bailian was removed from the dashboard
    (see MR !19). The operator's key works in the console but every
    documented REST endpoint rejects it (``sk-sp-`` prefix, 114-byte
    length is not a recognized key format). The ``bailian.aliyuncs.com``
    Bailian-specific host returns ``API令牌认证失败`` for this key.
    """
    return AccountProviderUsage(
        provider="alibaba",
        configured=False,
        dashboard_url="https://bailian.console.aliyun.com/",
    )


# Reference the no-op stubs so ruff doesn't flag them as unused; the gather
# below still calls the four live providers we keep on the dashboard.
_check_anthropic  # noqa: B018  (kept for back-compat / future re-add)
_check_openai  # noqa: B018
_check_alibaba  # noqa: B018


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
    # current UTC day until it closes -- analytics/query includes today, matching
    # the OpenRouter dashboard exactly.
    key = _settings.openrouter_admin_key or _settings.openrouter_api_key
    if not key:
        return ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    body = {
        "metrics": ["request_count", "total_usage", "tokens_prompt", "tokens_completion"],
        "dimensions": ["model"],
        "order_by": {"field": "total_usage", "direction": "desc"},
    }

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
        except Exception as exc:
            log.warning("openrouter_activity_failed", error=str(exc))
            result = ActivityResponse(items=[], fetched_at=datetime.now(UTC))

    await cache.set(_ACTIVITY_CACHE_KEY, result.model_dump(mode="json"), ttl=_ACTIVITY_CACHE_TTL)
    return result


async def get_usage() -> AccountsUsage:
    cached = await cache.get(_CACHE_KEY)
    if cached:
        return AccountsUsage.model_validate(cached)

    openrouter, kilo, minimax, deepseek = await asyncio.gather(
        _check_openrouter(),
        _check_kilo(),
        _check_minimax(),
        _check_deepseek(),
        return_exceptions=False,
    )
    result = AccountsUsage(
        openrouter=openrouter,
        kilo=kilo,
        minimax=minimax,
        deepseek=deepseek,
        fetched_at=datetime.now(UTC),
    )
    await cache.set(_CACHE_KEY, result.model_dump(mode="json"), ttl=_CACHE_TTL)
    return result
