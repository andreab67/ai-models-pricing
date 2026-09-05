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
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    async def _client_or_none(self) -> redis.Redis | None:
        if self._client is None:
            try:
                self._client = redis.from_url(self._url, decode_responses=True)
                # redis-py returns Awaitable[bool] from a sync call site under
                # type stubs but a raw bool in the legacy stubs mypy ships with.
                ping_result = self._client.ping()
                if asyncio.iscoroutine(ping_result):
                    await ping_result
            except Exception as exc:
                safe_url = re.sub(r":[^@]+@", ":@", self._url)
                log.warning("redis_unavailable", url=safe_url, error=str(exc))
                self._client = None
        return self._client

    async def get(self, key: str) -> Any | None:
        client = await self._client_or_none()
        if client is not None:
            try:
                raw = await client.get(key)
                if raw is None:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("cache_corrupt_value", key=key, backend="redis")
                    try:
                        await client.delete(key)
                    except Exception as exc:
                        log.warning("cache_corrupt_delete_failed", key=key, error=str(exc))
                    return None
            except Exception as exc:
                log.warning("redis_get_failed", key=key, error=str(exc))
                self._client = None

        async with self._lock:
            entry = self._mem.get(key)
            if entry is None:
                return None
            expires_at, raw = entry
            if expires_at < time.time():
                self._mem.pop(key, None)
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                log.warning("cache_corrupt_value", key=key, backend="memory")
                self._mem.pop(key, None)
                return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if ttl is None:
            ttl = self._default_ttl
        if ttl <= 0:
            # Negative/zero TTL means "don't retain" — honor by expiring immediately.
            # We don't have a "delete" verb on this API, so drop in-memory only and
            # use ex=1 for Redis (a 1-second TTL is the closest portable option).
            ttl = 1
        raw = json.dumps(value, default=str)
        client = await self._client_or_none()
        if client is not None:
            try:
                await client.set(key, raw, ex=ttl)
                return
            except Exception as exc:
                log.warning("redis_set_failed", key=key, error=str(exc))
                self._client = None

        async with self._lock:
            if ttl == 1:
                # Match the Redis branch: do not retain in-memory either.
                self._mem.pop(key, None)
                return
            self._mem[key] = (time.time() + ttl, raw)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: S110
                pass


cache = Cache(_settings.redis_url, _settings.cache_ttl_seconds)
