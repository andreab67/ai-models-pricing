"""Rank models for coding workloads."""

from __future__ import annotations

from app.config import get_settings
from app.schemas import ModelPricing, RankedModel

_settings = get_settings()


def _blended(model: ModelPricing) -> float:
    """Weighted cost blend: coding is output-heavy."""
    return (
        _settings.rank_input_weight * model.prompt_usd_per_mtok
        + _settings.rank_output_weight * model.completion_usd_per_mtok
    )


def _eligible(model: ModelPricing) -> bool:
    if model.prompt_usd_per_mtok == 0 and model.completion_usd_per_mtok == 0:
        # "Free" models — exclude from cost ranking; they aren't comparable
        return False
    if model.prompt_usd_per_mtok > _settings.rank_max_input_price:
        return False
    if model.completion_usd_per_mtok > _settings.rank_max_output_price:
        return False
    if not model.supports_tools:
        return False
    if (model.context_length or 0) < _settings.rank_min_context_tokens:
        return False
    return True


def top_n(models: list[ModelPricing], n: int | None = None) -> list[RankedModel]:
    n = n or _settings.rank_top_n
    eligible = [m for m in models if _eligible(m)]
    scored = sorted(eligible, key=_blended)
    ranked = []
    for i, m in enumerate(scored[:n], start=1):
        blended = _blended(m)
        # invert cost into a 0..100 score so higher = better
        score = max(0.0, 100.0 - blended)
        ranked.append(
            RankedModel(
                model=m,
                score=round(score, 2),
                blended_usd_per_mtok=round(blended, 4),
                rank=i,
            )
        )
    return ranked
