"""OpenRouter activity parsing tolerates one malformed row (Kilo Code Review)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.services import accounts


@respx.mock
async def test_activity_survives_malformed_total_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _miss(_key: str) -> None:
        return None

    stored: dict[str, Any] = {}

    async def _set(key: str, value: Any, ttl: int | None = None) -> None:
        stored["ttl"] = ttl

    monkeypatch.setattr(accounts.cache, "get", _miss)
    monkeypatch.setattr(accounts.cache, "set", _set)
    monkeypatch.setattr(accounts._settings, "openrouter_admin_key", "k")
    respx.post("https://openrouter.ai/api/v1/analytics/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "data": [
                        {"model": "a/good", "total_usage": "1.25", "request_count": "3"},
                        {"model": "b/bad", "total_usage": "not-a-number", "request_count": "1"},
                        {"model": "c/nan", "total_usage": "NaN", "request_count": "2"},
                    ]
                }
            },
        )
    )

    result = await accounts.get_activity()

    by_id = {i.model_id: i for i in result.items}
    assert by_id["a/good"].cost_usd == 1.25
    assert by_id["b/bad"].cost_usd == 0.0
    assert by_id["c/nan"].cost_usd == 0.0
    # A successful parse is cached for the full TTL, not the failure TTL.
    assert stored["ttl"] == accounts._ACTIVITY_CACHE_TTL
