"""CronJob entrypoint: keep kilo_plans.yaml in sync with kilo.ai/pricing.

Stores the last page hash in Redis. On a hash change: extracts the tier
figures via an LLM, sanity-checks them against the current yaml, and — if
they pass and actually differ — commits the update straight to main via the
GitLab API. GitLab CI then builds/deploys as normal. No human review step;
an implausible extraction just falls back to the old "please check manually"
email instead of being committed.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.services import kilo, kilo_extract
from app.services.cache import cache
from app.services.gitlab_commit import commit_file
from app.services.kilo import fetch_pricing_hash
from app.services.mailer import send

LAST_HASH_KEY = "kilo:pricing:last_hash"
KILO_PLANS_REPO_PATH = "api/app/data/kilo_plans.yaml"


async def _handle_change(old_hash: str, new_hash: str, page_text: str) -> None:
    log = get_logger("jobs.kilo_diff")
    current = kilo.load_raw()

    try:
        extracted = await kilo_extract.extract_pricing(page_text)
    except Exception as exc:
        log.error("kilo_extraction_failed", error=str(exc), exc_info=True)
        await _send_manual_review_email(old_hash, new_hash, reason=f"extraction failed: {exc}")
        return

    problems = kilo_extract.sanity_check(current, extracted)
    if problems:
        log.warning("kilo_extraction_rejected", old=old_hash, new=new_hash, problems=problems)
        await _send_manual_review_email(old_hash, new_hash, reason="; ".join(problems))
        return

    diff = kilo_extract.diff_from_current(current, extracted)
    if diff is None:
        log.info("kilo_pricing_hash_noise", old=old_hash, new=new_hash)
        return

    verified_date = date.today().isoformat()
    rendered = kilo_extract.render_kilo_plans_yaml(extracted, verified_date)
    commit_message = f"chore(kilo): auto-update pricing ({verified_date})\n\n{diff}"
    commit_url = await commit_file(KILO_PLANS_REPO_PATH, rendered, commit_message)

    log.warning("kilo_pricing_auto_committed", diff=diff, commit_url=commit_url)
    await _send_auto_update_email(diff, commit_url)


async def _send_manual_review_email(old_hash: str, new_hash: str, reason: str) -> None:
    subject = "[Pricing] Kilo Code pricing page changed — needs manual review"
    html = (
        f"<p>kilo.ai/pricing content hash changed, but the automated extraction "
        f"couldn't be trusted:</p>"
        f"<p><strong>Reason:</strong> {reason}</p>"
        f"<p><strong>Old hash:</strong> {old_hash}<br>"
        f"<strong>New hash:</strong> {new_hash}</p>"
        f"<p>Please check https://kilo.ai/pricing and update "
        f"<code>{KILO_PLANS_REPO_PATH}</code> manually.</p>"
    )
    await send(subject, html, f"Kilo pricing changed but needs manual review: {reason}")


async def _send_auto_update_email(diff: dict, commit_url: str) -> None:
    subject = "[Pricing] Kilo Code pricing auto-updated"
    diff_html = "<br>".join(f"{k}: {v}" for k, v in diff.items())
    html = (
        f"<p>kilo_plans.yaml was auto-updated from the live kilo.ai/pricing page.</p>"
        f"<p><strong>Changes:</strong><br>{diff_html}</p>"
        f'<p><a href="{commit_url}">{commit_url}</a></p>'
        f"<p>No action needed — this is an FYI audit trail.</p>"
    )
    await send(subject, html, f"Kilo pricing auto-updated: {diff} — {commit_url}")


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.kilo_diff")
    get_settings()

    try:
        new_hash, page_text = await fetch_pricing_hash()
        last_hash = await cache.get(LAST_HASH_KEY)

        if last_hash and last_hash != new_hash:
            log.warning("kilo_pricing_changed", old=last_hash, new=new_hash)
            await _handle_change(last_hash, new_hash, page_text)
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
    finally:
        # Close the Redis connection before the loop tears down, else redis-py's
        # async deallocator logs a noisy "Event loop is closed" traceback on exit.
        await cache.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
