"""Read the available OpenAI models, organization projects, and project activity."""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field, FiniteFloat, ValidationError

from app.logging import get_logger
from app.schemas import (
    OpenAIModelsResponse,
    OpenAIModelUsage,
    OpenAIProject,
    OpenAIProjectsResponse,
    OpenAIProjectUsageResponse,
)
from app.services.cache import cache

log = get_logger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/"
_ORGANIZATION_URL = f"{_OPENAI_URL}organization/"
_PROJECT_PAGE_SIZE = 100
_MAX_PROJECT_PAGES = 50
_MAX_DAYS_IN_MONTH = 31
_UPSTREAM_TIMEOUT_SECONDS = 6
_CACHE_TTL_SECONDS = 300
_MAX_TIMESTAMP = 253_402_300_799  # Last whole second representable by datetime.


class OpenAIAccountUnavailable(Exception):
    """The upstream account data could not be read in full."""


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


class _Model(BaseModel):
    id: str = Field(min_length=1)


class _ModelList(BaseModel):
    data: list[_Model]


class _Usage(BaseModel):
    project_id: str
    model: str | None = None
    service_tier: str | None = None
    num_model_requests: int = Field(strict=True, ge=0)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)


class _UsageBucket(BaseModel):
    results: list[_Usage]


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
) -> dict[str | None, float]:
    # end_time is exclusive. An empty interval can only occur in the first
    # whole second of a new month, when there is no spend to query yet.
    start = int(month_start.timestamp())
    end = int(now.timestamp())
    costs: dict[str | None, float] = {}
    if start == end:
        return costs

    params: dict[str, str | int] = {
        "start_time": start,
        "end_time": end,
        "group_by[]": "project_id",
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


async def get_models(api_key: str) -> OpenAIModelsResponse:
    key_digest = hashlib.sha256(api_key.encode()).hexdigest()
    cache_key = f"accounts:openai-models:{key_digest}"
    cached = await cache.get(cache_key)
    if cached is not None:
        try:
            return OpenAIModelsResponse.model_validate(cached)
        except ValidationError:
            log.warning("openai_models_cache_invalid")

    try:
        async with (
            httpx.AsyncClient(
                base_url=_OPENAI_URL, headers={"Authorization": f"Bearer {api_key}"},
            ) as client,
            asyncio.timeout(_UPSTREAM_TIMEOUT_SECONDS),
        ):
            response = await client.get("models")
            response.raise_for_status()
            models = _ModelList.model_validate_json(response.content)
    except _UPSTREAM_ERRORS as exc:
        log.warning("openai_models_unavailable", error_type=type(exc).__name__)
        raise OpenAIAccountUnavailable from exc

    result = OpenAIModelsResponse(models=sorted({model.id for model in models.data}))
    await cache.set(cache_key, result.model_dump(mode="json"), ttl=_CACHE_TTL_SECONDS)
    return result


async def _project_usage(
    client: httpx.AsyncClient, project_id: str, start: int, end: int,
) -> list[OpenAIModelUsage]:
    # OpenAI's Python SDK serializes array filters as repeated bracketed keys.
    params: dict[str, str | int | list[str]] = {
        "start_time": start,
        "end_time": end,
        "bucket_width": "1d",
        "limit": _MAX_DAYS_IN_MONTH,
        "project_ids[]": [project_id],
        "group_by[]": ["project_id", "model", "service_tier"],
    }
    totals: dict[tuple[str | None, str | None], OpenAIModelUsage] = {}
    seen_cursors: set[str] = set()

    for _ in range(_MAX_DAYS_IN_MONTH):
        response = await client.get("usage/completions", params=params)
        response.raise_for_status()
        page = _Page[_UsageBucket].model_validate_json(response.content)
        for bucket in page.data:
            for usage in bucket.results:
                if usage.project_id != project_id:
                    raise _InvalidPage("Unexpected project in OpenAI usage results")
                key = (usage.model, usage.service_tier)
                row = totals.get(key)
                if row is None:
                    totals[key] = OpenAIModelUsage(
                        model=usage.model,
                        service_tier=usage.service_tier,
                        requests=usage.num_model_requests,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )
                else:
                    row.requests += usage.num_model_requests
                    row.input_tokens += usage.input_tokens
                    row.output_tokens += usage.output_tokens
        if not page.has_more:
            return sorted(
                totals.values(),
                key=lambda row: (-row.requests, row.model or "", row.service_tier or ""),
            )
        cursor = page.next_page
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        params["page"] = cursor

    raise _InvalidPage("Invalid OpenAI usage pagination")


async def get_project_usage(admin_key: str, project_id: str) -> OpenAIProjectUsageResponse:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start, end = int(month_start.timestamp()), int(now.timestamp())
    if start == end:
        return OpenAIProjectUsageResponse(period_start=month_start.date(), rows=[])

    try:
        async with (
            httpx.AsyncClient(
                base_url=_ORGANIZATION_URL, headers={"Authorization": f"Bearer {admin_key}"},
            ) as client,
            asyncio.timeout(_UPSTREAM_TIMEOUT_SECONDS),
        ):
            rows = await _project_usage(client, project_id, start, end)
    except _UPSTREAM_ERRORS as exc:
        log.warning("openai_project_usage_unavailable", error_type=type(exc).__name__)
        raise OpenAIAccountUnavailable from exc

    return OpenAIProjectUsageResponse(period_start=month_start.date(), rows=rows)


async def get_projects(admin_key: str) -> OpenAIProjectsResponse:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # A deployment that changes credentials must not serve the old org's cache.
    key_digest = hashlib.sha256(admin_key.encode()).hexdigest()
    cache_key = f"accounts:openai-projects:v2:{key_digest}"
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
            raise OpenAIAccountUnavailable from exc

        try:
            async with asyncio.timeout(_UPSTREAM_TIMEOUT_SECONDS):
                costs = await _project_costs(client, month_start, now)
            total_spend = math.fsum(costs.values())
        except (*_UPSTREAM_ERRORS, OverflowError) as exc:
            log.warning("openai_project_costs_unavailable", error_type=type(exc).__name__)
            costs = None
            total_spend = None

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
        total_spend_usd=total_spend,
    )
    if result.spend_available:
        await cache.set(cache_key, result.model_dump(mode="json"), ttl=_CACHE_TTL_SECONDS)
    return result
