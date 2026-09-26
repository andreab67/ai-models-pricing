"""Liveness + readiness."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import session_scope
from app.services.cache import cache

router = APIRouter(tags=["meta"])

# Both probes run concurrently under one budget, so the handler finishes in
# about this long even when Redis is slow; keep the probe timeoutSeconds above.
_READYZ_BUDGET_S = 2.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _db_ok() -> bool:
    async with session_scope() as session:
        await session.execute(text("select 1"))
    return True


async def _bounded(probe: Coroutine[Any, Any, bool]) -> bool:
    try:
        return bool(await asyncio.wait_for(probe, timeout=_READYZ_BUDGET_S))
    except Exception:
        return False


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Returns 503 if Postgres is unreachable.

    Redis is reported honestly (``redis`` is true only when Redis itself
    answers a PING) but does not gate readiness: the cache falls back to
    process memory, so the API keeps serving without it.
    """
    db_ok, redis_ok = await asyncio.gather(
        _bounded(_db_ok()), _bounded(cache.redis_available())
    )

    ready = db_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"db": db_ok, "redis": redis_ok, "ready": ready}
