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
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.logging import get_logger
from app.schemas import (
    AccountBalance,
    AccountProviderUsage,
    AccountsUsage,
    ActivityGroupBy,
    ActivityPeriod,
    ActivityPeriodKey,
    ActivityResponse,
    ActivityTotals,
    ModelActivityItem,
    QuotaWindow,
)
from app.services.cache import cache

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


async def _kilo_balance(
    client: httpx.AsyncClient,
    origin: str,
    key: str,
    name: str,
    org_id: str | None,
) -> AccountBalance | None:
    """One account's balance from ``/api/profile/balance``, or None on failure.

    A missing, non-numeric or non-finite balance yields None rather than
    $0 -- a fabricated zero would read as "account empty".
    """
    headers = {"Authorization": f"Bearer {key}"}
    if org_id:
        headers["x-kilocode-organizationid"] = org_id
    try:
        resp = await client.get(
            f"{origin}/api/profile/balance", headers=headers, timeout=6.0
        )
        resp.raise_for_status()
        body = resp.json() or {}
        balance = float(body["balance"])
        if not math.isfinite(balance):
            raise ValueError(f"non-finite balance {body['balance']!r}")
    except Exception as exc:
        log.warning("kilo_balance_failed", account=name, error=str(exc))
        return None
    return AccountBalance(
        name=name,
        balance_usd=round(balance, 4),
        depleted=body.get("isDepleted") is True,
    )


async def _check_kilo() -> AccountProviderUsage:
    """Kilo remaining balance, per account.

    Uses the same calls the Kilo Code extension makes to show its balance:

    1. The gateway ``/models`` endpoint validates the key and gives the
       model count.
    2. ``GET /api/profile`` lists the organizations the key belongs to and
       whether it has a personal account.
    3. ``GET /api/profile/balance`` returns ``{"balance", "isDepleted"}``
       for the personal account; with an ``x-kilocode-organizationid``
       header it returns that organization's balance instead.

    Each account is reported on its own row. Lifetime counters from
    ``app.kilo.ai/api/user`` (``microdollars_used`` and friends) are not
    used: they describe history, not what is left to spend.
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

            # Profile/balance live on the gateway's origin (api.kilo.ai),
            # not under its /api/gateway path.
            base = httpx.URL(_settings.kilo_base_url)
            origin = f"{base.scheme}://{base.netloc.decode()}"
            accounts_to_check: list[tuple[str, str | None]] = [("Personal", None)]
            profile_failed = False
            try:
                prof_resp = await client.get(
                    f"{origin}/api/profile",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=6.0,
                )
                prof_resp.raise_for_status()
                profile = prof_resp.json() or {}
                if profile.get("hasPersonalAccount") is False:
                    accounts_to_check = []
                accounts_to_check += [
                    (str(o.get("name") or o["id"]), str(o["id"]))
                    for o in profile.get("organizations") or []
                    if isinstance(o, dict) and o.get("id")
                ]
            except Exception as exc:
                # Without the profile we cannot enumerate organizations, but
                # the personal balance needs no org id -- still report it.
                log.warning("kilo_profile_failed", error=str(exc))
                profile_failed = True

            results = await asyncio.gather(
                *(
                    _kilo_balance(client, origin, key, name, org_id)
                    for name, org_id in accounts_to_check
                )
            )
            balances = [b for b in results if b is not None]
            depleted = [b.name for b in balances if b.depleted]
            # A dropped row must say so: silently omitting an account would
            # hide the very one that might be running out.
            failed = [
                name
                for (name, _), b in zip(accounts_to_check, results, strict=True)
                if b is None
            ]

            problems: list[str] = []
            if depleted:
                problems.append(f"Balance depleted: {', '.join(depleted)}")
            if failed:
                problems.append(f"Balance unavailable: {', '.join(failed)}")
            if profile_failed:
                problems.append("Organization balances unavailable")
            warning = (
                "; ".join(problems) if balances else "Balance unavailable"
            ) or None

            return AccountProviderUsage(
                provider="kilo",
                configured=True,
                currency="USD",
                balances=balances or None,
                model_count=model_count or None,
                warning=warning,
                error=None,
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


_ACTIVITY_URL = "https://openrouter.ai/api/v1/analytics/query"
_ACTIVITY_CACHE_TTL = 900  # 15 min
_ACTIVITY_TODAY_CACHE_TTL = 300  # 5 min -- "today" is the number people watch move
_ACTIVITY_TZ = "America/Denver"
_ACTIVITY_DAYS: dict[str, int] = {"today": 1, "7d": 7, "30d": 30}
_ACTIVITY_LIMIT = 1000
# byok_fees is deliberately absent: requesting it switches OpenRouter to a
# different, lower-valued result set (see .audit/evidence-live.md s4), and
# credits_usage already includes BYOK fees, so it is not needed for totals.
_ACTIVITY_METRICS = [
    "request_count",
    "total_usage",
    "credits_usage",
    "byok_usage",
    "tokens_prompt",
    "tokens_completion",
    "reasoning_tokens",
]
_ACTIVITY_DIMENSIONS: dict[str, list[str]] = {
    "model": ["model"],
    "api_key": ["model", "api_key_id"],
    "app": ["model", "app"],
}
_ACTIVITY_CALLER_FIELD = {"model": None, "api_key": "api_key_id", "app": "app"}
_RECONCILE_TOLERANCE = 1e-6
_USD_DECIMALS = 6
_BILLING_FIELDS = ("total_usage", "credits_usage", "byok_usage")


class _ActivityError(Exception):
    """A provider failure whose message is safe to show (no secrets)."""


def _to_int(v: object) -> int:
    """Analytics query returns counts/tokens as strings; coerce safely."""
    try:
        # `object` is too wide for int()/float(); we want runtime coercion.
        return int(float(v)) if v is not None else 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _provider_time(moment: datetime) -> str:
    """OpenRouter accepts only ``YYYY-MM-DDTHH:MM:SSZ`` (offsets and bare dates 400)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def activity_window(period: ActivityPeriodKey, now: datetime) -> ActivityPeriod:
    """The queried window: local midnight (America/Denver) of the first day up to ``now``.

    The start is converted to UTC per date, so a DST change inside a multi-day
    window moves the offset of the start only, never the end. The end is ``now``
    truncated to whole seconds, hence the window is always partial.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    zone = ZoneInfo(_ACTIVITY_TZ)
    end = now.astimezone(UTC).replace(microsecond=0)
    end_date = end.astimezone(zone).date()
    start_date = end_date - timedelta(days=_ACTIVITY_DAYS[period] - 1)
    start = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(UTC)
    if end <= start:  # now is exactly local midnight: never send a zero-length range
        end = start + timedelta(seconds=1)
    return ActivityPeriod(
        key=period,
        timezone=_ACTIVITY_TZ,
        start=start,
        end=end,
        start_date=start_date,
        end_date=end_date,
        partial=True,
    )


def _opt_float(v: object) -> float | None:
    """Finite float, or None for missing / non-numeric / non-finite (never 0.0)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _opt_count(v: object) -> int | None:
    """Non-negative whole number (analytics sends counts as strings), else None."""
    n = _opt_float(v)
    if n is None or n < 0 or not n.is_integer():
        return None
    return int(n)


def _parse_activity_row(
    row: object, group_by: ActivityGroupBy
) -> tuple[ModelActivityItem | None, bool, bool]:
    """Parse one provider row -> (item, billing_missing, unreconciled).

    ``item`` is None when the row is unusable (not an object, or no model id).
    """
    if not isinstance(row, dict):
        return None, False, False
    model_id = row.get("model")
    if not isinstance(model_id, str) or not model_id:
        return None, False, False

    caller: str | None = None
    caller_field = _ACTIVITY_CALLER_FIELD[group_by]
    if caller_field is not None:
        raw_caller = row.get(caller_field)
        caller = None if raw_caller is None else str(raw_caller)

    costs = {f: _opt_float(row.get(f)) for f in _BILLING_FIELDS}
    credits, byok, total = (
        costs["credits_usage"],
        costs["byok_usage"],
        costs["total_usage"],
    )
    unreconciled = (
        credits is not None
        and byok is not None
        and total is not None
        and abs(credits + byok - total) > _RECONCILE_TOLERANCE
    )
    item = ModelActivityItem(
        model_id=model_id,
        caller=caller,
        requests=_opt_count(row.get("request_count")),
        prompt_tokens=_opt_count(row.get("tokens_prompt")),
        completion_tokens=_opt_count(row.get("tokens_completion")),
        reasoning_tokens=_opt_count(row.get("reasoning_tokens")),
        credits_usd=None if credits is None else round(credits, _USD_DECIMALS),
        byok_usd=None if byok is None else round(byok, _USD_DECIMALS),
        total_usd=None if total is None else round(total, _USD_DECIMALS),
    )
    return item, any(v is None for v in costs.values()), unreconciled


def _sum_present(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present), _USD_DECIMALS) if present else None


def _activity_response(
    window: ActivityPeriod,
    group_by: ActivityGroupBy,
    *,
    status: Literal["complete", "incomplete", "unconfigured", "error"],
    items: list[ModelActivityItem] | None = None,
    truncated: bool | None = None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> ActivityResponse:
    items = items or []
    return ActivityResponse(
        period=window,
        group_by=group_by,
        status=status,
        items=items,
        totals=ActivityTotals(
            credits_usd=_sum_present([i.credits_usd for i in items]),
            byok_usd=_sum_present([i.byok_usd for i in items]),
            combined_usd=_sum_present([i.total_usd for i in items]),
        ),
        truncated=truncated,
        warnings=warnings or [],
        error=error,
        fetched_at=datetime.now(UTC),
    )


async def _read_activity_cache(key: str, window: ActivityPeriod) -> ActivityResponse | None:
    cached = await cache.get(key)
    if not cached:
        return None
    try:
        result = ActivityResponse.model_validate(cached)
    except ValidationError:
        # Pre-v2 payload (or garbage): refetch rather than serve a wrong shape.
        log.warning("openrouter_activity_cache_ignored", key=key, reason="invalid shape")
        return None
    if result.period.start_date != window.start_date:
        return None  # the local day rolled over since this was cached
    return result


async def _fetch_activity_rows(key: str, body: dict[str, Any]) -> tuple[list[Any], bool | None]:
    """POST the analytics query -> (rows, truncated). Raises ``_ActivityError``."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                _ACTIVITY_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
        if resp.status_code == 403:
            raise _ActivityError("OpenRouter analytics needs a management key (HTTP 403)")
        if resp.status_code >= 400:
            raise _ActivityError(f"OpenRouter analytics request failed (HTTP {resp.status_code})")
        payload = resp.json()
    except httpx.HTTPError as exc:
        raise _ActivityError(
            f"OpenRouter analytics request failed ({type(exc).__name__})"
        ) from exc
    except ValueError as exc:  # json.JSONDecodeError and friends
        raise _ActivityError("OpenRouter analytics returned invalid JSON") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise _ActivityError("OpenRouter analytics returned an unexpected response shape")
    metadata = data.get("metadata") if isinstance(data, dict) else None
    truncated = metadata.get("truncated") if isinstance(metadata, dict) else None
    return rows, truncated if isinstance(truncated, bool) else None


async def get_activity(
    period: ActivityPeriodKey = "today",
    group_by: ActivityGroupBy = "model",
    *,
    now: datetime | None = None,
) -> ActivityResponse:
    """OpenRouter usage for a local-time window, split into credits / BYOK / combined.

    Uses ``/analytics/query`` (not ``/activity``, which excludes the current
    UTC day). It needs a management key, so only OPENROUTER_ADMIN_KEY is used:
    a regular key gets HTTP 403 there. The window is always sent as an explicit
    ``time_range`` -- top-level start/end fields are silently ignored upstream.
    """
    window = activity_window(period, now or datetime.now(UTC))
    key = _settings.openrouter_admin_key
    if not key:
        return _activity_response(window, group_by, status="unconfigured")

    cache_version = "v3" if group_by == "app" else "v2"
    cache_key = f"accounts:activity:{cache_version}:{period}:{group_by}"
    hit = await _read_activity_cache(cache_key, window)
    if hit is not None:
        return hit

    body = {
        "metrics": _ACTIVITY_METRICS,
        "dimensions": _ACTIVITY_DIMENSIONS[group_by],
        "time_range": {
            "start": _provider_time(window.start),
            "end": _provider_time(window.end),
        },
        "order_by": {"field": "total_usage", "direction": "desc"},
        "limit": _ACTIVITY_LIMIT,
    }
    try:
        if group_by == "app":
            # OpenRouter allows only two dimensions. Split on its unset app
            # sentinel (-1), so named apps and key fallbacks never overlap.
            rows, app_truncated = await _fetch_activity_rows(
                key,
                {**body, "filters": [{"field": "app", "operator": "neq", "value": -1}]},
            )
            key_rows, key_truncated = await _fetch_activity_rows(
                key,
                {
                    **body,
                    "dimensions": ["model", "api_key_id"],
                    "filters": [{"field": "app", "operator": "eq", "value": -1}],
                },
            )
            for row in key_rows:
                if isinstance(row, dict):
                    name = row.get("api_key_id")
                    name = name.strip() if isinstance(name, str) else ""
                    label = (
                        f"{name} (API key)"
                        if name and name.casefold() != "unknown"
                        else "Unattributed"
                    )
                    rows.append({**row, "app": label})
                else:
                    rows.append(row)  # preserve malformed-row reporting below
            truncated = (
                True
                if app_truncated is True or key_truncated is True
                else None if app_truncated is None or key_truncated is None else False
            )
        else:
            rows, truncated = await _fetch_activity_rows(key, body)
    except _ActivityError as exc:
        log.warning("openrouter_activity_failed", error=str(exc))
        failed = _activity_response(window, group_by, status="error", error=str(exc))
        await cache.set(cache_key, failed.model_dump(mode="json"), ttl=_FAILURE_CACHE_TTL)
        return failed

    items: list[ModelActivityItem] = []
    skipped = missing_billing = unreconciled = 0
    for row in rows:
        item, billing_missing, off_by_more_than_tolerance = _parse_activity_row(row, group_by)
        if item is None:
            skipped += 1
            continue
        items.append(item)
        missing_billing += billing_missing
        unreconciled += off_by_more_than_tolerance
    items.sort(key=lambda i: (i.total_usd is None, -(i.total_usd or 0.0)))

    warnings: list[str] = []
    if skipped:
        warnings.append(f"{skipped} malformed row(s) from OpenRouter were skipped")
    if missing_billing:
        warnings.append(f"{missing_billing} row(s) have a missing or non-numeric billing value")
    if unreconciled:
        warnings.append(f"{unreconciled} row(s) where credits + BYOK does not equal the total")
    if truncated is True:
        warnings.append(
            f"OpenRouter truncated the results at {_ACTIVITY_LIMIT} rows; totals are partial"
        )
    elif truncated is None:
        warnings.append("OpenRouter did not report whether results were truncated")

    result = _activity_response(
        window,
        group_by,
        status="incomplete" if warnings else "complete",
        items=items,
        truncated=truncated,
        warnings=warnings,
    )
    ttl = _ACTIVITY_TODAY_CACHE_TTL if period == "today" else _ACTIVITY_CACHE_TTL
    await cache.set(cache_key, result.model_dump(mode="json"), ttl=ttl)
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
    any_error = any(p.error for p in (openrouter, kilo))
    await cache.set(
        _CACHE_KEY,
        result.model_dump(mode="json"),
        ttl=_FAILURE_CACHE_TTL if any_error else _CACHE_TTL,
    )
    return result
