"""Kilo gateway catalog: an unknown price is dropped, never published as 0.0 (free).

Mirrors test_openrouter_price_guards. model-speed probes whatever /kilo/models
returns, so a record with no pricing block used to be probed as a free model.
ModelPricing requires numeric prices (no null), so dropping is the option that
does not break the ranker, the comparison routes or the web client.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest
import respx

from app.services import kilo_gateway


def _raw(model_id: str, prompt: Any = "0.000001", completion: Any = "0.000002", **pricing: Any):
    p: dict[str, Any] = {}
    if prompt is not None:
        p["prompt"] = prompt
    if completion is not None:
        p["completion"] = completion
    p.update(pricing)
    return {"id": model_id, "pricing": p}


def _ids(raw: list[dict[str, Any]]) -> set[str]:
    return {m.id for r in raw if (m := kilo_gateway._normalize(r)) is not None}


_BAD = [None, "", "nan", "NaN", "inf", "-inf", "1e999", "-0.000001", "abc"]


@pytest.mark.parametrize("bad", _BAD)
def test_bad_prompt_price_drops_the_record(bad: Any) -> None:
    assert _ids([_raw("x/bad", prompt=bad), _raw("x/good")]) == {"x/good"}


@pytest.mark.parametrize("bad", _BAD)
def test_bad_completion_price_drops_the_record(bad: Any) -> None:
    assert _ids([_raw("x/bad", completion=bad), _raw("x/good")]) == {"x/good"}


def test_record_without_a_pricing_block_is_dropped_not_published_as_free() -> None:
    assert _ids([{"id": "x/nopricing"}, {"id": "x/empty", "pricing": {}}]) == set()
    assert _ids([{"id": "x/null", "pricing": None}]) == set()


def test_explicit_zero_price_is_a_real_free_model() -> None:
    m = kilo_gateway._normalize(_raw("x/free", prompt="0", completion="0"))
    assert m is not None
    assert (m.prompt_usd_per_mtok, m.completion_usd_per_mtok) == (0.0, 0.0)


@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "n/a"])
def test_bad_optional_surcharge_never_stores_nan(bad: str) -> None:
    m = kilo_gateway._normalize(_raw("x/y", request=bad, image=bad))
    assert m is not None
    assert m.request_usd == 0.0
    assert m.image_usd == 0.0
    assert math.isfinite(m.request_usd) and math.isfinite(m.image_usd)


@pytest.fixture
def _kilo_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kilo_gateway._settings, "kilo_api_key", "test-key", raising=False)

    async def _get(_key: str) -> None:
        return None

    async def _set(_key: str, _value: Any, ttl: int | None = None) -> None:
        return None

    monkeypatch.setattr(kilo_gateway.cache, "get", _get)
    monkeypatch.setattr(kilo_gateway.cache, "set", _set)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_models_drops_unpriced_records_and_keeps_priced_ones(
    _kilo_network: None,
) -> None:
    payload = {
        "data": [
            {"id": "kilo/no-pricing"},
            _raw("kilo/nan", prompt="nan"),
            _raw("kilo/free", prompt="0", completion="0"),
            _raw("kilo/paid"),
        ]
    }
    respx.get(f"{kilo_gateway._BASE_URL}/models").mock(
        return_value=httpx.Response(200, json=payload)
    )
    models = await kilo_gateway.fetch_models()
    assert sorted(m.id for m in models) == ["kilo/free", "kilo/paid"]
