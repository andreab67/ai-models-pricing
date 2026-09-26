"""Regression tests for the full-codebase review fixes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.jobs import kilo_diff
from app.main import REQ_COUNT, UNMATCHED_ROUTE, app
from app.services import accounts, kilo, openrouter
from app.services.cache import Cache


def _counter_value(method: str, path: str, status: str) -> float:
    return REQ_COUNT.labels(method, path, status)._value.get()


# --- metrics labels -----------------------------------------------------------


def test_metrics_label_by_route_template(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _missing(_model_id: str) -> None:
        return None

    monkeypatch.setattr(openrouter, "get_model", _missing)
    client = TestClient(app)
    template = "/compare/{model_id:path}"
    before = _counter_value("GET", template, "404")
    assert client.get("/compare/vendor/some-model-123").status_code == 404
    assert client.get("/compare/vendor/other-model-456").status_code == 404
    assert _counter_value("GET", template, "404") == before + 2
    # The raw path must never become a label value.
    assert _counter_value("GET", "/compare/vendor/some-model-123", "404") == 0


def test_metrics_label_unmatched_paths_share_one_series() -> None:
    client = TestClient(app)
    before = _counter_value("GET", UNMATCHED_ROUTE, "404")
    client.get("/wp-login.php")
    client.get("/.env")
    assert _counter_value("GET", UNMATCHED_ROUTE, "404") == before + 2


# --- input validation ---------------------------------------------------------


def test_compare_rejects_unknown_tier_with_422() -> None:
    client = TestClient(app)
    resp = client.get("/compare/x/y", params={"kilo_tier": "enterprise"})
    assert resp.status_code == 422


def test_projection_rejects_unknown_tier_with_422() -> None:
    client = TestClient(app)
    assert client.get("/kilo/projection", params={"tier": "basic"}).status_code == 422


# --- kilo math ----------------------------------------------------------------


def test_plan_cap_is_honoured() -> None:
    growth = {"welcome_pct": 0.5, "step_pct": 0.05, "cap_pct": 0.40}
    assert kilo.monthly_bonus_pct(12, growth) == pytest.approx(0.40)
    assert kilo.monthly_bonus_pct(12, growth, plan_cap_pct=0.25) == pytest.approx(0.25)
    # A plan cap above the global cap cannot raise it.
    assert kilo.monthly_bonus_pct(12, growth, plan_cap_pct=0.90) == pytest.approx(0.40)
    assert kilo.monthly_bonus_pct(1, growth, plan_cap_pct=0.25) == pytest.approx(0.5)


def test_steady_state_streak_is_cap_month() -> None:
    assert kilo.steady_state_streak({"step_pct": 0.05, "cap_pct": 0.40}) == 8


def test_projection_uses_plan_values() -> None:
    proj = kilo.project("pro", 8)
    assert proj.bonus_pct == pytest.approx(0.40)
    assert proj.total_effective_credits_usd == pytest.approx(49 * 1.4)


# --- normalizers ----------------------------------------------------------------


def test_normalize_all_skips_malformed_records() -> None:
    raw: list[dict[str, Any]] = [
        {"id": "a/good", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "b/bad", "pricing": {"prompt": "0.000001", "completion": "0.000002"},
         "context_length": "not-a-number"},
        {"id": "c/weird-request", "pricing": {"prompt": "0", "completion": "0",
                                              "request": "n/a"}},
    ]
    models = openrouter.normalize_all(raw)
    ids = {m.id for m in models}
    assert "a/good" in ids
    assert "b/bad" not in ids
    assert "c/weird-request" in ids


def test_models_cache_outlives_refresh_interval() -> None:
    assert openrouter.models_cache_ttl() > openrouter._settings.openrouter_refresh_seconds


# --- provider cost parsing ------------------------------------------------------


@respx.mock
async def test_openai_costs_grouped_by_line_item_and_paginated() -> None:
    route = respx.get("https://api.openai.com/v1/organization/costs")
    route.side_effect = [
        httpx.Response(200, json={
            "data": [{"results": [
                {"amount": {"value": 1.5, "currency": "usd"}, "line_item": "gpt-4o, input"},
                {"amount": {"value": 0.5, "currency": "usd"}, "line_item": "gpt-4o, output"},
            ]}],
            "has_more": True, "next_page": "p2",
        }),
        httpx.Response(200, json={
            "data": [{"results": [
                {"amount": {"value": 2.0, "currency": "usd"}, "line_item": "o3, input"},
            ]}],
            "has_more": False, "next_page": None,
        }),
    ]
    async with httpx.AsyncClient() as client:
        buckets = await accounts._openai_cost_buckets(
            client, "k", days=30, group_by_line_item=True
        )
    assert buckets is not None
    assert route.calls[0].request.url.params["group_by"] == "line_item"
    assert route.calls[1].request.url.params["page"] == "p2"
    costs: dict[str, float] = {}
    for b in buckets:
        for r in b["results"]:
            model = accounts._openai_model_from_line_item(r)
            costs[model] = costs.get(model, 0.0) + accounts._openai_amount(r)
    assert costs == {"gpt-4o": 2.0, "o3": 2.0}


@respx.mock
async def test_anthropic_cost_report_reads_results_in_cents_across_pages() -> None:
    route = respx.get("https://api.anthropic.com/v1/organizations/cost_report")
    route.side_effect = [
        httpx.Response(200, json={
            "data": [{"results": [{"amount": "12345.0", "currency": "USD"}]}],
            "has_more": True, "next_page": "page_2",
        }),
        httpx.Response(200, json={
            "data": [{"results": [{"amount": "55", "currency": "USD"}]}],
            "has_more": False, "next_page": None,
        }),
    ]
    async with httpx.AsyncClient() as client:
        buckets = await accounts._anthropic_cost_buckets(client, "k", days=30)
    assert route.calls[0].request.url.params["limit"] == "31"
    assert route.calls[1].request.url.params["page"] == "page_2"
    total = sum(accounts._anthropic_amount_usd(r) for b in buckets for r in b["results"])
    assert total == pytest.approx(124.0)


# --- cache ----------------------------------------------------------------------


async def test_cache_falls_back_and_reports_redis_down() -> None:
    c = Cache("redis://127.0.0.1:1/0", default_ttl=60)
    await c.set("k", {"v": 1})
    assert await c.get("k") == {"v": 1}
    assert await c.redis_available() is False
    await c.close()


# --- kilo diff ------------------------------------------------------------------


async def _run_kilo_diff(
    monkeypatch: pytest.MonkeyPatch, last: str | None, new: str, delivered: bool = True
) -> tuple[int, list[str], list[str]]:
    sent: list[str] = []
    recorded: list[str] = []

    async def _fetch() -> tuple[str, str]:
        return new, "text"

    async def _last() -> str | None:
        return last

    async def _record(h: str) -> None:
        recorded.append(h)

    async def _send(subject: str, html: str, text: str) -> bool:
        sent.append(subject)
        return delivered

    class _Engine:
        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(kilo_diff, "fetch_pricing_hash", _fetch)
    monkeypatch.setattr(kilo_diff, "last_known_hash", _last)
    monkeypatch.setattr(kilo_diff, "record_hash", _record)
    monkeypatch.setattr(kilo_diff, "send", _send)
    monkeypatch.setattr(kilo_diff, "engine", _Engine())
    rc = await kilo_diff._main()
    return rc, sent, recorded


async def test_kilo_diff_alerts_on_change(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, sent, recorded = await _run_kilo_diff(monkeypatch, last="old", new="new")
    assert rc == 0
    assert len(sent) == 1
    assert recorded == ["new"]


async def test_kilo_diff_records_baseline_without_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc, sent, recorded = await _run_kilo_diff(monkeypatch, last=None, new="h1")
    assert (rc, sent, recorded) == (0, [], ["h1"])


async def test_kilo_diff_unchanged_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, sent, recorded = await _run_kilo_diff(monkeypatch, last="same", new="same")
    assert (rc, sent, recorded) == (0, [], [])




# --- review round 2 -------------------------------------------------------------


async def test_concurrent_reconnect_opens_one_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import app.services.cache as cache_mod

    created: list[object] = []

    class _FakeRedis:
        def __init__(self) -> None:
            created.append(self)
            self.store: dict[str, str] = {}

        async def ping(self) -> bool:
            await asyncio.sleep(0.01)
            return True

        async def get(self, key: str) -> str | None:
            return self.store.get(key)

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(cache_mod.redis, "from_url", lambda *a, **k: _FakeRedis())
    c = Cache("redis://fake:6379/0", default_ttl=60)
    await asyncio.gather(*(c.get("k") for _ in range(20)))
    assert len(created) == 1


async def test_single_flight_shares_one_failing_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    calls = 0

    async def _miss(_key: str) -> None:
        return None

    async def _failing_refresh(persist: bool = True) -> list[Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        raise httpx.ConnectError("upstream down")

    monkeypatch.setattr(openrouter.cache, "get", _miss)
    monkeypatch.setattr(openrouter, "refresh_pricing", _failing_refresh)
    monkeypatch.setattr(openrouter, "_inflight_refresh", None)
    results = await asyncio.gather(
        *(openrouter.list_models() for _ in range(10)), return_exceptions=True
    )
    assert calls == 1
    assert all(isinstance(r, httpx.ConnectError) for r in results)


def test_kilo_tier_is_case_insensitive() -> None:
    from app.config import Settings

    assert Settings(kilo_tier="Pro").kilo_tier == "pro"
    with pytest.raises(ValueError):
        Settings(kilo_tier="enterprise")


def test_version_matches_pyproject() -> None:
    import tomllib
    from pathlib import Path

    import app as app_pkg

    pyproject = Path(app_pkg.__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        assert app_pkg.__version__ == tomllib.load(f)["project"]["version"]


# --- review round 3 (Kilo Code Review on PR #3) ---------------------------------


async def test_kilo_diff_keeps_baseline_when_alert_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc, sent, recorded = await _run_kilo_diff(monkeypatch, last="old", new="new", delivered=False)
    assert rc == 1
    assert len(sent) == 1
    assert recorded == []


async def test_invalid_redis_url_falls_back_to_memory() -> None:
    c = Cache("http://not-a-redis-url", default_ttl=60)
    await c.set("k", {"v": 1})
    assert await c.get("k") == {"v": 1}
    assert await c.redis_available() is False


async def test_corrupt_redis_value_does_not_mark_redis_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.cache as cache_mod

    class _Redis:
        async def ping(self) -> bool:
            return True

        async def get(self, key: str) -> str:
            return "{not json"

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(cache_mod.redis, "from_url", lambda *a, **k: _Redis())
    c = Cache("redis://fake:6379/0", default_ttl=60)
    assert await c.get("k") is None
    assert c._client is not None  # still connected


def test_openai_amount_tolerates_scalar_amount() -> None:
    assert accounts._openai_amount({"amount": "1.5"}) == 0.0
    assert accounts._openai_amount({"amount": None}) == 0.0
    assert accounts._openai_amount({"amount": {"value": "2.5"}}) == 2.5


def test_readyz_probes_run_concurrently_under_one_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import time

    from app.routes import health

    async def _slow_db() -> bool:
        await asyncio.sleep(1.2)
        return True

    async def _slow_redis() -> bool:
        await asyncio.sleep(1.2)
        return True

    monkeypatch.setattr(health, "_db_ok", _slow_db)
    monkeypatch.setattr(health.cache, "redis_available", _slow_redis)
    client = TestClient(app)
    start = time.perf_counter()
    resp = client.get("/readyz")
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert resp.json() == {"db": True, "redis": True, "ready": True}
    assert elapsed < 2.0  # sequential would take ~2.4s
