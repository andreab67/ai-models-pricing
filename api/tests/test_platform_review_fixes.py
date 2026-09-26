"""Regression tests for the API platform fixes ported from the GitHub review."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import REQ_COUNT, UNMATCHED_ROUTE, app
from app.services import openrouter
from app.services.cache import Cache


def _counter_value(method: str, path: str, status: str) -> float:
    return REQ_COUNT.labels(method, path, status)._value.get()


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
    assert _counter_value("GET", "/compare/vendor/some-model-123", "404") == 0


def test_metrics_label_unmatched_paths_share_one_series() -> None:
    client = TestClient(app)
    before = _counter_value("GET", UNMATCHED_ROUTE, "404")
    client.get("/wp-login.php")
    client.get("/.env")
    assert _counter_value("GET", UNMATCHED_ROUTE, "404") == before + 2


def test_normalize_all_skips_malformed_records() -> None:
    raw: list[dict[str, Any]] = [
        {"id": "a/good", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "b/bad", "pricing": {"prompt": "0.000001", "completion": "0.000002"},
         "context_length": "not-a-number"},
        {"id": "c/weird-request", "pricing": {"prompt": "0", "completion": "0",
                                              "request": "n/a"}},
    ]
    ids = {m.id for m in openrouter.normalize_all(raw)}
    assert "a/good" in ids
    assert "b/bad" not in ids
    assert "c/weird-request" in ids


def test_models_cache_outlives_refresh_interval() -> None:
    assert openrouter.models_cache_ttl() > openrouter._settings.openrouter_refresh_seconds


async def test_single_flight_shares_one_failing_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


async def test_concurrent_reconnect_opens_one_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.cache as cache_mod

    created: list[object] = []

    class _FakeRedis:
        def __init__(self) -> None:
            created.append(self)

        async def ping(self) -> bool:
            await asyncio.sleep(0.01)
            return True

        async def get(self, key: str) -> str | None:
            return None

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(cache_mod.redis, "from_url", lambda *a, **k: _FakeRedis())
    c = Cache("redis://fake:6379/0", default_ttl=60)
    await asyncio.gather(*(c.get("k") for _ in range(20)))
    assert len(created) == 1


async def test_failed_connect_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.cache as cache_mod

    attempts = 0

    class _DownRedis:
        async def ping(self) -> bool:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("refused")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(cache_mod.redis, "from_url", lambda *a, **k: _DownRedis())
    c = Cache("redis://fake:6379/0", default_ttl=60)
    for _ in range(5):
        await c.set("k", 1)
    assert attempts == 1
    assert await c.get("k") == 1  # in-memory fallback still serves
