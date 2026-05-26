"""CronJob entrypoint: alert when kilo.ai/pricing changes.

Stores the last hash in Redis. If the new hash differs from the last,
emails a short notice so we know to refresh kilo_plans.yaml.
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.services.cache import cache
from app.services.kilo import fetch_pricing_hash
from app.services.mailer import send

LAST_HASH_KEY = "kilo:pricing:last_hash"


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.kilo_diff")
    get_settings()

    try:
        new_hash, _ = await fetch_pricing_hash()
        last_hash = await cache.get(LAST_HASH_KEY)

        if last_hash and last_hash != new_hash:
            log.warning("kilo_pricing_changed", old=last_hash, new=new_hash)
            subject = "[Pricing] Kilo Code pricing page changed"
            html = (
                f"<p>kilo.ai/pricing content hash changed.</p>"
                f"<p><strong>Old:</strong> {last_hash}<br>"
                f"<strong>New:</strong> {new_hash}</p>"
                f"<p>Refresh <code>api/app/data/kilo_plans.yaml</code>.</p>"
            )
            await send(subject, html, "Kilo pricing page changed — refresh kilo_plans.yaml")
        else:
            log.info(
                "kilo_pricing_unchanged",
                hash=new_hash,
                first_run=last_hash is None,
            )

        await cache.set(LAST_HASH_KEY, new_hash, ttl=60 * 60 * 24 * 30)
        return 0
    except Exception as exc:
        log.error("kilo_diff_failed", error=str(exc), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
