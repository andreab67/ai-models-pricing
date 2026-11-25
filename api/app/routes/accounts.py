"""Account usage endpoint (OpenRouter + Kilo spend/balance)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from app.config import Settings, get_settings
from app.schemas import (
    AccountsUsage,
    ActivityGroupBy,
    ActivityPeriodKey,
    ActivityResponse,
    OpenAIModelsResponse,
    OpenAIProjectsResponse,
    OpenAIProjectUsageResponse,
)
from app.services import accounts, openai_projects

router = APIRouter(prefix="/accounts", tags=["accounts"])
_PRIVATE_HEADERS = {"Cache-Control": "no-store"}


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
    admin_key = _openai_key(settings, admin=True)

    try:
        result = await openai_projects.get_projects(admin_key)
    except openai_projects.OpenAIAccountUnavailable as exc:
        raise HTTPException(502, "OpenAI Projects unavailable", headers=_PRIVATE_HEADERS) from exc

    response.headers.update(_PRIVATE_HEADERS)
    return result


@router.get("/openai-models", response_model=OpenAIModelsResponse)
async def models(
    response: Response, settings: Annotated[Settings, Depends(get_settings)],
) -> OpenAIModelsResponse:
    """Return models accessible with the configured OpenAI project API key."""
    api_key = _openai_key(settings, admin=False)
    try:
        result = await openai_projects.get_models(api_key)
    except openai_projects.OpenAIAccountUnavailable as exc:
        raise HTTPException(502, "OpenAI models unavailable", headers=_PRIVATE_HEADERS) from exc

    response.headers.update(_PRIVATE_HEADERS)
    return result


@router.get("/openai-projects/{project_id}/usage", response_model=OpenAIProjectUsageResponse)
async def project_usage(
    project_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,128}$")],
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpenAIProjectUsageResponse:
    """Return month-to-date completions usage by model and service tier."""
    admin_key = _openai_key(settings, admin=True)
    try:
        result = await openai_projects.get_project_usage(admin_key, project_id)
    except openai_projects.OpenAIAccountUnavailable as exc:
        raise HTTPException(
            502, "OpenAI project usage unavailable", headers=_PRIVATE_HEADERS,
        ) from exc

    response.headers.update(_PRIVATE_HEADERS)
    return result


def _openai_key(settings: Settings, *, admin: bool) -> str:
    if not settings.expose_openai_projects:
        raise HTTPException(404, "Not Found", headers=_PRIVATE_HEADERS)

    key = (settings.openai_admin_key if admin else settings.openai_api_key).strip()
    if not key:
        label = "OpenAI Admin API key" if admin else "OpenAI project API key"
        raise HTTPException(503, f"{label} is not configured", headers=_PRIVATE_HEADERS)
    return key
