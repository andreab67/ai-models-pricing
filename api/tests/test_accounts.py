"""Per-provider account checker coverage.

Each provider gets a focused test for the two paths we care about:

  * key absent → ``configured=False``, ``error is None``
  * key present + valid → numbers reflected from the live response

Errors are surfaced verbatim (truncated) so the dashboard can show what
failed; we don't test the exact truncation length because that's a UX
implementation detail that drifts.
"""

from __future__ import annotations

import pytest
import respx

from app.services import accounts

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _patch_settings(monkeypatch, **overrides):
    """Override the cached Settings instance with test-only values."""
    from app.config import get_settings

    settings = get_settings()
    for k, v in overrides.items():
        setattr(settings, k, v)
    monkeypatch.setattr(accounts, "_settings", settings)
    return settings


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, openrouter_api_key="")
    out = await accounts._check_openrouter()
    assert out.provider == "openrouter"
    assert out.configured is False
    assert out.error is None
    assert out.dashboard_url == "https://openrouter.ai/settings/credits"


@pytest.mark.asyncio
async def test_openrouter_credits_parsed(monkeypatch):
    _patch_settings(monkeypatch, openrouter_api_key="sk-live-test")
    with respx.mock(base_url="https://openrouter.ai") as mock:
        mock.get("/api/v1/credits").respond(
            200,
            json={"data": {"total_credits": 100.0, "total_usage": 12.5}},
        )
        out = await accounts._check_openrouter()
    assert out.configured is True
    assert out.spent_usd == 12.5
    assert out.limit_usd == 100.0
    assert out.remaining_usd == 87.5
    assert out.currency == "USD"


@pytest.mark.asyncio
async def test_openrouter_invalid_key_reports_error(monkeypatch):
    _patch_settings(monkeypatch, openrouter_api_key="sk-bad")
    with respx.mock(base_url="https://openrouter.ai") as mock:
        mock.get("/api/v1/credits").respond(401, json={"error": "nope"})
        out = await accounts._check_openrouter()
    assert out.configured is True
    assert out.error == "API key invalid"


# ---------------------------------------------------------------------------
# Kilo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kilo_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, kilo_api_key="")
    out = await accounts._check_kilo()
    assert out.configured is False


@pytest.mark.asyncio
async def test_kilo_models_and_user_parsed(monkeypatch):
    """Live shape: gateway /models + cloud /api/user (microdollar counts).

    Remaining credit is ``total_microdollars_acquired - microdollars_used``
    = 349.05 - 325.27 = $23.78, which is exactly what the Kilo console shows
    as "Remaining Personal Credits".

    ``kilo_pass_threshold`` is deliberately NOT used: it is the Kilo Pass
    spend threshold, not a budget, so using it as a limit produced a
    fabricated $16.35 remaining.
    """
    _patch_settings(monkeypatch, kilo_api_key="sk-kilo")
    with respx.mock(assert_all_called=False) as mock:
        # kilo_base_url is https://api.kilo.ai/api/gateway in the default config
        mock.get("https://api.kilo.ai/api/gateway/models").respond(
            200, json={"data": [{"id": "m1"}, {"id": "m2"}]}
        )
        mock.get("https://app.kilo.ai/api/user").respond(
            200,
            json={
                "microdollars_used": 325265679,
                "kilo_pass_threshold": 341619360,
                "total_microdollars_acquired": 349050000,
            },
        )
        out = await accounts._check_kilo()
    assert out.configured is True
    assert out.model_count == 2
    assert out.spent_usd == pytest.approx(325.2657, abs=1e-3)
    # The limit is the LIFETIME credits acquired, not the pass threshold.
    assert out.limit_usd == pytest.approx(349.05, abs=1e-3)
    # 349.05 - 325.27 = 23.78, matching the console's Remaining Personal Credits.
    # NOTE: this also pins that the pass threshold (341.62) is NOT the limit --
    # a revert to that field would fail this ~$7.27 away.
    assert out.remaining_usd == pytest.approx(23.7843, abs=1e-3)
    assert out.plan == "Lifetime credit"
    assert out.error is None


@pytest.mark.asyncio
async def test_kilo_pass_threshold_is_not_a_limit(monkeypatch):
    """A user object that carries only the pass threshold must not produce a
    limit/remaining pair -- there is no real denominator to compute against,
    so the card reports spend alone rather than a fabricated balance.
    """
    _patch_settings(monkeypatch, kilo_api_key="sk-kilo")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.kilo.ai/api/gateway/models").respond(
            200, json={"data": [{"id": "m"}]}
        )
        mock.get("https://app.kilo.ai/api/user").respond(
            200,
            json={
                "microdollars_used": 325265679,
                "kilo_pass_threshold": 341619360,
            },
        )
        out = await accounts._check_kilo()
    assert out.spent_usd == pytest.approx(325.2657, abs=1e-3)
    assert out.limit_usd is None
    assert out.remaining_usd is None


@pytest.mark.asyncio
async def test_kilo_user_endpoint_unreachable_omits_balance(monkeypatch):
    """If the cloud user endpoint is unreachable (network error or 4xx)
    we still show model count, and we do NOT invent a balance.
    """
    _patch_settings(monkeypatch, kilo_api_key="sk-kilo")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.kilo.ai/api/gateway/models").respond(
            200, json={"data": [{"id": "m"}]}
        )
        mock.get("https://app.kilo.ai/api/user").respond(503)
        out = await accounts._check_kilo()
    assert out.configured is True
    assert out.model_count == 1
    # No spent/limit surfaced when the cloud endpoint fails.
    assert out.spent_usd is None
    assert out.limit_usd is None
    assert out.remaining_usd is None


@pytest.mark.asyncio
async def test_kilo_invalid_key(monkeypatch):
    _patch_settings(monkeypatch, kilo_api_key="sk-bad")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.kilo.ai/api/gateway/models").respond(401)
        out = await accounts._check_kilo()
    assert out.configured is True
    assert out.error == "API key invalid"


# ---------------------------------------------------------------------------
# MiniMax
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minimax_quota_parsed(monkeypatch):
    """Live shape (api.minimax.io, 2026-09): each model_remains entry has
    BOTH a 5h interval and a weekly counter for the same model. We expand
    each entry into 1-2 QuotaWindow records so the dashboard can render
    each quota on its own row. The plan is a single Token Plan subscription;
    the model_remains array is NOT a list of plans.
    """
    _patch_settings(monkeypatch, minimax_api_key="sk-minimax")
    with respx.mock(assert_all_called=False) as mock:
        # .chat returns the cookie-required error envelope so the checker
        # falls through to .io, which returns real data.
        mock.get("https://api.minimax.chat/v1/api/openplatform/coding_plan/remains").respond(
            200,
            json={
                "base_resp": {"status_code": 1004, "status_msg": "cookie missing"},
                "model_remains": [],
            },
        )
        mock.get("https://api.minimax.io/v1/api/openplatform/coding_plan/remains").respond(
            200,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "model_remains": [
                    {
                        # Unlimited quota: limit and usage are both 0, but
                        # the remaining percent is real -- MUST surface on
                        # the dashboard so the operator sees the healthy
                        # general window alongside the partly-used video.
                        "model_name": "general",
                        "current_interval_usage_count": 0,
                        "current_interval_total_count": 0,
                        "current_interval_remaining_percent": 94,
                        "current_weekly_usage_count": 0,
                        "current_weekly_total_count": 0,
                        "current_weekly_remaining_percent": 99,
                    },
                    {
                        "model_name": "video",
                        "current_interval_usage_count": 2,
                        "current_interval_total_count": 3,
                        "current_interval_remaining_percent": 33,
                        "current_weekly_usage_count": 20,
                        "current_weekly_total_count": 21,
                        "current_weekly_remaining_percent": 5,
                    },
                ],
            },
        )
        out = await accounts._check_minimax()
    assert out.configured is True
    assert out.plan == "Token Plan"
    assert out.currency == "REQS"
    assert out.quota_windows is not None
    # 4 windows: general-5h, general-weekly, video-5h, video-weekly
    assert len(out.quota_windows) == 4
    by_key = {(w.name, w.period): w for w in out.quota_windows}
    # general is the "unlimited" case -- limit and usage are both 0 but the
    # remaining percent is still meaningful and MUST surface so the
    # operator sees the healthy quota alongside the partly-used video.
    assert by_key[("general", "5h")].remaining_percent == 94.0
    assert by_key[("general", "5h")].usage == 0
    assert by_key[("general", "5h")].limit == 0
    assert by_key[("general", "weekly")].remaining_percent == 99.0
    assert by_key[("general", "weekly")].limit == 0
    assert by_key[("video", "5h")].remaining_percent == 33.0
    assert by_key[("video", "weekly")].remaining_percent == 5.0
    # Worst across all windows is video-weekly at 5% (the lowest).
    assert out.remaining_percent == 5.0
    # No fabricated USD numbers.
    assert out.limit_usd is None
    assert out.spent_usd is None
    # Legacy aggregates intentionally cleared -- the per-window view is the
    # canonical display path now.
    assert out.usage_count is None
    assert out.usage_limit is None
    assert out.plan_models is None


@pytest.mark.asyncio
async def test_minimax_cookie_envelope_falls_through_to_io(monkeypatch):
    """If the .chat host returns the cookie-required error envelope but .io
    is reachable, we use the .io payload -- the cookie envelope is NOT a
    hard failure.
    """
    _patch_settings(monkeypatch, minimax_api_key="sk-minimax")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.minimax.chat/v1/api/openplatform/coding_plan/remains").respond(
            200,
            json={"base_resp": {"status_code": 1004, "status_msg": "cookie missing"}},
        )
        mock.get("https://api.minimax.io/v1/api/openplatform/coding_plan/remains").respond(
            200,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "model_remains": [
                    {
                        "model_name": "general",
                        "current_interval_usage_count": 1,
                        "current_interval_total_count": 100,
                        "current_interval_remaining_percent": 99,
                    },
                ],
            },
        )
        out = await accounts._check_minimax()
    assert out.configured is True
    # 5h window only (no weekly fields on this entry).
    assert out.quota_windows is not None
    assert len(out.quota_windows) == 1
    assert out.quota_windows[0].name == "general"
    assert out.quota_windows[0].period == "5h"
    assert out.quota_windows[0].remaining_percent == 99.0


@pytest.mark.asyncio
async def test_minimax_invalid_key(monkeypatch):
    _patch_settings(monkeypatch, minimax_api_key="sk-bad")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.minimax.chat/v1/api/openplatform/coding_plan/remains").respond(401)
        mock.get("https://api.minimax.io/v1/api/openplatform/coding_plan/remains").respond(401)
        out = await accounts._check_minimax()
    assert out.error == "API key invalid"


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, deepseek_api_key="")
    out = await accounts._check_deepseek()
    assert out.configured is False


@pytest.mark.asyncio
async def test_deepseek_balance_parsed(monkeypatch):
    """DeepSeek's /user/balance returns granted + topped_up separately so the
    dashboard can show the paid / free breakdown.

    Per the API reference, ``total_balance`` already INCLUDES granted and
    topped-up, so no spend figure can be derived from this endpoint and the
    card reports none.
    """
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200,
            json={
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "15.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "5.00",
                    }
                ],
            },
        )
        out = await accounts._check_deepseek()
    assert out.configured is True
    assert out.remaining_usd == pytest.approx(15.00)
    # A snapshot balance is not a ledger: we refuse to invent a spend number.
    assert out.spent_usd is None
    assert out.currency == "USD"
    # Credit composition breakdown.
    assert out.granted_usd == pytest.approx(10.00)
    assert out.topped_up_usd == pytest.approx(5.00)
    assert out.error is None


@pytest.mark.asyncio
async def test_deepseek_unavailable_balance_surfaces_warning(monkeypatch):
    """`is_available: false` means the balance cannot cover an API call.

    It must land in `warning`, NOT `error`: `error` makes the card render
    only the message and hides the remaining balance and its paid/free
    split -- precisely the figures the operator needs in the alarm state.
    """
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200,
            json={
                "is_available": False,
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "0.10",
                        "granted_balance": "0.10",
                        "topped_up_balance": "0.00",
                    }
                ],
            },
        )
        out = await accounts._check_deepseek()
    assert out.configured is True
    # Data survives the warning -- this is the whole point.
    assert out.remaining_usd == pytest.approx(0.10)
    assert out.granted_usd == pytest.approx(0.10)
    assert out.warning == "balance too low for API calls"
    # A warning must never masquerade as a hard probe failure.
    assert out.error is None


@pytest.mark.asyncio
async def test_deepseek_null_is_available_is_not_a_false_alarm(monkeypatch):
    """`is_available` explicitly null means UNKNOWN, not "balance too low".

    Truthiness on a present-but-null field would fire a false alarm, so the
    check is `is not False` rather than `bool(...)`.
    """
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200,
            json={
                "is_available": None,
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "2.75",
                        "granted_balance": "0.00",
                        "topped_up_balance": "2.75",
                    }
                ],
            },
        )
        out = await accounts._check_deepseek()
    assert out.warning is None
    assert out.remaining_usd == pytest.approx(2.75)


@pytest.mark.asyncio
async def test_deepseek_prefers_usd_over_cny(monkeypatch):
    """DeepSeek returns a CNY and a USD entry; USD must win, otherwise the
    card would quote a CNY figure under a USD label.
    """
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200,
            json={
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00",
                    },
                    {
                        "currency": "USD",
                        "total_balance": "2.75",
                        "granted_balance": "0.00",
                        "topped_up_balance": "2.75",
                    },
                ],
            },
        )
        out = await accounts._check_deepseek()
    assert out.currency == "USD"
    assert out.remaining_usd == pytest.approx(2.75)


@pytest.mark.asyncio
async def test_deepseek_no_balance_infos(monkeypatch):
    """A 200 with an empty balance_infos array is not a crash: the key is
    valid, we just have no number to show.
    """
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200, json={"is_available": True, "balance_infos": []}
        )
        out = await accounts._check_deepseek()
    assert out.configured is True
    assert out.remaining_usd is None
    assert out.spent_usd is None
    assert out.error is None


@pytest.mark.asyncio
async def test_kilo_acquired_without_used(monkeypatch):
    """Credits acquired but nothing spent yet: limit surfaces, remaining
    equals the full acquired amount.
    """
    _patch_settings(monkeypatch, kilo_api_key="sk-kilo")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.kilo.ai/api/gateway/models").respond(
            200, json={"data": [{"id": "m"}]}
        )
        mock.get("https://app.kilo.ai/api/user").respond(
            200,
            json={
                "microdollars_used": 0,
                "total_microdollars_acquired": 20000000,
            },
        )
        out = await accounts._check_kilo()
    assert out.limit_usd == pytest.approx(20.0, abs=1e-3)
    assert out.remaining_usd == pytest.approx(20.0, abs=1e-3)
    # The label must survive the zero-spend path too -- it is what tells the
    # operator these are lifetime figures rather than this month's budget.
    assert out.plan == "Lifetime credit"


# ---------------------------------------------------------------------------
# Aggregate: get_usage() returns every provider's record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_returns_every_provider(monkeypatch):
    _patch_settings(
        monkeypatch,
        openrouter_api_key="sk-or",
        kilo_api_key="sk-kilo",
        minimax_api_key="sk-mx",
        deepseek_api_key="sk-ds",
    )
    # Reset the cache so the test does not return a stale dict from a
    # previous run; the in-memory fallback would otherwise memoize.
    from app.services.cache import cache

    await cache.set(accounts._CACHE_KEY, None, ttl=0)

    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://openrouter.ai/api/v1/credits").respond(
            200, json={"data": {"total_credits": 0, "total_usage": 0}}
        )
        mock.get(url__regex=r"https://api\.kilo\.ai.*/models").respond(
            200, json={"data": [{"id": "m"}]}
        )
        # Kilo Cloud user endpoint -- microdollar counts.
        mock.get("https://app.kilo.ai/api/user").respond(
            200,
            json={
                "microdollars_used": 325265679,
                "kilo_pass_threshold": 341619360,
            },
        )
        mock.get(url__regex=r"https://api\.minimax\.(chat|io).*coding_plan.*").respond(
            200,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "model_remains": [
                    {
                        "model_name": "general",
                        "current_interval_usage_count": 1,
                        "current_interval_total_count": 100,
                        "current_interval_remaining_percent": 99,
                    },
                ],
            },
        )
        mock.get("https://api.deepseek.com/user/balance").respond(
            200, json={"balance_infos": [{"currency": "USD", "total_balance": "1"}]}
        )

        out = await accounts.get_usage()

    # Per-provider assertion -- not just "did the gather return". Each checker
    # has its own try/except so a returned record can be configured=False with
    # a populated error; the only way to know every provider actually answered
    # is to inspect each one. This is the test that catches the regression
    # where every checker swallows a real failure and the dashboard looks fine.
    for name in (
        "openrouter", "kilo", "minimax", "deepseek",
    ):
        rec = getattr(out, name)
        assert rec.configured is True, f"{name}: not configured ({rec.error!r})"
        assert rec.error is None, f"{name}: surfaced error {rec.error!r}"
