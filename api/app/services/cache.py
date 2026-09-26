"""Thin Redis cache wrapper. Falls back to in-memory if Redis unreachable."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import redis.asyncio as redis

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
_settings = get_settings()

# Bound every Redis round trip so a blackholed Redis cannot stall requests,
# and back off between reconnect attempts instead of dialling on every call.
_SOCKET_TIMEOUT_S = 2.0
_RECONNECT_BACKOFF_S = 30.0


class Cache:
    """Async cache with Redis primary + in-memory fallback.

    The fallback keeps the API alive when Redis dies — it's a single-node
    in-process dict, so every replica is independent. Loud-fail in logs so
    we notice if Redis is gone for long.
    """

    def __init__(self, url: str, default_ttl: int) -> None:
        self._url = url
        self._default_ttl = default_ttl
        self._client: redis.Redis | None = None
        self._next_connect_at = 0.0
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    def _safe_url(self) -> str:
        return re.sub(r":[^@/]+@", ":***@", self._url)

    def _mark_down(self) -> None:
        client, self._client = self._client, None
        self._next_connect_at = time.monotonic() + _RECONNECT_BACKOFF_S
        if client is not None:
            # Fire-and-forget close; a failing close must not mask the error.
            try:
                asyncio.get_running_loop().create_task(client.aclose())
            except RuntimeError:
                pass

    async def _client_or_none(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client
        if time.monotonic() < self._next_connect_at:
            return None
        client = redis.from_url(
            self._url,
            decode_responses=True,
            socket_connect_timeout=_SOCKET_TIMEOUT_S,
            socket_timeout=_SOCKET_TIMEOUT_S,
        )
        try:
            await client.ping()
        except Exception as exc:
            log.warning("redis_unavailable", url=self._safe_url(), error=str(exc))
            self._next_connect_at = time.monotonic() + _RECONNECT_BACKOFF_S
            try:
                await client.aclose()
            except Exception:  # noqa: S110 — best-effort cleanup
                pass
            return None
        self._client = client
        return client

    async def redis_available(self) -> bool:
        """True only if Redis itself answers a PING right now (not the fallback)."""
        client = await self._client_or_none()
        if client is None:
            return False
        try:
            return bool(await client.ping())
        except Exception as exc:
            log.warning("redis_ping_failed", error=str(exc))
            self._mark_down()
            return False

    async def get(self, key: str) -> Any | None:
        client = await self._client_or_none()
        if client is not None:
            try:
                raw = await client.get(key)
                if raw is None:
                    return None
                return json.loads(raw)
            except Exception as exc:
                log.warning("redis_get_failed", key=key, error=str(exc))
                self._mark_down()

        async with self._lock:
            entry = self._mem.get(key)
            if entry is None:
                return None
            expires_at, raw = entry
            if expires_at < time.time():
                self._mem.pop(key, None)
                return None
            return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl or self._default_ttl
        raw = json.dumps(value, default=str)
        client = await self._client_or_none()
        if client is not None:
            try:
                await client.set(key, raw, ex=ttl)
                return
            except Exception as exc:
                log.warning("redis_set_failed", key=key, error=str(exc))
                self._mark_down()

        async with self._lock:
            self._mem[key] = (time.time() + ttl, raw)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: S110
                pass
            self._client = None


cache = Cache(_settings.redis_url, _settings.cache_ttl_seconds)
