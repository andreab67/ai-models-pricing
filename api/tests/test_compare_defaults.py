"""/compare defaults to the configured tier at the steady-state streak."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import compare as compare_routes
from app.schemas import ModelPricing
from app.services import kilo


def _model() -> ModelPricing:
    return ModelPricing(
        id="x/y",
        name="X Y",
        provider="x",
        prompt_usd_per_mtok=3.0,
        completion_usd_per_mtok=15.0,
        captured_at=datetime.now(UTC),
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _get_model(model_id: str) -> ModelPricing | None:
        return _model() if model_id == "x/y" else None

    monkeypatch.setattr(compare_routes.openrouter, "get_model", _get_model)
    return TestClient(app)


def _kilo_pass(body: dict) -> dict:
    return next(c for c in body["channels"] if c["channel"] == "kilo_pass")


def test_defaults_use_configured_tier_at_steady_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compare_routes.get_settings(), "kilo_tier", "expert")
    steady = kilo.steady_state_streak(kilo.load_bonus_growth())

    resp = client.get("/compare/x/y")

    assert resp.status_code == 200
    notes = _kilo_pass(resp.json())["notes"]
    assert notes.startswith(f"tier=expert, month {steady},")
    # Steady state is the capped bonus, never the one-off month-1 welcome bonus.
    assert steady > 1
    expected = round(3.0 * (1 - kilo.effective_discount("expert", steady)), 4)
    assert _kilo_pass(resp.json())["prompt_usd_per_mtok"] == expected


def test_explicit_assumptions_still_win(client: TestClient) -> None:
    resp = client.get("/compare/x/y?kilo_tier=pro&kilo_streak_months=1")

    assert resp.status_code == 200
    assert _kilo_pass(resp.json())["notes"].startswith("tier=pro, month 1,")


def test_invalid_tier_is_422(client: TestClient) -> None:
    assert client.get("/compare/x/y?kilo_tier=enterprise").status_code == 422
