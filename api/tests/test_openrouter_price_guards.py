"""OpenRouter catalog guards: bad prices are rejected, not stored as 0.0 or NaN.

Also pins the previous-cache protection (empty / sharply shrunk catalog) and the
response size cap.
"""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx

from app.schemas import ModelPricing
from app.services import openrouter


def _raw(model_id: str, prompt: Any = "0.000001", completion: Any = "0.000002", **pricing: Any):
    p: dict[str, Any] = {}
    if prompt is not None:
        p["prompt"] = prompt
    if completion is not None:
        p["completion"] = completion
    p.update(pricing)
    return {"id": model_id, "pricing": p}


def _ids(raw: list[dict[str, Any]]) -> set[str]:
    return {m.id for m in openrouter.normalize_all(raw)}


# --- price validation ------------------------------------------------------


_BAD_PROMPTS = [None, "", "nan", "NaN", "inf", "-inf", "1e999", "-0.000001", "abc"]


@pytest.mark.parametrize("bad", _BAD_PROMPTS)
def test_bad_prompt_price_drops_the_record(bad: Any) -> None:
    assert _ids([_raw("x/bad", prompt=bad), _raw("x/good")]) == {"x/good"}


@pytest.mark.parametrize("bad", [None, "", "nan", "inf", "-1", "abc"])
def test_bad_completion_price_drops_the_record(bad: Any) -> None:
    assert _ids([_raw("x/bad", completion=bad), _raw("x/good")]) == {"x/good"}


def test_record_without_pricing_block_is_dropped_not_stored_as_free() -> None:
    assert _ids([{"id": "x/nopricing"}, {"id": "x/empty", "pricing": {}}]) == set()


def test_explicit_zero_price_is_a_real_free_model() -> None:
    models = openrouter.normalize_all([_raw("x/free", prompt="0", completion="0")])
    assert [(m.id, m.prompt_usd_per_mtok, m.completion_usd_per_mtok) for m in models] == [
        ("x/free", 0.0, 0.0)
    ]


@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "n/a"])
def test_bad_optional_surcharge_never_stores_nan(bad: str) -> None:
    [m] = openrouter.normalize_all([_raw("x/y", request=bad, image=bad)])
    assert m.request_usd == 0.0
    assert m.image_usd == 0.0
    assert math.isfinite(m.request_usd) and math.isfinite(m.image_usd)


# --- previous cache is kept ------------------------------------------------


class _FakeCache:
    def __init__(self, previous: list[dict[str, Any]] | None) -> None:
        self.previous = previous
        self.sets: list[Any] = []

    async def get(self, _key: str) -> Any:
        return self.previous

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.sets.append((key, value))


def _previous(n: int) -> list[dict[str, Any]]:
    return [
        ModelPricing(
            id=f"p/m{i}",
            name=f"m{i}",
            prompt_usd_per_mtok=1.0,
            completion_usd_per_mtok=2.0,
            captured_at="2026-11-10T00:00:00Z",
        ).model_dump(mode="json")
        for i in range(n)
    ]


@pytest.fixture
def persisted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _persist(raw: Any, normalized: Any) -> None:
        calls.append("persist")

    async def _prune() -> int:
        calls.append("prune")
        return 0

    monkeypatch.setattr(openrouter, "_persist", _persist)
    monkeypatch.setattr(openrouter, "prune_snapshots", _prune)
    return calls


def _serve(monkeypatch: pytest.MonkeyPatch, raw: list[dict[str, Any]], cache: _FakeCache) -> None:
    async def _fetch() -> list[dict[str, Any]]:
        return raw

    monkeypatch.setattr(openrouter, "fetch_raw", _fetch)
    monkeypatch.setattr(openrouter, "cache", cache)


async def test_empty_catalog_keeps_previous_cache(
    monkeypatch: pytest.MonkeyPatch, persisted: list[str]
) -> None:
    cache = _FakeCache(_previous(10))
    _serve(monkeypatch, [], cache)
    with pytest.raises(openrouter.CatalogRejectedError):
        await openrouter.refresh_pricing(persist=True)
    assert cache.sets == []
    assert persisted == []


async def test_catalog_of_only_bad_prices_is_rejected_like_an_empty_one(
    monkeypatch: pytest.MonkeyPatch, persisted: list[str]
) -> None:
    cache = _FakeCache(None)
    _serve(monkeypatch, [_raw("a/x", prompt="nan"), _raw("a/y", completion=None)], cache)
    with pytest.raises(openrouter.CatalogRejectedError):
        await openrouter.refresh_pricing(persist=True)
    assert cache.sets == []
    assert persisted == []


async def test_sharply_shrunk_catalog_keeps_previous_cache(
    monkeypatch: pytest.MonkeyPatch, persisted: list[str]
) -> None:
    cache = _FakeCache(_previous(10))
    _serve(monkeypatch, [_raw(f"n/m{i}") for i in range(4)], cache)  # 4 < 50% of 10
    with pytest.raises(openrouter.CatalogRejectedError, match="shrank from 10 to 4"):
        await openrouter.refresh_pricing(persist=True)
    assert cache.sets == []
    assert persisted == []


async def test_shrink_at_the_threshold_is_accepted(
    monkeypatch: pytest.MonkeyPatch, persisted: list[str]
) -> None:
    cache = _FakeCache(_previous(10))
    _serve(monkeypatch, [_raw(f"n/m{i}") for i in range(5)], cache)  # exactly 50%
    models = await openrouter.refresh_pricing(persist=True)
    assert len(models) == 5
    assert len(cache.sets) == 1
    assert persisted == ["persist", "prune"]


async def test_first_fill_has_no_baseline_and_is_accepted(
    monkeypatch: pytest.MonkeyPatch, persisted: list[str]
) -> None:
    cache = _FakeCache(None)
    _serve(monkeypatch, [_raw("n/only")], cache)
    assert len(await openrouter.refresh_pricing(persist=False)) == 1
    assert len(cache.sets) == 1


# --- response size cap -----------------------------------------------------

_S = openrouter._settings
MODELS_URL = f"{_S.openrouter_base_url}{_S.openrouter_models_path}"


class _Chunked(httpx.AsyncByteStream):
    """A body with no Content-Length, delivered in chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for c in self._chunks:
            yield c


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(openrouter._settings, "openrouter_max_response_bytes", 1000)
    return 1000


async def test_oversized_declared_response_is_rejected_without_retry(small_cap: int) -> None:
    body = json.dumps({"data": [_raw("a/b")], "pad": "x" * 5000}).encode()
    with respx.mock() as mock:
        route = mock.get(MODELS_URL).mock(return_value=httpx.Response(200, content=body))
        with pytest.raises(openrouter.ResponseTooLargeError):
            await openrouter.fetch_raw()
    assert route.call_count == 1


async def test_oversized_streamed_response_without_content_length_is_rejected(
    small_cap: int,
) -> None:
    chunks = [b'{"data": [', b"x" * 600, b"y" * 600, b"]}"]
    with respx.mock() as mock:
        mock.get(MODELS_URL).mock(
            return_value=httpx.Response(200, stream=_Chunked(chunks))
        )
        with pytest.raises(openrouter.ResponseTooLargeError):
            await openrouter.fetch_raw()


async def test_response_under_the_cap_is_parsed() -> None:
    payload = {"data": [_raw("a/b"), _raw("c/d")]}
    with respx.mock() as mock:
        mock.get(MODELS_URL).mock(return_value=httpx.Response(200, json=payload))
        raw = await openrouter.fetch_raw()
    assert [r["id"] for r in raw] == ["a/b", "c/d"]
