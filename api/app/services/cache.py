"""Thin Redis cache wrapper. Falls back to in-memory if Redis unreachable."""

from __future__ import annotations

import asyncio
import inspect
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

# Strong references to fire-and-forget close tasks so they are not garbage
# collected before they run.
_background_tasks: set[asyncio.Task[Any]] = set()


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
        self._connect_lock = asyncio.Lock()

    def _safe_url(self) -> str:
        return re.sub(r":[^@/]+@", ":***@", self._url)

    def _mark_down(self) -> None:
        """Drop the current client and back off before reconnecting."""
        client, self._client = self._client, None
        self._next_connect_at = time.monotonic() + _RECONNECT_BACKOFF_S
        closer = getattr(client, "aclose", None)
        if closer is None:
            return
        # Fire-and-forget close; a failing close must not mask the error.
        try:
            task = asyncio.get_running_loop().create_task(closer())
        except Exception:  # noqa: S110 — no loop / not a coroutine: best effort
            return
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _client_or_none(self) -> redis.Redis | None:
        if self._client is not None:
            return self._client
        if time.monotonic() < self._next_connect_at:
            return None
        # One connect attempt at a time; concurrent callers reuse its result
        # instead of each opening (and leaking) their own client.
        async with self._connect_lock:
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
                # redis-py types ping() as Union[Awaitable, Any], so it may hand
                # back either an awaitable or a raw bool. isawaitable, NOT
                # iscoroutine, so a Future/Task is awaited too rather than
                # dropped unawaited -- dropping it would skip the connectivity
                # check this call exists to perform.
                ping_result = client.ping()
                if inspect.isawaitable(ping_result):
                    await ping_result
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
                self._mark_down()

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
        no_retain = ttl is not None and ttl <= 0
        if ttl is None or ttl <= 0:
            ttl = self._default_ttl
        raw = json.dumps(value, default=str)
        client = await self._client_or_none()
        if client is not None:
            try:
                if no_retain:
                    # Caller asked to not retain — delete any existing entry
                    # rather than writing a short-lived tombstone that a
                    # subsequent get() could read back within the window.
                    await client.delete(key)
                else:
                    await client.set(key, raw, ex=ttl)
                return
            except Exception as exc:
                log.warning("redis_set_failed", key=key, error=str(exc))
                self._mark_down()

        async with self._lock:
            if no_retain:
                # Match the Redis branch: do not retain in-memory either.
                self._mem.pop(key, None)
                return
            self._mem[key] = (time.time() + ttl, raw)

    async def ping(self) -> bool:
        """True only when the REAL Redis answered.

        Deliberately NOT expressible via get()/set(): those fall back to the
        in-process dict by design, so during a Redis outage they SUCCEED and
        cannot tell you whether Redis is actually there. A readiness probe
        built on them reports redis=true no matter what, which is worse than
        not reporting at all. This reaches the client directly instead.
        """
        client = await self._client_or_none()
        if client is None:
            return False
        try:
            result = client.ping()
            # Same stub inconsistency _client_or_none() works around: redis-py
            # types ping() as Union[Awaitable, Any], so it may hand back either
            # an awaitable or a raw bool. isawaitable, NOT iscoroutine: a Future,
            # a Task or any __await__ object is not a coroutine, so iscoroutine
            # would skip the await and bool() a live awaitable -- which is
            # unconditionally True. That would report redis=true straight
            # through an outage, the exact silent pass this method exists to
            # stop.
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as exc:
            log.warning("redis_ping_failed", error=str(exc))
            self._mark_down()
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: S110
                pass
            self._client = None


cache = Cache(_settings.redis_url, _settings.cache_ttl_seconds)
