"""CronJob entrypoint: refresh OpenRouter pricing snapshot."""

from __future__ import annotations

import asyncio
import sys

from app.logging import configure_logging, get_logger
from app.services.cache import cache
from app.services.openrouter import refresh_pricing


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.refresh_pricing")
    try:
        models = await refresh_pricing(persist=True)
        log.info("refresh_pricing_done", count=len(models))
        return 0
    except Exception as exc:
        log.error("refresh_pricing_failed", error=str(exc), exc_info=True)
        return 1
    finally:
        await cache.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
