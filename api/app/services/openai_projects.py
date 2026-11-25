"""Read active organization projects and their current UTC month's costs."""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field, FiniteFloat, ValidationError

from app.logging import get_logger
from app.schemas import OpenAIProject, OpenAIProjectsResponse
from app.services.cache import cache

log = get_logger(__name__)

_ORGANIZATION_URL = "https://api.openai.com/v1/organization/"
_PROJECT_PAGE_SIZE = 100
_MAX_PROJECT_PAGES = 50
_MAX_DAYS_IN_MONTH = 31
_UPSTREAM_TIMEOUT_SECONDS = 6
_CACHE_TTL_SECONDS = 300
_MAX_TIMESTAMP = 253_402_300_799  # Last whole second representable by datetime.


class OpenAIProjectsUnavailable(Exception):
    """The upstream project list could not be read in full."""


class _InvalidPage(ValueError):
    """An upstream page cannot be processed without risking a partial result."""


class _Project(BaseModel):
    id: str = Field(min_length=1)
    created_at: int = Field(strict=True, ge=0, le=_MAX_TIMESTAMP)
    name: str | None = None
    residency: str | None = None
    status: Literal["active", "archived"] | None = None


class _CostAmount(BaseModel):
    value: FiniteFloat = Field(strict=True)
    currency: Literal["usd"]


class _Cost(BaseModel):
    project_id: str | None = None
    amount: _CostAmount


class _CostBucket(BaseModel):
    results: list[_Cost]


class _Page[T](BaseModel):
    data: list[T]
    has_more: bool = Field(strict=True)
    last_id: str | None = None
    next_page: str | None = None


async def _project_list(client: httpx.AsyncClient) -> list[_Project]:
    params: dict[str, str | int] = {"limit": _PROJECT_PAGE_SIZE, "include_archived": "false"}
    projects: dict[str, _Project] = {}
    seen_cursors: set[str] = set()

    for _ in range(_MAX_PROJECT_PAGES):
        response = await client.get("projects", params=params)
        response.raise_for_status()
        page = _Page[_Project].model_validate_json(response.content)
        projects.update((row.id, row) for row in page.data if row.status != "archived")
        if not page.has_more:
            return sorted(projects.values(), key=lambda row: (-row.created_at, row.id))
        cursor = page.last_id
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        params["after"] = cursor

    raise _InvalidPage("Invalid OpenAI Projects pagination")


async def _project_costs(
    client: httpx.AsyncClient, month_start: datetime, now: datetime
) -> dict[str, float]:
    # end_time is exclusive. An empty interval can only occur in the first
    # whole second of a new month, when there is no spend to query yet.
    start = int(month_start.timestamp())
    end = int(now.timestamp())
    costs: dict[str, float] = {}
    if start == end:
        return costs

    params: dict[str, str | int] = {
        "start_time": start,
        "end_time": end,
        "group_by": "project_id",
        "bucket_width": "1d",
        "limit": _MAX_DAYS_IN_MONTH,
    }
    seen_cursors: set[str] = set()

    for _ in range(_MAX_DAYS_IN_MONTH):
        response = await client.get("costs", params=params)
        response.raise_for_status()
        page = _Page[_CostBucket].model_validate_json(response.content)
        for bucket in page.data:
            for cost in bucket.results:
                if cost.project_id is not None:
                    total = costs.get(cost.project_id, 0.0) + cost.amount.value
                    if not math.isfinite(total):
                        raise _InvalidPage("OpenAI project costs overflowed")
                    costs[cost.project_id] = total
        if not page.has_more:
            return costs
        cursor = page.next_page
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        params["page"] = cursor

    raise _InvalidPage("Invalid OpenAI Costs pagination")


_UPSTREAM_ERRORS = (httpx.HTTPError, ValidationError, _InvalidPage, TimeoutError)


async def get_projects(admin_key: str) -> OpenAIProjectsResponse:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # A deployment that changes credentials must not serve the old org's cache.
    key_digest = hashlib.sha256(admin_key.encode()).hexdigest()
    cache_key = f"accounts:openai-projects:{key_digest}"
    cached = await cache.get(cache_key)
    if cached is not None:
        try:
            snapshot = OpenAIProjectsResponse.model_validate(cached)
            if snapshot.period_start == month_start.date():
                return snapshot
        except ValidationError:
            log.warning("openai_projects_cache_invalid")

    async with httpx.AsyncClient(
        base_url=_ORGANIZATION_URL,
        headers={"Authorization": f"Bearer {admin_key}"},
    ) as client:
        try:
            async with asyncio.timeout(_UPSTREAM_TIMEOUT_SECONDS):
                projects = await _project_list(client)
        except _UPSTREAM_ERRORS as exc:
            log.warning("openai_projects_unavailable", error_type=type(exc).__name__)
            raise OpenAIProjectsUnavailable from exc

        try:
            async with asyncio.timeout(_UPSTREAM_TIMEOUT_SECONDS):
                costs = await _project_costs(client, month_start, now) if projects else {}
        except _UPSTREAM_ERRORS as exc:
            log.warning("openai_project_costs_unavailable", error_type=type(exc).__name__)
            costs = None

    result = OpenAIProjectsResponse(
        projects=[
            OpenAIProject(
                id=project.id,
                name=project.name,
                residency=project.residency,
                created_at=datetime.fromtimestamp(project.created_at, UTC),
                spend_usd=costs.get(project.id, 0.0) if costs is not None else None,
            )
            for project in projects
        ],
        period_start=month_start.date(),
        spend_available=costs is not None,
    )
    if result.spend_available:
        await cache.set(cache_key, result.model_dump(mode="json"), ttl=_CACHE_TTL_SECONDS)
    return result
