"""OpenRouter activity v2: request body, row parsing, totals, status, errors, cache, route.

One malformed value must never blank the table (Kilo Code Review), but it is now
reported as ``None`` plus an ``incomplete`` status -- never as a fabricated 0.0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import ActivityResponse, ActivityTotals
from app.services import accounts

URL = "https://openrouter.ai/api/v1/analytics/query"
# 2026-10-14 14:00 MDT
NOW = datetime(2026, 10, 14, 20, 0, 0, tzinfo=UTC)


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ttl


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    fake = FakeCache()
    monkeypatch.setattr(accounts.cache, "get", fake.get)
    monkeypatch.setattr(accounts.cache, "set", fake.set)
    return fake


@pytest.fixture(autouse=True)
def admin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accounts._settings, "openrouter_admin_key", "k-secret")


def _payload(rows: list[Any], truncated: bool | None = False) -> dict[str, Any]:
    metadata: dict[str, Any] = {"query_time_ms": 12, "row_count": len(rows)}
    if truncated is not None:
        metadata["truncated"] = truncated
    return {"data": {"data": rows, "metadata": metadata}}


def _row(model: str, credits: Any, byok: Any, total: Any, **extra: Any) -> dict[str, Any]:
    return {
        "model": model,
        "credits_usage": credits,
        "byok_usage": byok,
        "total_usage": total,
        "request_count": "1",
        "tokens_prompt": "10",
        "tokens_completion": "5",
        "reasoning_tokens": None,
        **extra,
    }


# Rows copied from the operator's real api_key_id breakdown (.audit/evidence-live.md).
SNAPSHOT = [
    _row("openai/text-embedding-3-small", 1.2e-05, 1.025552, 1.025564, api_key_id="Hermes"),
    _row("anthropic/claude-opus-5.5-20260921", 0.042, 0.672047, 0.714047, api_key_id=None),
    _row("inclusionai/ling-3.0-flash-20260723", 0.625516, 0, 0.625516, api_key_id="crm"),
    _row(
        "inclusionai/ling-3.0-flash-20260723", 0.003351, 0, 0.003351, api_key_id="lingualab leads"
    ),
    _row("anthropic/claude-4.5-haiku-20251001", 0, 0.002978, 0.002978, api_key_id="models"),
]


# --- request body ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("group_by", "dimensions"),
    [
        ("model", ["model"]),
        ("api_key", ["model", "api_key_id"]),
        ("app", ["model", "app"]),
    ],
)
async def test_request_body(
    respx_mock: respx.MockRouter, fake_cache: FakeCache, group_by: str, dimensions: list[str]
) -> None:
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload([])))

    await accounts.get_activity("7d", group_by, now=NOW)  # type: ignore[arg-type]

    request = route.calls.last.request
    body = json.loads(request.content)
    assert body["time_range"] == {"start": "2026-10-08T06:00:00Z", "end": "2026-10-14T20:00:00Z"}
    assert body["metrics"] == [
        "request_count",
        "total_usage",
        "credits_usage",
        "byok_usage",
        "tokens_prompt",
        "tokens_completion",
        "reasoning_tokens",
    ]
    assert "byok_fees" not in body["metrics"]
    assert body["dimensions"] == dimensions
    assert body["limit"] == 1000
    assert body["order_by"] == {"field": "total_usage", "direction": "desc"}
    # Top-level start/end are silently ignored upstream; only time_range may carry the window.
    assert not {"start", "end", "start_time", "date_range"} & body.keys()
    assert request.headers["authorization"] == "Bearer k-secret"


# --- operator snapshot ------------------------------------------------------------


async def test_operator_snapshot_totals_keep_credits_and_byok_apart(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload(SNAPSHOT)))

    result = await accounts.get_activity("today", "api_key", now=NOW)

    assert result.status == "complete"
    assert result.warnings == []
    assert result.truncated is False
    assert result.totals.credits_usd == pytest.approx(0.670879)
    assert result.totals.byok_usd == pytest.approx(1.700577)
    assert result.totals.combined_usd == pytest.approx(2.371456)
    assert result.totals.combined_usd != result.totals.credits_usd

    by_key = {(i.model_id, i.caller): i for i in result.items}
    embeddings = by_key[("openai/text-embedding-3-small", "Hermes")]
    assert embeddings.credits_usd == pytest.approx(1.2e-05)
    assert embeddings.byok_usd == pytest.approx(1.025552)
    opus = by_key[("anthropic/claude-opus-5.5-20260921", None)]  # null key stays None
    assert opus.caller is None
    assert opus.credits_usd == pytest.approx(0.042)
    assert opus.byok_usd == pytest.approx(0.672047)
    # A BYOK-only row never reports its BYOK usage as credits.
    haiku = by_key[("anthropic/claude-4.5-haiku-20251001", "models")]
    assert haiku.credits_usd == 0
    assert haiku.byok_usd == pytest.approx(0.002978)
    # Sorted by combined usage, highest first.
    totals = [i.total_usd for i in result.items]
    assert totals == sorted(totals, reverse=True)
    assert result.period.key == "today"
    assert result.group_by == "api_key"


async def test_caller_follows_grouping(respx_mock: respx.MockRouter, fake_cache: FakeCache) -> None:
    rows = [
        _row("a/m", 1, 0, 1, api_key_id="k1", app="Chatroom"),
        _row("b/m", 0.5, 0, 0.5, api_key_id=None, app=None),
    ]
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload(rows)))

    by_model = await accounts.get_activity("today", "model", now=NOW)
    assert [i.caller for i in by_model.items] == [None, None]
    fake_cache.store.clear()
    by_key = await accounts.get_activity("today", "api_key", now=NOW)
    assert [i.caller for i in by_key.items] == ["k1", None]
    fake_cache.store.clear()
    by_app = await accounts.get_activity("today", "app", now=NOW)
    assert [i.caller for i in by_app.items] == ["Chatroom", None]


# --- tolerant parsing -------------------------------------------------------------


async def test_malformed_rows_are_skipped_and_values_become_none(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    rows = [
        _row("a/good", 1.0, 0.25, 1.25, request_count="3"),
        "not a dict",
        {"credits_usage": 1, "byok_usage": 0, "total_usage": 1},  # no model
        _row("c/nan", "NaN", 0.5, 0.5),
        _row("d/missing", None, 0.5, 0.5),
        _row("e/text", "not-a-number", 0.5, 0.5),
        _row("f/total-missing", 1.0, 0.5, None),
    ]
    del rows[4]["credits_usage"]
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload(rows)))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "incomplete"
    assert any("2 malformed row(s)" in w for w in result.warnings)
    assert any("4 row(s) have a missing or non-numeric billing value" in w for w in result.warnings)
    by_id = {i.model_id: i for i in result.items}
    assert set(by_id) == {"a/good", "c/nan", "d/missing", "e/text", "f/total-missing"}
    good = by_id["a/good"]
    assert (good.credits_usd, good.byok_usd, good.total_usd) == (1.0, 0.25, 1.25)
    assert good.requests == 3  # numeric string parsed
    assert good.prompt_tokens == 10
    assert good.reasoning_tokens is None
    for bad in ("c/nan", "d/missing", "e/text"):
        assert by_id[bad].credits_usd is None  # never 0.0
        assert by_id[bad].byok_usd == 0.5
        assert by_id[bad].total_usd == 0.5
    assert by_id["f/total-missing"].total_usd is None
    # Totals sum the values that are present.
    assert result.totals.credits_usd == pytest.approx(2.0)
    assert result.totals.byok_usd == pytest.approx(2.25)
    assert result.totals.combined_usd == pytest.approx(2.75)
    # None sorts last.
    assert result.items[-1].model_id == "f/total-missing"


async def test_totals_are_none_when_no_row_has_the_value(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    rows = [{"model": "a/m", "request_count": "2"}]
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload(rows)))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "incomplete"
    assert result.totals == ActivityTotals()
    assert result.items[0].requests == 2
    assert result.items[0].credits_usd is None


async def test_reconciliation_mismatch_marks_incomplete(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    rows = [_row("a/m", 1.0, 1.0, 3.0), _row("b/m", 1.0, 1.0, 2.0000005)]
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload(rows)))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "incomplete"
    # Only a/m exceeds the 1e-6 tolerance.
    assert result.warnings == ["1 row(s) where credits + BYOK does not equal the total"]


# --- truncation -----------------------------------------------------------------


async def test_truncated_true_is_incomplete(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=_payload([_row("a/m", 1, 0, 1)], truncated=True))
    )

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "incomplete"
    assert result.truncated is True
    assert any("truncated" in w for w in result.warnings)


async def test_missing_metadata_is_unknown_and_incomplete(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    payload = {"data": {"data": [_row("a/m", 1, 0, 1)]}}
    respx_mock.post(URL).mock(return_value=httpx.Response(200, json=payload))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "incomplete"
    assert result.truncated is None
    assert "OpenRouter did not report whether results were truncated" in result.warnings


# --- provider errors --------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403, json={"error": {"message": "nope"}}), "management key (HTTP 403)"),
        (httpx.Response(500, text="boom"), "(HTTP 500)"),
        (httpx.Response(200, content=b"<html>not json"), "invalid JSON"),
        (httpx.Response(200, json={"data": []}), "unexpected response shape"),
        (httpx.Response(200, json={"data": {"data": {"a": 1}}}), "unexpected response shape"),
        (httpx.Response(200, json=[1, 2]), "unexpected response shape"),
    ],
)
async def test_provider_failures_report_error(
    respx_mock: respx.MockRouter, fake_cache: FakeCache, response: httpx.Response, message: str
) -> None:
    respx_mock.post(URL).mock(return_value=response)

    result = await accounts.get_activity("30d", "app", now=NOW)

    assert result.status == "error"
    assert message in (result.error or "")
    assert "k-secret" not in (result.error or "")
    assert result.items == []
    assert result.totals == ActivityTotals()
    assert result.truncated is None
    assert fake_cache.ttls["accounts:activity:v2:30d:app"] == accounts._FAILURE_CACHE_TTL


async def test_transport_failure_reports_error(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    respx_mock.post(URL).mock(side_effect=httpx.ConnectTimeout("slow"))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "error"
    assert "ConnectTimeout" in (result.error or "")
    assert fake_cache.ttls["accounts:activity:v2:today:model"] == accounts._FAILURE_CACHE_TTL


async def test_no_admin_key_is_unconfigured_and_never_calls_out(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    monkeypatch.setattr(accounts._settings, "openrouter_admin_key", "")
    # A regular key must not be used as a fallback: analytics rejects it with 403.
    monkeypatch.setattr(accounts._settings, "openrouter_api_key", "regular-key")
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload([])))

    result = await accounts.get_activity("today", "model", now=NOW)

    assert result.status == "unconfigured"
    assert result.items == []
    assert result.totals == ActivityTotals()
    assert not route.called
    assert fake_cache.store == {}


# --- cache ------------------------------------------------------------------------


async def test_cache_keys_and_ttls_per_period_and_grouping(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=_payload([_row("a/m", 1, 0, 1)]))
    )

    combos = [("today", "model"), ("7d", "model"), ("7d", "app"), ("30d", "api_key")]
    for period, group_by in combos:
        await accounts.get_activity(period, group_by, now=NOW)  # type: ignore[arg-type]

    assert fake_cache.ttls == {
        "accounts:activity:v2:today:model": accounts._ACTIVITY_TODAY_CACHE_TTL,
        "accounts:activity:v2:7d:model": accounts._ACTIVITY_CACHE_TTL,
        "accounts:activity:v2:7d:app": accounts._ACTIVITY_CACHE_TTL,
        "accounts:activity:v2:30d:api_key": accounts._ACTIVITY_CACHE_TTL,
    }
    assert accounts._ACTIVITY_TODAY_CACHE_TTL == 300
    assert accounts._ACTIVITY_CACHE_TTL == 900


async def test_cache_hit_skips_the_provider(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=_payload([_row("a/m", 1, 0, 1)]))
    )

    first = await accounts.get_activity("7d", "model", now=NOW)
    second = await accounts.get_activity("7d", "model", now=NOW)

    assert route.call_count == 1
    assert second.model_dump() == first.model_dump()


async def test_v1_shaped_cache_entry_is_ignored(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    v1 = {
        "items": [
            {
                "model_id": "a/m",
                "requests": 1,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "cost_usd": 2.44,
            }
        ],
        "fetched_at": "2026-10-14T19:00:00Z",
    }
    fake_cache.store["accounts:activity:v2:today:model"] = v1
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=_payload([_row("a/m", 1, 0, 1)]))
    )

    result = await accounts.get_activity("today", "model", now=NOW)

    assert route.call_count == 1
    assert result.items[0].total_usd == 1


async def test_garbage_cache_entry_is_ignored(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    fake_cache.store["accounts:activity:v2:today:model"] = "garbage"
    route = respx_mock.post(URL).mock(return_value=httpx.Response(200, json=_payload([])))

    await accounts.get_activity("today", "model", now=NOW)

    assert route.call_count == 1


async def test_cache_from_a_previous_local_day_is_ignored(
    respx_mock: respx.MockRouter, fake_cache: FakeCache
) -> None:
    route = respx_mock.post(URL).mock(
        return_value=httpx.Response(200, json=_payload([_row("a/m", 1, 0, 1)]))
    )
    await accounts.get_activity("today", "model", now=NOW)
    assert route.call_count == 1

    # 04:00 MDT on Oct 15: the local day rolled over although the entry is far from expired.
    next_day = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    result = await accounts.get_activity("today", "model", now=next_day)

    assert route.call_count == 2
    assert result.period.start_date.isoformat() == "2026-10-15"


# --- route ------------------------------------------------------------------------


def test_route_defaults_and_param_plumbing(
    monkeypatch: pytest.MonkeyPatch, fake_cache: FakeCache
) -> None:
    monkeypatch.setattr(accounts._settings, "openrouter_admin_key", "")
    client = TestClient(app)

    default = client.get("/accounts/activity")
    assert default.status_code == 200
    body = ActivityResponse.model_validate(default.json())
    assert (body.period.key, body.group_by, body.status) == ("today", "model", "unconfigured")
    assert body.period.timezone == "America/Denver"
    assert body.period.partial is True

    chosen = ActivityResponse.model_validate(
        client.get("/accounts/activity", params={"period": "30d", "group_by": "app"}).json()
    )
    assert (chosen.period.key, chosen.group_by) == ("30d", "app")
    assert (chosen.period.end - chosen.period.start).days >= 29


@pytest.mark.parametrize(
    "params", [{"period": "yesterday"}, {"group_by": "provider"}, {"period": "90d"}]
)
def test_route_rejects_invalid_params(params: dict[str, str]) -> None:
    assert TestClient(app).get("/accounts/activity", params=params).status_code == 422
