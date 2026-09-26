"""Regression tests for the Kilo fixes ported from the GitHub review."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.jobs import kilo_diff
from app.main import app
from app.schemas import KiloPlan
from app.services import kilo


def test_plan_cap_is_honoured() -> None:
    growth = {"welcome_pct": 0.5, "step_pct": 0.05, "cap_pct": 0.40}
    assert kilo.monthly_bonus_pct(12, growth) == pytest.approx(0.40)
    assert kilo.monthly_bonus_pct(12, growth, plan_cap_pct=0.25) == pytest.approx(0.25)
    # A plan cap above the global cap cannot raise it.
    assert kilo.monthly_bonus_pct(12, growth, plan_cap_pct=0.90) == pytest.approx(0.40)
    # The month-1 welcome bonus is not capped by the plan's monthly cap.
    assert kilo.monthly_bonus_pct(1, growth, plan_cap_pct=0.25) == pytest.approx(0.5)


def test_steady_state_streak_is_cap_month() -> None:
    assert kilo.steady_state_streak({"step_pct": 0.05, "cap_pct": 0.40}) == 8


def test_projection_uses_plan_values() -> None:
    proj = kilo.project("pro", 8)
    assert proj.bonus_pct == pytest.approx(0.40)
    assert proj.total_effective_credits_usd == pytest.approx(49 * 1.4)


def test_compare_rejects_unknown_tier_with_422() -> None:
    client = TestClient(app)
    assert client.get("/compare/x/y", params={"kilo_tier": "enterprise"}).status_code == 422


def test_projection_rejects_unknown_tier_with_422() -> None:
    client = TestClient(app)
    assert client.get("/kilo/projection", params={"tier": "basic"}).status_code == 422


def test_kilo_tier_is_case_insensitive() -> None:
    from app.config import Settings

    assert Settings(kilo_tier="Pro").kilo_tier == "pro"
    with pytest.raises(ValueError):
        Settings(kilo_tier="enterprise")


async def _run_kilo_diff(
    monkeypatch: pytest.MonkeyPatch,
    last: str | None,
    new: str,
    committed: list[KiloPlan] | None = None,
) -> tuple[int, list[str], list[tuple[str, object]]]:
    handled: list[str] = []
    recorded: list[tuple[str, object]] = []

    async def _fetch() -> tuple[str, str]:
        return new, "text"

    async def _last() -> str | None:
        return last

    async def _record(h: str, plans: object = None) -> None:
        recorded.append((h, plans))

    async def _handle(old: str, new_hash: str, page_text: str) -> list[KiloPlan] | None:
        handled.append(new_hash)
        return committed

    class _Closeable:
        async def close(self) -> None:
            return None

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(kilo_diff, "fetch_pricing_hash", _fetch)
    monkeypatch.setattr(kilo_diff, "last_known_hash", _last)
    monkeypatch.setattr(kilo_diff, "record_hash", _record)
    monkeypatch.setattr(kilo_diff, "_handle_change", _handle)
    monkeypatch.setattr(kilo_diff, "cache", _Closeable())
    monkeypatch.setattr(kilo_diff, "engine", _Closeable())
    rc = await kilo_diff._main()
    return rc, handled, recorded


async def test_kilo_diff_handles_change_then_records(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, handled, recorded = await _run_kilo_diff(monkeypatch, last="old", new="new")
    assert rc == 0
    assert handled == ["new"]
    assert recorded == [("new", None)]


async def test_kilo_diff_first_run_records_baseline_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc, handled, recorded = await _run_kilo_diff(monkeypatch, last=None, new="h1")
    assert (rc, handled, recorded) == (0, [], [("h1", None)])


async def test_kilo_diff_unchanged_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, handled, recorded = await _run_kilo_diff(monkeypatch, last="same", new="same")
    assert (rc, handled, recorded) == (0, [], [])


async def test_kilo_diff_does_not_record_when_handling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(old: str, new_hash: str, page_text: str) -> None:
        raise RuntimeError("gitlab commit failed")

    recorded: list[str] = []

    async def _record(h: str, plans: object = None) -> None:
        recorded.append(h)

    async def _fetch() -> tuple[str, str]:
        return "new", "text"

    async def _last() -> str:
        return "old"

    class _Closeable:
        async def close(self) -> None:
            return None

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(kilo_diff, "fetch_pricing_hash", _fetch)
    monkeypatch.setattr(kilo_diff, "last_known_hash", _last)
    monkeypatch.setattr(kilo_diff, "record_hash", _record)
    monkeypatch.setattr(kilo_diff, "_handle_change", _boom)
    monkeypatch.setattr(kilo_diff, "cache", _Closeable())
    monkeypatch.setattr(kilo_diff, "engine", _Closeable())
    assert await kilo_diff._main() == 1
    assert recorded == []
