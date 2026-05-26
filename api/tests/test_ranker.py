"""Unit tests for ranker eligibility + ordering."""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas import ModelPricing
from app.services import ranker


def _m(
    mid: str,
    p: float,
    c: float,
    ctx: int = 200_000,
    tools: bool = True,
) -> ModelPricing:
    return ModelPricing(
        id=mid,
        name=mid,
        provider=mid.split("/")[0],
        prompt_usd_per_mtok=p,
        completion_usd_per_mtok=c,
        context_length=ctx,
        supports_tools=tools,
        captured_at=datetime.now(UTC),
    )


def test_excludes_free_models() -> None:
    models = [_m("free/foo", 0, 0), _m("x/y", 0.1, 0.5)]
    ranked = ranker.top_n(models, n=10)
    assert {r.model.id for r in ranked} == {"x/y"}


def test_excludes_models_without_tool_support() -> None:
    models = [_m("a/b", 0.1, 0.5, tools=False), _m("c/d", 0.2, 0.6, tools=True)]
    ranked = ranker.top_n(models, n=10)
    assert {r.model.id for r in ranked} == {"c/d"}


def test_excludes_small_context() -> None:
    models = [_m("a/b", 0.1, 0.5, ctx=8_000), _m("c/d", 0.2, 0.6, ctx=200_000)]
    ranked = ranker.top_n(models, n=10)
    assert {r.model.id for r in ranked} == {"c/d"}


def test_orders_by_blended_cost() -> None:
    models = [
        _m("a/expensive", 5, 25),
        _m("b/cheap", 0.2, 0.8),
        _m("c/mid", 1.0, 3.0),
    ]
    ranked = ranker.top_n(models, n=3)
    assert [r.model.id for r in ranked] == ["b/cheap", "c/mid", "a/expensive"]
    assert ranked[0].rank == 1
