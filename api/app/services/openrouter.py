"""OpenRouter pricing fetcher.

Hits /api/v1/models and normalizes the response. OpenRouter publishes
per-token USD strings; we convert to USD per 1M tokens for sane display.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models import ModelPricingSnapshot
from app.schemas import ModelPricing
from app.services.cache import cache

log = get_logger(__name__)
_settings = get_settings()

OPENROUTER_MODELS_CACHE_KEY = "openrouter:models:normalized"

# The cache must outlive the refresh interval, or every cycle leaves a window
# (job startup + fetch) where the key is gone and requests stampede upstream.
CACHE_TTL_MULTIPLIER = 3

_refresh_lock = asyncio.Lock()


def models_cache_ttl() -> int:
    return _settings.openrouter_refresh_seconds * CACHE_TTL_MULTIPLIER


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_mtok(per_token: str | float | None) -> float:
    """Convert OpenRouter's per-token decimal string to USD per 1M tokens."""
    if per_token is None or per_token == "":
        return 0.0
    try:
        return float(per_token) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _normalize(raw_model: dict[str, Any]) -> ModelPricing | None:
    pricing = raw_model.get("pricing") or {}
    arch = raw_model.get("architecture") or {}
    top = raw_model.get("top_provider") or {}

    prompt = _to_mtok(pricing.get("prompt"))
    completion = _to_mtok(pricing.get("completion"))

    if prompt < 0 or completion < 0:
        return None

    model_id = raw_model.get("id")
    if not model_id:
        return None

    provider = model_id.split("/", 1)[0] if "/" in model_id else None
    modalities = arch.get("input_modalities") or []

    return ModelPricing(
        id=model_id,
        name=raw_model.get("name") or model_id,
        provider=provider,
        prompt_usd_per_mtok=round(prompt, 4),
        completion_usd_per_mtok=round(completion, 4),
        request_usd=_float_or_zero(pricing.get("request")),
        image_usd=_float_or_zero(pricing.get("image")),
        context_length=raw_model.get("context_length") or top.get("context_length"),
        max_completion_tokens=top.get("max_completion_tokens"),
        supports_tools="tools" in (raw_model.get("supported_parameters") or []),
        supports_vision="image" in modalities,
        captured_at=datetime.now(UTC),
    )


async def fetch_raw() -> list[dict[str, Any]]:
    url = f"{_settings.openrouter_base_url}{_settings.openrouter_models_path}"
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(timeout=_settings.openrouter_timeout_s) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
                data = payload.get("data")
                if not isinstance(data, list):
                    raise httpx.HTTPError("OpenRouter /models payload missing 'data' list")
                log.info("openrouter_fetch_ok", count=len(data))
                return data
    return []  # unreachable; tenacity reraise=True


def normalize_all(raw: list[dict[str, Any]]) -> list[ModelPricing]:
    """Normalize every record, skipping (and logging) malformed ones.

    One bad record from upstream must not abort the whole refresh.
    """
    normalized: list[ModelPricing] = []
    for r in raw:
        try:
            m = _normalize(r)
        except Exception as exc:
            log.warning(
                "openrouter_model_skipped",
                model_id=r.get("id") if isinstance(r, dict) else None,
                error=str(exc),
            )
            continue
        if m is not None:
            normalized.append(m)
    return normalized


async def refresh_pricing(persist: bool = True) -> list[ModelPricing]:
    """Fetch, normalize, cache, and (optionally) persist to Postgres."""
    raw = await fetch_raw()
    normalized = normalize_all(raw)

    await cache.set(
        OPENROUTER_MODELS_CACHE_KEY,
        [m.model_dump(mode="json") for m in normalized],
        ttl=models_cache_ttl(),
    )

    if persist:
        await _persist(raw, normalized)
        await prune_snapshots()

    return normalized


async def _persist(
    raw: list[dict[str, Any]], normalized: list[ModelPricing]
) -> None:
    """Insert one snapshot per model per hour in a single statement.

    The refresh job runs several times an hour; once the current hour's
    bucket exists, later runs skip the insert instead of issuing hundreds of
    conflicting no-op rows.
    """
    if not normalized:
        return
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    raw_by_id = {r.get("id"): r for r in raw if isinstance(r, dict)}

    async with session_scope() as session:
        already = await session.scalar(
            select(exists().where(ModelPricingSnapshot.captured_at == now))
        )
        if already:
            log.info("openrouter_persist_skipped", captured_at=now.isoformat())
            return
        rows = [
            {
                "model_id": m.id,
                "name": m.name,
                "provider": m.provider,
                "prompt_usd_per_mtok": m.prompt_usd_per_mtok,
                "completion_usd_per_mtok": m.completion_usd_per_mtok,
                "request_usd": m.request_usd,
                "image_usd": m.image_usd,
                "context_length": m.context_length,
                "max_completion_tokens": m.max_completion_tokens,
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
                "raw": json.dumps(raw_by_id.get(m.id) or {}),
                "captured_at": now,
            }
            for m in normalized
        ]
        stmt = (
            pg_insert(ModelPricingSnapshot)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_model_captured")
        )
        await session.execute(stmt)
    log.info("openrouter_persist_ok", count=len(normalized))


async def prune_snapshots() -> int:
    """Delete snapshots older than the configured retention window."""
    days = _settings.snapshot_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as session:
        result = await session.execute(
            delete(ModelPricingSnapshot).where(ModelPricingSnapshot.captured_at < cutoff)
        )
    deleted = int(getattr(result, "rowcount", 0) or 0)
    if deleted:
        log.info("openrouter_snapshots_pruned", deleted=deleted, retention_days=days)
    return deleted


async def list_models(use_cache: bool = True) -> list[ModelPricing]:
    """Public read path. Returns cached models or refreshes on miss.

    Concurrent misses share one upstream fetch (single-flight): the first
    caller refreshes while the rest wait on the lock and then read the
    freshly cached value.
    """
    if use_cache:
        cached = await cache.get(OPENROUTER_MODELS_CACHE_KEY)
        if cached:
            return [ModelPricing.model_validate(c) for c in cached]
    async with _refresh_lock:
        if use_cache:
            cached = await cache.get(OPENROUTER_MODELS_CACHE_KEY)
            if cached:
                return [ModelPricing.model_validate(c) for c in cached]
        return await refresh_pricing(persist=False)


async def get_model(model_id: str) -> ModelPricing | None:
    models = await list_models()
    for m in models:
        if m.id == model_id:
            return m
    return None


async def get_history(model_id: str, days: int = 30) -> list[ModelPricing]:
    """Pull recent snapshots from Postgres."""
    since = datetime.now(UTC) - timedelta(days=days)
    async with session_scope() as session:
        stmt = (
            select(ModelPricingSnapshot)
            .where(
                ModelPricingSnapshot.model_id == model_id,
                ModelPricingSnapshot.captured_at >= since,
            )
            .order_by(ModelPricingSnapshot.captured_at.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()

    return [
        ModelPricing(
            id=row.model_id,
            name=row.name,
            provider=row.provider,
            prompt_usd_per_mtok=row.prompt_usd_per_mtok,
            completion_usd_per_mtok=row.completion_usd_per_mtok,
            request_usd=row.request_usd,
            image_usd=row.image_usd,
            context_length=row.context_length,
            max_completion_tokens=row.max_completion_tokens,
            supports_tools=row.supports_tools,
            supports_vision=row.supports_vision,
            captured_at=row.captured_at,
        )
        for row in rows
    ]
