"""Account usage endpoint (OpenRouter + Kilo spend/balance)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import AccountsUsage, ActivityGroupBy, ActivityPeriodKey, ActivityResponse
from app.services import accounts

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
