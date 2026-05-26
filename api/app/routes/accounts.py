"""Account usage endpoint (OpenAI + Anthropic spend/balance)."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import AccountsUsage, ActivityResponse
from app.services import accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/usage", response_model=AccountsUsage)
async def usage() -> AccountsUsage:
    """Return current-month spend and remaining credit for each configured provider."""
    return await accounts.get_usage()


@router.get("/activity", response_model=ActivityResponse)
async def activity() -> ActivityResponse:
    """Return per-model usage from OpenRouter activity (last 30 days)."""
    return await accounts.get_activity()
