"""Exercise the OpenAI projects route against the documented upstream responses."""

from datetime import UTC, datetime

import httpx
import pytest
import respx
from fastapi import FastAPI

from app.config import get_settings
from app.routes.accounts import router
from app.services.cache import Cache

PATH = "/accounts/openai-projects"
UPSTREAM = "https://api.openai.com/v1/organization"


@pytest.fixture
def app():
    instance = FastAPI()
    instance.include_router(router)
    return instance


@pytest.fixture(autouse=True)
def no_redis_network(monkeypatch):
    async def unavailable(_self):
        return None

    monkeypatch.setattr(Cache, "_client_or_none", unavailable)


async def request(app, *, enabled=True, key="test-admin-key"):
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"expose_openai_projects": enabled, "openai_admin_key": key}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(PATH)


def project(project_id, *, created_at=1711471533, **extra):
    return {"id": project_id, "created_at": created_at, **extra}


def page(*rows, has_more=False, **extra):
    return {"data": rows, "has_more": has_more, **extra}


def cost(project_id, value):
    return {"project_id": project_id, "amount": {"value": value, "currency": "usd"}}


async def test_openai_projects_are_disabled_by_default(app):
    with respx.mock() as mock:
        response = await request(app, enabled=False)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert not mock.calls


async def test_openai_projects_require_an_admin_key(app):
    with respx.mock() as mock:
        response = await request(app, key=" ")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert not mock.calls


async def test_projects_join_paginated_utc_month_to_date_costs_and_cache(app):
    with respx.mock() as mock:
        mock.get(
            f"{UPSTREAM}/projects",
            params={"limit": "100", "include_archived": "false", "after": "proj_first"},
        ).respond(200, json=page(
            project("proj_recent", created_at=1711471534, name="Recent", residency="GLOBAL"),
            project("proj_archived", status="archived"),
        ))
        first = mock.get(
            f"{UPSTREAM}/projects", params={"limit": "100", "include_archived": "false"}
        ).respond(200, json=page(project("proj_first"), has_more=True, last_id="proj_first"))
        base_costs = mock.get(f"{UPSTREAM}/costs")

        def respond_to_costs(outgoing):
            assert outgoing.url.params.get_list("group_by") == ["project_id"]
            assert outgoing.url.params["bucket_width"] == "1d"
            assert outgoing.url.params["limit"] == "31"
            start = datetime.fromtimestamp(int(outgoing.url.params["start_time"]), UTC)
            end = datetime.fromtimestamp(int(outgoing.url.params["end_time"]), UTC)
            assert start == end.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0,
            )
            match outgoing.url.params.get("page"):
                case None:
                    return httpx.Response(200, json=page(
                        {"results": [cost("proj_recent", 0.5), cost(None, 40)]},
                        has_more=True, next_page="cost_cursor",
                    ))
                case "cost_cursor":
                    return httpx.Response(200, json=page({"results": [cost("proj_recent", 0.25)]}))
                case unexpected:
                    pytest.fail(f"Unexpected cost cursor {unexpected}")

        base_costs.side_effect = respond_to_costs
        response = await request(app, key="test-admin-key-pagination")
        assert response.status_code == 200, response.text
        assert (await request(app, key="test-admin-key-pagination")).json() == response.json()
        assert len(mock.calls) == 4

    assert first.calls.last.request.headers["authorization"] == "Bearer test-admin-key-pagination"
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["spend_available"] is True
    assert result["period_start"] == datetime.now(UTC).replace(day=1).date().isoformat()
    assert result["projects"] == [
        {
            "id": "proj_recent", "name": "Recent", "residency": "GLOBAL",
            "created_at": "2024-03-26T16:45:34Z", "spend_usd": 0.75,
        },
        {
            "id": "proj_first", "name": None, "residency": None,
            "created_at": "2024-03-26T16:45:33Z", "spend_usd": 0.0,
        },
    ]


async def test_invalid_cost_response_keeps_projects_without_claiming_zero(app):
    with respx.mock() as mock:
        mock.get(f"{UPSTREAM}/projects").respond(200, json=page(project("proj_first")))
        mock.get(f"{UPSTREAM}/costs").respond(
            200, json=page({"results": [cost("proj_first", "not-a-number")]}),
        )
        response = await request(app, key="test-admin-key-bad-costs")

    assert response.status_code == 200, response.text
    assert response.json()["spend_available"] is False
    assert response.json()["projects"][0]["spend_usd"] is None


@pytest.mark.parametrize("status,body", [
    (401, {"error": "upstream private details"}),
    (200, page(project("proj_first"), has_more=True)),
])
async def test_project_failure_is_generic_and_never_returns_partial_projects(app, status, body):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{UPSTREAM}/projects").respond(status, json=body)
        mock.get(f"{UPSTREAM}/costs").respond(200, json=page())
        response = await request(app)
    assert response.status_code == 502
    assert response.json() == {"detail": "OpenAI Projects unavailable"}
    assert response.headers["cache-control"] == "no-store"
