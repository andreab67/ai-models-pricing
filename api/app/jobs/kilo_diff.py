"""CronJob entrypoint: alert when kilo.ai/pricing changes.

The last seen page hash is stored in Postgres (``kilo_plan_snapshot``), not
Redis: the cache silently falls back to process memory when Redis is down,
which would make every run look like a first run and never alert. When the
hash changes, one row per tier is written with the new hash, and a short
notice is emailed so kilo_plans.yaml gets refreshed.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.db import engine, session_scope
from app.logging import configure_logging, get_logger
from app.models import KiloPlanSnapshot
from app.services.kilo import fetch_pricing_hash, load_plans
from app.services.mailer import send


async def last_known_hash() -> str | None:
    async with session_scope() as session:
        return await session.scalar(
            select(KiloPlanSnapshot.source_hash)
            .order_by(KiloPlanSnapshot.captured_at.desc(), KiloPlanSnapshot.id.desc())
            .limit(1)
        )


async def record_hash(new_hash: str) -> None:
    """Persist the current plan table under the new page hash."""
    plans = load_plans()
    async with session_scope() as session:
        session.add_all(
            KiloPlanSnapshot(
                tier=p.tier,
                monthly_usd=p.monthly_usd,
                paid_credits_usd=p.paid_credits_usd,
                max_bonus_pct=p.max_bonus_pct,
                source_hash=new_hash,
            )
            for p in plans
        )


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.kilo_diff")

    try:
        new_hash, _ = await fetch_pricing_hash()
        last_hash = await last_known_hash()

        if last_hash == new_hash:
            log.info("kilo_pricing_unchanged", hash=new_hash)
            return 0

        if last_hash is None:
            log.info("kilo_pricing_baseline_recorded", hash=new_hash)
        else:
            log.warning("kilo_pricing_changed", old=last_hash, new=new_hash)
            subject = "[Pricing] Kilo Code pricing page changed"
            html = (
                f"<p>kilo.ai/pricing content hash changed.</p>"
                f"<p><strong>Old:</strong> {last_hash}<br>"
                f"<strong>New:</strong> {new_hash}</p>"
                f"<p>Refresh <code>api/app/data/kilo_plans.yaml</code>.</p>"
            )
            delivered = await send(
                subject, html, "Kilo pricing page changed — refresh kilo_plans.yaml"
            )
            if not delivered:
                # Keep the old baseline so the change is reported once mail works,
                # instead of recording it and losing the alert for good.
                raise RuntimeError("pricing change alert not delivered (SMTP not configured)")

        # Record only after the alert was delivered, so a failed or skipped
        # send is retried on the next run instead of being swallowed.
        await record_hash(new_hash)
        return 0
    except Exception as exc:
        log.error("kilo_diff_failed", error=str(exc), exc_info=True)
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
