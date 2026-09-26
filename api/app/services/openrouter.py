"""OpenRouter pricing fetcher.

Hits /api/v1/models and normalizes the response. OpenRouter publishes
per-token USD strings; we convert to USD per 1M tokens for sane display.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select
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

CACHE_KEY = "openrouter:models:normalized"

# The cache must outlive the refresh interval, or every cycle leaves a window
# (job startup + fetch) where the key is gone and requests stampede upstream.
CACHE_TTL_MULTIPLIER = 3

# Single-flight: concurrent cache misses await one shared refresh task, so a
# failure is shared too instead of each waiter re-running the retry cycle.
_inflight_refresh: asyncio.Task[list[ModelPricing]] | None = None

# Bound concurrent endpoint requests during speed enrichment — one call per model.
_SPEED_CONCURRENCY = 8


# Allowlist of hosts we will attach the OpenRouter bearer token to. This blocks
# SSRF-via-catalog: if a model's `links.details` URL is hijacked to an
# attacker-controlled host, we refuse to send the Authorization header there.
# Only paths under the public models endpoints are allowed — the catalog's
# `links.details` always points at /api/v1/models/..., so restricting the path
# prefix means a hijacked catalog cannot redirect the bearer to e.g.
# /account/transfer-credits.
_ALLOWED_DETAIL_HOSTS = frozenset({"openrouter.ai"})
_ALLOWED_DETAIL_PATH_PREFIXES: tuple[str, ...] = ("/api/v1/models/",)


def models_cache_ttl() -> int:
    return _settings.openrouter_refresh_seconds * CACHE_TTL_MULTIPLIER


def _is_allowed_detail_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    host = parts.hostname or ""
    if not any(host == h or host.endswith(f".{h}") for h in _ALLOWED_DETAIL_HOSTS):
        return False
    path = parts.path or ""
    return any(path.startswith(p) for p in _ALLOWED_DETAIL_PATH_PREFIXES)


def _auth_headers() -> dict[str, str]:
    """Authorization header for OpenRouter. Required for speed stats."""
    key = _settings.openrouter_api_key
    return {"Authorization": f"Bearer {key}"} if key else {}


def _to_mtok(per_token: str | float | None) -> float:
    """Convert OpenRouter's per-token decimal string to USD per 1M tokens."""
    if per_token is None or per_token == "":
        return 0.0
    try:
        return float(per_token) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0)
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


async def fetch_raw() -> list[dict[str, Any]]:
    url = f"{_settings.openrouter_base_url}{_settings.openrouter_models_path}"
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError,)),
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(
                timeout=_settings.openrouter_timeout_s, headers=_auth_headers()
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
                data = payload.get("data")
                if not isinstance(data, list):
                    raise httpx.HTTPError("OpenRouter /models payload missing 'data' list")
                log.info("openrouter_fetch_ok", count=len(data))
                return data
    raise httpx.HTTPError("OpenRouter /models fetch exhausted retries")


def _extract_speed(
    payload: dict[str, Any],
) -> tuple[float | None, float | None, str | None]:
    """Pull default-route p50 throughput/latency from an endpoints payload.

    OpenRouter returns endpoints in routing-preference order. We take the first
    endpoint that actually has a recent throughput sample — that's the speed a
    default-routed request realistically gets. Returns (tps, latency_ms, provider).
    """
    endpoints = (payload.get("data") or {}).get("endpoints") or []
    for ep in endpoints:
        tp = (ep.get("throughput_last_30m") or {}).get("p50")
        if tp is None:
            continue
        lat = (ep.get("latency_last_30m") or {}).get("p50")
        return (
            float(tp),
            float(lat) if lat is not None else None,
            ep.get("provider_name"),
        )
    return None, None, None


async def enrich_speeds(
    normalized: list[ModelPricing], raw: list[dict[str, Any]]
) -> None:
    """Populate throughput/latency in-place from OpenRouter's endpoints API.

    Issues one authenticated request per model (bounded concurrency), so this
    runs only in the background refresh job — never on the read path. Per-model
    failures are tolerated: the model simply keeps null speed.
    """
    headers = _auth_headers()
    if not headers:
        log.warning("openrouter_speed_skip_no_key")
        return

    details_by_id = {
        r.get("id"): (r.get("links") or {}).get("details") for r in raw
    }
    by_id = {m.id: m for m in normalized}
    parts = urlsplit(_settings.openrouter_base_url)
    host_root = f"{parts.scheme}://{parts.netloc}"
    sem = asyncio.Semaphore(_SPEED_CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=_settings.openrouter_timeout_s, headers=headers
    ) as client:

        async def _one(model_id: str | None, details: str | None) -> None:
            if not model_id or not details:
                return
            url = f"{host_root}{details}" if details.startswith("/") else details
            # Guard: never attach the bearer token to a host outside the allowlist.
            # Both the prefix-join case (URL inherits host_root) and the absolute-URL
            # case are checked against the same set so a hijacked catalog can't
            # exfiltrate the OpenRouter API key.
            if not _is_allowed_detail_url(url):
                log.warning(
                    "openrouter_speed_url_rejected", model=model_id, url=url,
                )
                return
            async with sem:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    tps, latency, provider = _extract_speed(resp.json())
                except (httpx.HTTPError, ValueError) as exc:
                    log.debug(
                        "openrouter_speed_fetch_failed", model=model_id, error=str(exc)
                    )
                    return
            m = by_id.get(model_id)
            if m is not None and tps is not None:
                m.throughput_tps = round(tps, 1)
                m.latency_ms = round(latency, 1) if latency is not None else None
                m.speed_provider = provider

        await asyncio.gather(
            *(_one(mid, d) for mid, d in details_by_id.items())
        )

    enriched = sum(1 for m in normalized if m.throughput_tps is not None)
    log.info("openrouter_speed_enrich_ok", enriched=enriched, total=len(normalized))


async def refresh_pricing(
    persist: bool = True, enrich_speed: bool = False
) -> list[ModelPricing]:
    """Fetch, normalize, cache, and (optionally) persist to Postgres.

    ``enrich_speed`` adds one endpoints request per model to attach throughput/
    latency — enable it only in the background CronJob, not on the read path.
    """
    raw = await fetch_raw()
    normalized = normalize_all(raw)

    if enrich_speed:
        await enrich_speeds(normalized, raw)

    await cache.set(
        CACHE_KEY,
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
    """Insert one snapshot per model per hour in a single batched statement.

    The refresh job runs several times an hour; rows already present for the
    current hour bucket are skipped by the unique constraint, and models that
    were missing from an earlier run in the same hour are filled in.
    """
    if not normalized:
        return
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    raw_by_id = {r.get("id"): r for r in raw if isinstance(r, dict)}

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
            "throughput_tps": m.throughput_tps,
            "latency_ms": m.latency_ms,
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
    async with session_scope() as session:
        await session.execute(stmt)
    log.info("openrouter_persist_ok", count=len(normalized), captured_at=now.isoformat())


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

    Concurrent misses share one upstream fetch: the first caller starts a
    refresh task and every other caller awaits the same task (and gets the
    same result or exception).
    """
    global _inflight_refresh
    if use_cache:
        cached = await cache.get(CACHE_KEY)
        if cached:
            return [ModelPricing.model_validate(c) for c in cached]
    if _inflight_refresh is None or _inflight_refresh.done():
        _inflight_refresh = asyncio.create_task(refresh_pricing(persist=False))
        # Mark the exception as retrieved even if every waiter was cancelled,
        # so asyncio does not log "Task exception was never retrieved".
        _inflight_refresh.add_done_callback(lambda t: t.cancelled() or t.exception())
    # shield: a cancelled request must not cancel the refresh others await.
    return await asyncio.shield(_inflight_refresh)


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
            throughput_tps=row.throughput_tps,
            latency_ms=row.latency_ms,
            captured_at=row.captured_at,
        )
        for row in rows
    ]
