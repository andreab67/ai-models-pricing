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
_BASE_URL = _settings.kilo_base_url


class KiloUnavailable(RuntimeError):
    """Kilo's gateway could not be reached or returned an error.

    Distinct from "Kilo returned an empty catalog", which is a valid (if odd)
    answer. Returning [] for both is what let a multi-hour Kilo outage on
    2026-09-18 read as a successful fetch of zero models all the way through
    model-speed's catalog-of-record, silently reducing its candidate pool to
    OpenRouter-only with nothing logged above INFO.
    """


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
    """Return Kilo's model catalog.

    Returns [] only when no key is configured, which is a deliberate
    deployment state rather than a failure. Raises KiloUnavailable if the
    gateway is configured but unreachable or erroring, so callers can tell
    "Kilo says zero models" apart from "Kilo did not answer".
    """
    key = _settings.kilo_api_key
    if not key:
        log.warning("kilo_models_skipped_no_key")
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
            # Per-record isolation: one malformed record must not be reported
            # as a gateway outage. _normalize assumes a str id and dict-ish
            # pricing, so schema drift on a single entry would otherwise fall
            # into the except below and 503 the whole catalog -- mislabeling a
            # data problem as an availability problem, which is exactly the
            # conflation this change exists to remove. Mirrors the per-record
            # guard model-speed already has in _normalize_pricing_api.
            normalized: list[ModelPricing] = []
            skipped = 0
            for r in data:
                try:
                    m = _normalize(r)
                except (TypeError, ValueError, AttributeError):
                    skipped += 1
                    continue
                if m is not None:
                    normalized.append(m)
            if skipped:
                log.warning("kilo_models_records_skipped", skipped=skipped, total=len(data))
            if normalized:
                await cache.set(
                    CACHE_KEY,
                    [m.model_dump(mode="json") for m in normalized],
                    ttl=_CACHE_TTL,
                )
            log.info("kilo_models_fetch_ok", count=len(normalized))
            return normalized
        except Exception as exc:
            log.error("kilo_models_fetch_failed", error=str(exc), base_url=_BASE_URL)
            raise KiloUnavailable(f"Kilo gateway unavailable: {exc}") from exc


async def get_model(model_id: str) -> ModelPricing | None:
    models = await fetch_models()
    for m in models:
        if m.id == model_id:
            return m
    return None
