"""Per-provider account checker coverage.

Each provider gets a focused test for the two paths we care about:

  * key absent → ``configured=False``, ``error is None``
  * key present + valid → numbers reflected from the live response

Errors are surfaced verbatim (truncated) so the dashboard can show what
failed; we don't test the exact truncation length because that's a UX
implementation detail that drifts.
"""

from __future__ import annotations

import httpx
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
# OpenRouter — already existed, but pinning the new ``currency``/``dashboard_url``
# fields so a future refactor doesn't silently drop them.
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
# MiniMax
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minimax_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, minimax_api_key="")
    out = await accounts._check_minimax()
    assert out.provider == "minimax"
    assert out.configured is False
    assert out.dashboard_url is not None


@pytest.mark.asyncio
async def test_minimax_quota_parsed(monkeypatch):
    _patch_settings(monkeypatch, minimax_api_key="sk-minimax")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.MiniMax.chat/v1/api/openplatform/coding_plan/remains").respond(
            200,
            json={
                "data": {
                    "limit": 100.0,
                    "used": 30.0,
                    "remains": 70.0,
                    "currency": "USD",
                }
            },
        )
        out = await accounts._check_minimax()
    assert out.configured is True
    assert out.limit_usd == 100.0
    assert out.spent_usd == 30.0
    assert out.remaining_usd == 70.0
    assert out.currency == "USD"


@pytest.mark.asyncio
async def test_minimax_invalid_key(monkeypatch):
    _patch_settings(monkeypatch, minimax_api_key="sk-bad")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.MiniMax.chat/v1/api/openplatform/coding_plan/remains").respond(401)
        out = await accounts._check_minimax()
    assert out.error == "API key invalid"


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, anthropic_api_key="", anthropic_admin_key="")
    out = await accounts._check_anthropic()
    assert out.configured is False


@pytest.mark.asyncio
async def test_anthropic_balance_parsed(monkeypatch):
    _patch_settings(monkeypatch, anthropic_api_key="sk-ant-test", anthropic_admin_key="")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.anthropic.com/v1/organizations").respond(
            200, json={"data": [{"id": "org-abc"}]}
        )
        mock.get(
            "https://api.anthropic.com/v1/organizations/org-abc/billing/balance"
        ).respond(200, json={"available_credit": 50.0, "used_credit": 12.5, "currency": "USD"})
        out = await accounts._check_anthropic()
    assert out.configured is True
    # Anthropic's billing endpoint returns DOLLARS, not cents.
    assert out.remaining_usd == 50.0
    assert out.spent_usd == 12.5
    assert out.currency == "USD"


@pytest.mark.asyncio
async def test_anthropic_admin_required_on_403(monkeypatch):
    _patch_settings(monkeypatch, anthropic_api_key="sk-ant-user", anthropic_admin_key="")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.anthropic.com/v1/organizations").respond(403)
        out = await accounts._check_anthropic()
    assert out.configured is True
    assert out.error == "admin key required for billing"


@pytest.mark.asyncio
async def test_anthropic_no_org_reports_error(monkeypatch):
    _patch_settings(monkeypatch, anthropic_api_key="sk-ant-test", anthropic_admin_key="")
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.anthropic.com/v1/organizations").respond(
            200, json={"data": []}
        )
        out = await accounts._check_anthropic()
    assert out.configured is True
    assert "no organization" in (out.error or "")


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, openai_api_key="", openai_admin_key="")
    out = await accounts._check_openai()
    assert out.configured is False


@pytest.mark.asyncio
async def test_openai_credit_grants_parsed(monkeypatch):
    _patch_settings(monkeypatch, openai_api_key="", openai_admin_key="sk-admin-test")
    with respx.mock(base_url="https://api.openai.com") as mock:
        mock.get("/v1/dashboard/billing/credit_grants").respond(
            200,
            json={
                "total_granted": 50.0,
                "total_used": 7.5,
                "total_available": 42.5,
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
            },
        )
        out = await accounts._check_openai()
    assert out.configured is True
    assert out.limit_usd == 50.0
    assert out.spent_usd == 7.5
    assert out.remaining_usd == 42.5
    assert out.period_start == "2026-09-01"


@pytest.mark.asyncio
async def test_openai_user_key_surfaces_admin_required(monkeypatch):
    _patch_settings(monkeypatch, openai_api_key="sk-test", openai_admin_key="")
    with respx.mock(base_url="https://api.openai.com") as mock:
        mock.get("/v1/dashboard/billing/credit_grants").respond(403)
        out = await accounts._check_openai()
    assert out.configured is True
    assert out.error == "admin key required for billing"


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
    _patch_settings(monkeypatch, deepseek_api_key="sk-deepseek")
    with respx.mock(base_url="https://api.deepseek.com") as mock:
        mock.get("/user/balance").respond(
            200,
            json={
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "12.34",
                        "granted_balance": "10.00",
                        "topped_up_balance": "5.00",
                    }
                ]
            },
        )
        out = await accounts._check_deepseek()
    assert out.configured is True
    assert out.remaining_usd == pytest.approx(12.34)
    assert out.spent_usd == pytest.approx(2.66)  # granted+topped_up - total
    assert out.currency == "USD"


# ---------------------------------------------------------------------------
# Alibaba DashScope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alibaba_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, alibaba_api_key="")
    out = await accounts._check_alibaba()
    assert out.configured is False


@pytest.mark.asyncio
async def test_alibaba_valid_key_returns_active(monkeypatch):
    _patch_settings(monkeypatch, alibaba_api_key="sk-alibaba")
    with respx.mock(base_url="https://dashscope.aliyuncs.com") as mock:
        # MUST be the free metadata endpoint, not the billable text-generation
        # endpoint -- otherwise every dashboard refresh costs real tokens.
        mock.get("/api/v1/models").respond(200, json={"data": []})
        out = await accounts._check_alibaba()
    assert out.configured is True
    assert out.error is None


@pytest.mark.asyncio
async def test_alibaba_invalid_key_reports_error(monkeypatch):
    _patch_settings(monkeypatch, alibaba_api_key="sk-bad")
    with respx.mock(base_url="https://dashscope.aliyuncs.com") as mock:
        mock.get("/api/v1/models").respond(401)
        out = await accounts._check_alibaba()
    assert out.error == "API key invalid"


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_unconfigured(monkeypatch):
    _patch_settings(monkeypatch, cursor_email="", cursor_plan="")
    out = await accounts._check_cursor()
    assert out.configured is False
    assert out.error is not None  # tells the operator to set CURSOR_EMAIL


@pytest.mark.asyncio
async def test_cursor_configured_links_to_settings(monkeypatch):
    _patch_settings(monkeypatch, cursor_email="a@x.com", cursor_plan="Pro")
    out = await accounts._check_cursor()
    assert out.configured is True
    assert out.plan == "Pro"
    assert "cursor.com/settings" in (out.dashboard_url or "")
    # The email MUST NOT leak into the URL -- it would flow through browser
    # history, the Referer header on third-party requests, and Cursor's own
    # server logs. Cursor's settings page also doesn't honor ?email=, so the
    # query string has no UX value.
    assert "email=" not in (out.dashboard_url or "")


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
        anthropic_api_key="sk-anth",
        openai_admin_key="sk-admin",
        deepseek_api_key="sk-ds",
        alibaba_api_key="sk-alb",
        cursor_email="a@x.com",
        cursor_plan="Pro",
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
        mock.get(url__regex=r"https://api\.minimax\.(chat|io).*coding_plan.*").respond(
            200, json={"data": {"limit": 1, "used": 0, "remains": 1}}
        )
        mock.get("https://api.anthropic.com/v1/organizations").respond(
            200, json={"data": [{"id": "org-1"}]}
        )
        mock.get(
            "https://api.anthropic.com/v1/organizations/org-1/billing/balance"
        ).respond(200, json={"available_credit": 100})
        mock.get("https://api.openai.com/v1/dashboard/billing/credit_grants").respond(
            200, json={"total_granted": 1, "total_used": 0, "total_available": 1}
        )
        mock.get("https://api.deepseek.com/user/balance").respond(
            200, json={"balance_infos": [{"currency": "USD", "total_balance": "1"}]}
        )
        # Alibaba: free metadata endpoint, NOT the billable text-generation
        # endpoint (would cost real tokens per refresh).
        mock.get(url__regex=r"https://dashscope\.aliyuncs\.com/api/v1/models").respond(
            200, json={"data": []}
        )

        out = await accounts.get_usage()

    # Per-provider assertion -- not just "did the gather return". Each checker
    # has its own try/except so a returned record can be configured=False with
    # a populated error; the only way to know every provider actually answered
    # is to inspect each one. This is the test that catches the regression
    # where every checker swallows a real failure and the dashboard looks fine.
    for name in (
        "openrouter", "kilo", "minimax", "anthropic",
        "openai", "deepseek", "alibaba", "cursor",
    ):
        rec = getattr(out, name)
        assert rec.configured is True, f"{name}: not configured ({rec.error!r})"
        assert rec.error is None, f"{name}: surfaced error {rec.error!r}"


# Silence unused import warning under ruff when the suite shrinks.
_ = httpx
