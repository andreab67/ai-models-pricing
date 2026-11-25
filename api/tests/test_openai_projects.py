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


async def request(app, *, enabled=True, key="test-admin-key", model_key="", path=PATH):
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={
            "expose_openai_projects": enabled,
            "openai_admin_key": key,
            "openai_api_key": model_key,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


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
            assert outgoing.url.params.get_list("group_by[]") == ["project_id"]
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
                    return httpx.Response(200, json=page({"results": [
                        cost("proj_recent", 0.25), cost("proj_archived", 3.25),
                    ]}))
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
    assert result["total_spend_usd"] == 44.0
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
    assert response.json()["total_spend_usd"] is None
    assert response.json()["projects"][0]["spend_usd"] is None


async def test_organization_costs_are_available_without_active_projects(app):
    with respx.mock() as mock:
        mock.get(f"{UPSTREAM}/projects").respond(200, json=page())
        mock.get(f"{UPSTREAM}/costs").respond(
            200, json=page({"results": [cost("proj_archived", 2.5), cost(None, -0.5)]}),
        )
        response = await request(app, key="test-admin-key-no-active-projects")

    assert response.status_code == 200, response.text
    assert response.json()["projects"] == []
    assert response.json()["total_spend_usd"] == 2.0


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


async def test_model_catalog_uses_project_key_and_returns_model_ids(app):
    with respx.mock() as mock:
        models = mock.get("https://api.openai.com/v1/models").respond(200, json={
            "data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-a"}],
        })
        response = await request(app, model_key="test-model-key", path="/accounts/openai-models")

    assert response.status_code == 200, response.text
    assert response.json() == {"models": ["model-a", "model-b"]}
    assert models.calls.last.request.headers["authorization"] == "Bearer test-model-key"
    assert response.headers["cache-control"] == "no-store"


async def test_project_usage_aggregates_pages_by_model_and_service_tier(app):
    def usage(tier, requests):
        return {
            "project_id": "proj_basic", "model": "model-a", "service_tier": tier,
            "num_model_requests": requests, "input_tokens": 10, "output_tokens": 4,
        }

    def respond(outgoing):
        params = outgoing.url.params
        assert params.get_list("project_ids[]") == ["proj_basic"]
        assert params.get_list("group_by[]") == ["project_id", "model", "service_tier"]
        start = datetime.fromtimestamp(int(params["start_time"]), UTC)
        end = datetime.fromtimestamp(int(params["end_time"]), UTC)
        assert start == end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if params.get("page") == "more":
            return httpx.Response(200, json=page({"results": [usage("flex", 3), usage(None, 1)]}))
        return httpx.Response(200, json=page(
            {"results": [usage("flex", 4), usage("default", 2)]},
            has_more=True, next_page="more",
        ))

    with respx.mock() as mock:
        calls = mock.get(f"{UPSTREAM}/usage/completions").mock(side_effect=respond)
        response = await request(app, path=f"{PATH}/proj_basic/usage")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert calls.call_count == 2
    assert calls.calls.last.request.headers["authorization"] == "Bearer test-admin-key"
    assert response.json()["rows"] == [
        {"model": "model-a", "service_tier": "flex", "requests": 7, "input_tokens": 20,
         "output_tokens": 8},
        {"model": "model-a", "service_tier": "default", "requests": 2, "input_tokens": 10,
         "output_tokens": 4},
        {"model": "model-a", "service_tier": None, "requests": 1, "input_tokens": 10,
         "output_tokens": 4},
    ]


@pytest.mark.parametrize("path", ["/accounts/openai-models", f"{PATH}/proj_basic/usage"])
async def test_new_openai_endpoints_require_opt_in_and_credentials(app, path):
    with respx.mock() as mock:
        disabled = await request(app, enabled=False, model_key="test-model-key", path=path)
        missing = await request(app, key="", model_key="", path=path)

    assert disabled.status_code == 404
    assert missing.status_code == 503
    assert disabled.headers["cache-control"] == missing.headers["cache-control"] == "no-store"
    assert not mock.calls


async def test_project_usage_rejects_rows_from_a_different_project(app):
    with respx.mock() as mock:
        mock.get(f"{UPSTREAM}/usage/completions").respond(200, json=page({"results": [{
            "project_id": "proj_other", "model": "model-a", "service_tier": "flex",
            "num_model_requests": 9, "input_tokens": 10, "output_tokens": 4,
        }]}))
        response = await request(app, path=f"{PATH}/proj_basic/usage")

    assert response.status_code == 502
    assert response.json() == {"detail": "OpenAI project usage unavailable"}
    assert response.headers["cache-control"] == "no-store"
