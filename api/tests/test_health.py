"""Probe endpoints: the bound, the attribution, and what actually gates ready.

These pin down three things that were all wrong or unguarded before:

  1. /readyz answers WITHIN its budget when a dependency hangs. The kubelet
     deadline is 3s (k8s/base/api-deployment.yaml); if the handler runs past
     it the probe fails as the opaque "context deadline exceeded" instead of
     a 503 naming the dependency.
  2. The budget is SHARED and the checks run CONCURRENTLY. Bounding them one
     after the other would let the handler run for twice the budget, and
     would hand the second check whatever was left -- often 0s -- reporting
     it down while healthy.
  3. Redis is reported, NOT gated. Cache falls back to an in-process dict on
     purpose so the API survives a Redis outage; failing readiness would take
     the API down for an outage the design tolerates.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import health
from app.routes.health import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def stub_deps(monkeypatch):
    """Replace both dependencies with controllable async stubs."""

    def _apply(db=None, redis=None):
        class _Session:
            async def execute(self, _stmt):
                if db is not None:
                    await db()
                return None

        class _Scope:
            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, *_exc):
                return False

        monkeypatch.setattr(health, "session_scope", lambda: _Scope())

        async def _ping():
            if redis is not None:
                return await redis()
            return True

        monkeypatch.setattr(health.cache, "ping", _ping)

    return _apply


def test_healthz_does_no_io(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_all_healthy(client, stub_deps):
    stub_deps()
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"db": True, "redis": True, "ready": True}


def test_readyz_503_when_postgres_is_down(client, stub_deps):
    async def boom():
        raise RuntimeError("no postgres")

    stub_deps(db=boom)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"db": False, "redis": True, "ready": False}


def test_redis_outage_is_reported_but_does_not_gate_ready(client, stub_deps):
    """The whole point of the in-memory fallback: stay up without Redis."""

    async def down():
        return False

    stub_deps(redis=down)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"db": True, "redis": False, "ready": True}


def test_readyz_answers_within_budget_when_a_dependency_hangs(client, stub_deps, monkeypatch):
    monkeypatch.setattr(health, "_READYZ_BUDGET_S", 0.2)

    async def hang():
        await asyncio.sleep(30)

    stub_deps(db=hang)
    started = time.monotonic()
    response = client.get("/readyz")
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json()["db"] is False
    # Generous slack for slow CI hosts; the point is 30s did not elapse.
    assert elapsed < 5, f"readyz took {elapsed:.2f}s; the budget was not enforced"


def test_a_hanging_check_does_not_consume_the_other_checks_budget(client, stub_deps, monkeypatch):
    """The regression that a sequential drain would reintroduce.

    db hangs and eats the whole budget. redis is healthy but slightly slow --
    if the budget were spent in sequence it would be handed ~0s and reported
    down. Concurrently, it finishes comfortably.
    """
    monkeypatch.setattr(health, "_READYZ_BUDGET_S", 0.5)

    async def hang():
        await asyncio.sleep(30)

    async def slow_but_fine():
        await asyncio.sleep(0.1)
        return True

    stub_deps(db=hang, redis=slow_but_fine)
    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"db": False, "redis": True, "ready": False}


async def test_hanging_checks_are_cancelled_not_left_running(stub_deps, monkeypatch):
    """A stalled dependency must not leave work -- and a pooled DB connection.

    Called directly rather than through TestClient so the assertion runs on
    the same loop the handler used and can observe the cancellation land.
    """
    monkeypatch.setattr(health, "_READYZ_BUDGET_S", 0.2)
    cancelled = asyncio.Event()

    async def hang():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stub_deps(db=hang)

    class _Response:
        status_code = 200

    body = await health.readyz(_Response())

    assert body["db"] is False
    assert body["ready"] is False
    # cancel() only SCHEDULES cancellation; give the loop a turn to deliver it.
    await asyncio.sleep(0.05)
    assert cancelled.is_set(), "the stalled check was left running after the probe answered"
