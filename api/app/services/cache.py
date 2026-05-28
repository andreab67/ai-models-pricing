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
                await self._client.ping()
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
                return json.loads(raw)
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
                self._client = None

        async with self._lock:
            self._mem[key] = (time.time() + ttl, raw)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: S110
                pass


cache = Cache(_settings.redis_url, _settings.cache_ttl_seconds)
