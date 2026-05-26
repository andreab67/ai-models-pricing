"""Liveness + readiness."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db import session_scope
from app.services.cache import cache

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Returns 503 if Postgres or Redis is unreachable."""
    db_ok = True
    redis_ok = True

    try:
        async with session_scope() as session:
            await session.execute(text("select 1"))
    except Exception:
        db_ok = False

    try:
        await cache.set("readyz:probe", 1, ttl=5)
        probe = await cache.get("readyz:probe")
        redis_ok = probe == 1
    except Exception:
        redis_ok = False

    ready = db_ok and redis_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"db": db_ok, "redis": redis_ok, "ready": ready}
