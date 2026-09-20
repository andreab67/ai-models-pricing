"""Liveness + readiness."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import session_scope
from app.services.cache import cache

router = APIRouter(tags=["meta"])

# /readyz makes four network round trips and none of the clients below carries
# a deadline of its own, so a hung Postgres or Redis would hold the handler
# open until the kubelet gave up -- surfacing as the opaque "context deadline
# exceeded" rather than a 503 naming the dependency. Bound each check instead.
# Keep this under the readinessProbe timeoutSeconds in
# k8s/base/api-deployment.yaml (currently 3s).
_READYZ_BUDGET_S = 2.0


def _discard_outcome(task: asyncio.Task[bool]) -> None:
    """Retrieve an abandoned probe task's outcome.

    Nothing awaits a task we cancelled, so if it finishes with a real
    exception instead of honouring the cancellation -- e.g. the session
    teardown in session_scope raises because the connection is already dead --
    asyncio logs "Task exception was never retrieved" when it is collected.
    Reading .exception() here marks it retrieved and keeps the probe silent.
    """
    if not task.cancelled():
        task.exception()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Returns 503 if Postgres or Redis is unreachable."""

    async def _db() -> bool:
        async with session_scope() as session:
            await session.execute(text("select 1"))
        return True

    async def _redis() -> bool:
        await cache.set("readyz:probe", 1, ttl=5)
        return await cache.get("readyz:probe") == 1

    # Both checks run CONCURRENTLY under one budget. Bounding them one after
    # the other would be wrong twice over: the handler could run for twice
    # _READYZ_BUDGET_S and overshoot the probe deadline it exists to stay under,
    # and whichever check ran second would be handed whatever was left -- often
    # 0s -- and be reported down when it is healthy. Attribution is the point of
    # returning {"db": ..., "redis": ...}, so it has to be accurate.
    tasks = {"db": asyncio.create_task(_db()), "redis": asyncio.create_task(_redis())}
    try:
        await asyncio.wait(tasks.values(), timeout=_READYZ_BUDGET_S)

        results: dict[str, bool] = {}
        for name, task in tasks.items():
            if not task.done():
                results[name] = False
            else:
                results[name] = (
                    not task.cancelled() and task.exception() is None and task.result() is True
                )
    finally:
        # Unlike a thread, a stalled task can actually be cancelled, so a slow
        # dependency leaves nothing running behind the probe. This has to sit
        # in a finally: the probe client hanging up (the kubelet's own
        # timeoutSeconds firing, or shutdown) cancels THIS handler inside
        # asyncio.wait, and without the cleanup both checks would be orphaned
        # -- each holding a pooled Postgres connection that nothing reclaims,
        # so a Postgres stall would drain the pool one probe at a time.
        for task in tasks.values():
            if not task.done():
                task.cancel()
                task.add_done_callback(_discard_outcome)

    db_ok = results["db"]
    redis_ok = results["redis"]

    ready = db_ok and redis_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"db": db_ok, "redis": redis_ok, "ready": ready}
