"""Account usage endpoint (OpenRouter + Kilo spend/balance)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import Settings, get_settings
from app.schemas import (
    AccountsUsage,
    ActivityGroupBy,
    ActivityPeriodKey,
    ActivityResponse,
    OpenAIProjectsResponse,
)
from app.services import accounts, openai_projects

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/usage", response_model=AccountsUsage)
async def usage() -> AccountsUsage:
    """Return current-month spend and remaining credit for each configured provider."""
    return await accounts.get_usage()


@router.get("/activity", response_model=ActivityResponse)
async def activity(
    period: ActivityPeriodKey = "today",
    group_by: ActivityGroupBy = "model",
) -> ActivityResponse:
    """Return OpenRouter usage for a window in America/Denver local time.

    ``period`` is ``today`` (local midnight to now), ``7d`` or ``30d`` (the last
    7 / 30 local days including today). The window always ends at "now", so
    the current day is partial. ``group_by`` splits rows by model, API key or app.
    Credit charges, upstream BYOK usage and their combined total are reported
    separately.
    """
    return await accounts.get_activity(period, group_by)


@router.get("/openai-projects", response_model=OpenAIProjectsResponse)
async def projects(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> OpenAIProjectsResponse:
    """Return active OpenAI projects and month-to-date spend in UTC."""
    headers = {"Cache-Control": "no-store"}
    if not settings.expose_openai_projects:
        raise HTTPException(404, "Not Found", headers=headers)

    admin_key = settings.openai_admin_key.strip()
    if not admin_key:
        raise HTTPException(503, "OpenAI Admin API key is not configured", headers=headers)

    try:
        result = await openai_projects.get_projects(admin_key)
    except openai_projects.OpenAIProjectsUnavailable as exc:
        raise HTTPException(502, "OpenAI Projects unavailable", headers=headers) from exc

    response.headers.update(headers)
    return result
