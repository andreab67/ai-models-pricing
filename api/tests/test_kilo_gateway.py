"""Kilo gateway failure signalling.

The distinction these tests pin down is the one a 2026-09-18 Kilo outage
exposed: `fetch_models()` used to return [] both when Kilo said "no models"
and when Kilo could not be reached at all. `/kilo/models` is model-speed's
catalog of record, so the second case quietly halved its candidate pool with
nothing logged above INFO.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.compare import kilo_router
from app.services import kilo_gateway

MODELS_URL = f"{kilo_gateway._BASE_URL}/models"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(kilo_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _no_cache_no_key(monkeypatch):
    """Force the network path: a configured key and a cold cache."""
    monkeypatch.setattr(kilo_gateway._settings, "kilo_api_key", "test-key", raising=False)

    async def _get(_key):
        return None

    async def _set(_key, _value, ttl=None):
        return None

    monkeypatch.setattr(kilo_gateway.cache, "get", _get)
    monkeypatch.setattr(kilo_gateway.cache, "set", _set)


def _model_payload(model_id: str = "minimax/minimax-m3") -> dict:
    return {
        "data": [
            {
                "id": model_id,
                "name": model_id,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "context_length": 1_000_000,
            }
        ]
    }


@respx.mock
@pytest.mark.asyncio
async def test_upstream_403_raises_rather_than_returning_empty():
    """A 403 must not masquerade as an empty catalog."""
    respx.get(MODELS_URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    with pytest.raises(kilo_gateway.KiloUnavailable):
        await kilo_gateway.fetch_models()


@respx.mock
@pytest.mark.asyncio
async def test_connection_error_raises():
    respx.get(MODELS_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(kilo_gateway.KiloUnavailable):
        await kilo_gateway.fetch_models()


@respx.mock
@pytest.mark.asyncio
async def test_genuinely_empty_catalog_is_not_an_error():
    """Kilo answering with zero models is a real answer, not a failure."""
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    assert await kilo_gateway.fetch_models() == []


@respx.mock
@pytest.mark.asyncio
async def test_happy_path_returns_models():
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=_model_payload()))
    models = await kilo_gateway.fetch_models()
    assert [m.id for m in models] == ["minimax/minimax-m3"]


@pytest.mark.asyncio
async def test_no_key_returns_empty_without_raising(monkeypatch):
    """No key configured is a deployment choice, not an outage."""
    monkeypatch.setattr(kilo_gateway._settings, "kilo_api_key", "", raising=False)
    assert await kilo_gateway.fetch_models() == []


@respx.mock
def test_route_returns_503_when_kilo_is_down(client: TestClient):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    resp = client.get("/kilo/models")
    assert resp.status_code == 503


@respx.mock
def test_route_returns_200_for_a_genuinely_empty_catalog(client: TestClient):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    resp = client.get("/kilo/models")
    assert resp.status_code == 200
    assert resp.json() == []


@respx.mock
def test_single_model_route_503s_rather_than_404s_when_kilo_is_down(client: TestClient):
    """A 404 would assert Kilo lacks the model; we do not know that."""
    respx.get(MODELS_URL).mock(return_value=httpx.Response(403, text="Forbidden"))
    resp = client.get("/kilo/models/minimax/minimax-m3")
    assert resp.status_code == 503


@respx.mock
def test_single_model_route_still_404s_when_kilo_answers_without_it(client: TestClient):
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=_model_payload()))
    resp = client.get("/kilo/models/some/other-model")
    assert resp.status_code == 404


@respx.mock
@pytest.mark.asyncio
async def test_one_malformed_record_does_not_503_the_whole_catalog():
    """Schema drift on a single entry is a data problem, not an outage."""
    payload = {
        "data": [
            {"id": 12345, "pricing": {}},  # non-str id -> _normalize would blow up
            {
                "id": "minimax/minimax-m3",
                "name": "minimax/minimax-m3",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "context_length": 1_000_000,
            },
        ]
    }
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json=payload))
    models = await kilo_gateway.fetch_models()
    assert [m.id for m in models] == ["minimax/minimax-m3"]
