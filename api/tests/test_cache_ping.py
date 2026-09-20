"""Cache.ping(): the probe that must NOT be absorbed by the fallback.

Every /readyz test stubs cache.ping out, so without this file the one piece of
new production logic -- "redis is probed for real and reported honestly" -- has
no coverage at all. What matters here is that ping() can return False. get()
and set() cannot: they fall back to the in-process dict and succeed during an
outage, which is precisely why ping() exists.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.cache import Cache


@pytest.fixture
def cache() -> Cache:
    return Cache("redis://unused:6379/0", default_ttl=60)


def _install(cache: Cache, client: object | None) -> None:
    """Pin the client so _client_or_none() short-circuits to it."""
    cache._client = client  # type: ignore[assignment]


async def test_ping_true_when_redis_answers(cache):
    class _Client:
        async def ping(self):
            return True

    _install(cache, _Client())
    assert await cache.ping() is True


async def test_ping_false_when_redis_is_unreachable(cache):
    """No client at all: _client_or_none() fails to connect and returns None."""

    async def _no_client():
        return None

    cache._client_or_none = _no_client  # type: ignore[assignment]
    assert await cache.ping() is False


async def test_ping_false_and_client_dropped_when_the_command_raises(cache):
    class _Client:
        async def ping(self):
            raise ConnectionError("redis went away")

    _install(cache, _Client())
    assert await cache.ping() is False
    # The dead client must be dropped so the next probe reconnects.
    assert cache._client is None


async def test_ping_false_when_redis_answers_falsily(cache):
    class _Client:
        async def ping(self):
            return False

    _install(cache, _Client())
    assert await cache.ping() is False


async def test_a_non_coroutine_awaitable_is_awaited_not_coerced(cache):
    """The iscoroutine trap: a Future is awaitable but is not a coroutine.

    With `asyncio.iscoroutine` the await is skipped and `bool(<Future>)` is
    unconditionally True -- reporting redis=true straight through an outage.
    """

    class _Client:
        def ping(self):
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            future.set_result(False)
            return future

    _install(cache, _Client())
    assert await cache.ping() is False


async def test_ping_is_not_satisfied_by_the_in_memory_fallback(cache):
    """The whole point: set/get succeed during an outage, ping must not."""

    async def _no_client():
        return None

    cache._client_or_none = _no_client  # type: ignore[assignment]

    await cache.set("k", 1, ttl=5)
    assert await cache.get("k") == 1  # fallback happily serves this
    assert await cache.ping() is False  # ...but readiness is told the truth
