"""Unit tests for OpenRouter speed extraction + normalization defaults."""

from __future__ import annotations

from app.schemas import ModelPricing
from app.services import openrouter


def _endpoints(*eps: dict) -> dict:
    return {"data": {"endpoints": list(eps)}}


def test_extract_speed_takes_first_endpoint_with_sample() -> None:
    payload = _endpoints(
        {
            "provider_name": "Amazon Bedrock",
            "throughput_last_30m": {"p50": 48, "p90": 66},
            "latency_last_30m": {"p50": 2061.5},
        },
        {
            "provider_name": "Google",
            "throughput_last_30m": {"p50": 40},
            "latency_last_30m": {"p50": 1045},
        },
    )
    tps, latency, provider = openrouter._extract_speed(payload)
    assert tps == 48.0
    assert latency == 2061.5
    assert provider == "Amazon Bedrock"


def test_extract_speed_skips_null_throughput_endpoints() -> None:
    """First endpoint has no live sample — fall through to the next that does."""
    payload = _endpoints(
        {
            "provider_name": "OpenAI",
            "throughput_last_30m": None,
            "latency_last_30m": None,
        },
        {
            "provider_name": "Azure",
            "throughput_last_30m": {"p50": 75},
            "latency_last_30m": {"p50": 900},
        },
    )
    tps, latency, provider = openrouter._extract_speed(payload)
    assert tps == 75.0
    assert latency == 900.0
    assert provider == "Azure"


def test_extract_speed_all_null_returns_none() -> None:
    payload = _endpoints(
        {"provider_name": "OpenAI", "throughput_last_30m": None},
    )
    assert openrouter._extract_speed(payload) == (None, None, None)


def test_extract_speed_no_endpoints_returns_none() -> None:
    assert openrouter._extract_speed({"data": {"endpoints": []}}) == (None, None, None)
    assert openrouter._extract_speed({}) == (None, None, None)


def test_extract_speed_missing_latency_is_tolerated() -> None:
    payload = _endpoints(
        {"provider_name": "DeepInfra", "throughput_last_30m": {"p50": 120}},
    )
    tps, latency, provider = openrouter._extract_speed(payload)
    assert tps == 120.0
    assert latency is None
    assert provider == "DeepInfra"


def test_normalize_defaults_speed_to_none() -> None:
    """/models payload carries no speed — fields default to None until enriched."""
    raw = {
        "id": "anthropic/claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "context_length": 1_000_000,
        "supported_parameters": ["tools"],
        "architecture": {"input_modalities": ["text", "image"]},
    }
    m = openrouter._normalize(raw)
    assert m is not None
    assert m.throughput_tps is None
    assert m.latency_ms is None
    assert m.speed_provider is None


def test_model_pricing_round_trips_speed_fields() -> None:
    m = ModelPricing.model_validate(
        {
            "id": "x/y",
            "name": "Y",
            "prompt_usd_per_mtok": 1.0,
            "completion_usd_per_mtok": 2.0,
            "throughput_tps": 48.0,
            "latency_ms": 2061.5,
            "speed_provider": "Amazon Bedrock",
            "captured_at": "2026-06-11T00:00:00Z",
        }
    )
    dumped = m.model_dump(mode="json")
    assert dumped["throughput_tps"] == 48.0
    assert dumped["latency_ms"] == 2061.5
    assert dumped["speed_provider"] == "Amazon Bedrock"
