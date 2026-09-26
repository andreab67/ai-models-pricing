"""Liveness + readiness."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import session_scope
from app.services.cache import cache

router = APIRouter(tags=["meta"])

_PROBE_TIMEOUT_S = 3.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _db_ok() -> bool:
    async with session_scope() as session:
        await session.execute(text("select 1"))
    return True


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Returns 503 if Postgres is unreachable.

    Redis is reported honestly (``redis`` is true only when Redis itself
    answers a PING) but does not gate readiness: the cache falls back to
    process memory, so the API keeps serving without it.
    """
    try:
        db_ok = await asyncio.wait_for(_db_ok(), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        db_ok = False

    try:
        redis_ok = await asyncio.wait_for(cache.redis_available(), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        redis_ok = False

    ready = db_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"db": db_ok, "redis": redis_ok, "ready": ready}
