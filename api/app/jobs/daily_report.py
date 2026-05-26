"""CronJob entrypoint: render and email the daily top-5 report."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.services import openrouter, ranker
from app.services.kilo import effective_discount
from app.services.mailer import send

# A naive but defensible monthly baseline used for "projected savings":
# 5M input + 5M output tokens at the daily incumbent (Claude Sonnet 4.6).
BASELINE_INPUT_MTOK = 5
BASELINE_OUTPUT_MTOK = 5
BASELINE_MODEL_ID = "anthropic/claude-sonnet-4.6"


def _baseline_cost(in_rate: float, out_rate: float) -> float:
    return (in_rate * BASELINE_INPUT_MTOK) + (out_rate * BASELINE_OUTPUT_MTOK)


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.daily_report")
    settings = get_settings()

    try:
        models = await openrouter.list_models(use_cache=False)
        top5 = ranker.top_n(models, n=5)

        baseline = next((m for m in models if m.id == BASELINE_MODEL_ID), None)
        if baseline is None or not top5:
            savings = 0.0
            assumption = "baseline unavailable"
        else:
            baseline_cost = _baseline_cost(
                baseline.prompt_usd_per_mtok, baseline.completion_usd_per_mtok
            )
            cheapest = top5[0].model
            cheapest_cost = _baseline_cost(
                cheapest.prompt_usd_per_mtok, cheapest.completion_usd_per_mtok
            )
            # Apply Kilo Pass discount at the user's typical streak
            discount = effective_discount("starter", 1, annual=False)
            cheapest_cost *= (1 - discount)
            savings = max(0.0, baseline_cost - cheapest_cost)
            assumption = (
                f"{BASELINE_INPUT_MTOK}M in + {BASELINE_OUTPUT_MTOK}M out "
                f"vs. {baseline.name}, with Kilo Pass (starter, m1)"
            )

        env = Environment(
            loader=FileSystemLoader(Path(__file__).parent.parent / "templates"),
            autoescape=select_autoescape(["html"]),
        )
        tmpl = env.get_template("daily_report.html")
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        html = tmpl.render(
            generated_at=generated_at,
            models=top5,
            projected_monthly_savings_usd=savings,
            baseline_assumption=assumption,
        )
        text = "\n".join(
            [
                f"#{r.rank} {r.model.name} ({r.model.id}) — "
                f"${r.model.prompt_usd_per_mtok:.3f}/"
                f"${r.model.completion_usd_per_mtok:.3f} per Mtok"
                for r in top5
            ]
        )
        subject = f"[Pricing] Top 5 coding models — {generated_at}"
        await send(subject, html, text)
        log.info(
            "daily_report_built",
            top_count=len(top5),
            savings=savings,
            smtp_to=settings.smtp_to,
        )
        return 0
    except Exception as exc:
        log.error("daily_report_failed", error=str(exc), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
