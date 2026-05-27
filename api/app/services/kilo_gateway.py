"""Kilo AI Gateway model catalog fetcher.

Hits /api/gateway/models and normalizes the response. The Kilo gateway is
OpenAI-compatible and uses the same model-id/pricing format as OpenRouter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.logging import get_logger
from app.schemas import ModelPricing
from app.services.cache import cache

log = get_logger(__name__)
_settings = get_settings()

CACHE_KEY = "kilo:models:normalized"
_CACHE_TTL = 900  # 15 min
_BASE_URL = "https://api.kilo.ai/api/gateway"


def _to_mtok(per_token: str | float | None) -> float:
    """Convert per-token decimal string to USD per 1M tokens."""
    if per_token is None or per_token == "":
        return 0.0
    try:
        return float(per_token) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _normalize(raw: dict[str, Any]) -> ModelPricing | None:
    pricing = raw.get("pricing") or {}
    arch = raw.get("architecture") or {}

    prompt = _to_mtok(pricing.get("prompt"))
    completion = _to_mtok(pricing.get("completion"))

    if prompt < 0 or completion < 0:
        return None

    model_id = raw.get("id")
    if not model_id:
        return None

    provider = model_id.split("/", 1)[0] if "/" in model_id else None
    modalities = arch.get("input_modalities") or raw.get("input_modalities") or []

    return ModelPricing(
        id=model_id,
        name=raw.get("name") or model_id,
        provider=provider,
        prompt_usd_per_mtok=round(prompt, 4),
        completion_usd_per_mtok=round(completion, 4),
        request_usd=float(pricing.get("request") or 0),
        image_usd=float(pricing.get("image") or 0),
        context_length=raw.get("context_length"),
        max_completion_tokens=(raw.get("top_provider") or {}).get("max_completion_tokens"),
        supports_tools="tools" in (raw.get("supported_parameters") or []),
        supports_vision="image" in modalities,
        captured_at=datetime.now(UTC),
    )


async def fetch_models() -> list[ModelPricing]:
    """Return Kilo's model catalog. Empty list if key not configured or fetch fails."""
    key = _settings.kilo_api_key
    if not key:
        return []

    cached = await cache.get(CACHE_KEY)
    if cached:
        return [ModelPricing.model_validate(m) for m in cached]

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                f"{_BASE_URL}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            normalized = [m for r in data if (m := _normalize(r)) is not None]
            if normalized:
                await cache.set(
                    CACHE_KEY,
                    [m.model_dump(mode="json") for m in normalized],
                    ttl=_CACHE_TTL,
                )
            log.info("kilo_models_fetch_ok", count=len(normalized))
            return normalized
        except Exception as exc:
            log.warning("kilo_models_fetch_failed", error=str(exc))
            return []


async def get_model(model_id: str) -> ModelPricing | None:
    models = await fetch_models()
    for m in models:
        if m.id == model_id:
            return m
    return None
