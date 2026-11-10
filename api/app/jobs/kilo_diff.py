"""CronJob entrypoint: keep kilo_plans.yaml in sync with kilo.ai/pricing.

Stores the last page hash in Postgres (``kilo_plan_snapshot``), not Redis:
the cache silently falls back to process memory when Redis is down, which
made every run look like a first run so changes were never detected. On a
hash change: extracts the tier figures via an LLM, sanity-checks them
against the current yaml, and — if they pass and actually differ — commits
the update to a bot branch (``bot/kilo-plans-<hash>``, cut from main) and
opens a merge request assigned to the reviewer. Nothing reaches main until a
human merges it; GitLab CI then builds/deploys as normal. An implausible
extraction just falls back to the "please check manually" email instead.
"""

from __future__ import annotations

import asyncio
import html
import sys
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from app.config import get_settings
from app.db import engine, session_scope
from app.logging import configure_logging, get_logger
from app.models import KiloPlanSnapshot
from app.schemas import KiloPlan
from app.services import kilo, kilo_extract
from app.services.cache import cache
from app.services.gitlab_commit import propose_file_change
from app.services.kilo import fetch_pricing_hash
from app.services.mailer import send

KILO_PLANS_REPO_PATH = "api/app/data/kilo_plans.yaml"
BOT_BRANCH_PREFIX = "bot/kilo-plans-"


@dataclass(frozen=True)
class _Proposal:
    """An auto-update that was handed to a human as a merge request."""

    plans: list[KiloPlan]
    diff: dict
    review_url: str


async def last_known_hash() -> str | None:
    async with session_scope() as session:
        return await session.scalar(
            select(KiloPlanSnapshot.source_hash)
            .order_by(KiloPlanSnapshot.captured_at.desc(), KiloPlanSnapshot.id.desc())
            .limit(1)
        )


async def record_hash(new_hash: str, plans: list[KiloPlan] | None = None) -> None:
    """Persist the plan table under the new page hash (one row per tier)."""
    rows = plans if plans is not None else kilo.load_plans()
    async with session_scope() as session:
        session.add_all(
            KiloPlanSnapshot(
                tier=p.tier,
                monthly_usd=p.monthly_usd,
                paid_credits_usd=p.paid_credits_usd,
                max_bonus_pct=p.max_bonus_pct,
                source_hash=new_hash,
            )
            for p in rows
        )


async def _handle_change(old_hash: str, new_hash: str, page_text: str) -> _Proposal | None:
    """Handle a page change. Returns the opened merge request on an auto-update."""
    log = get_logger("jobs.kilo_diff")
    current = kilo.load_raw()

    try:
        extracted = await kilo_extract.extract_pricing(page_text)
    except Exception as exc:
        log.error("kilo_extraction_failed", error=str(exc), exc_info=True)
        await _send_manual_review_email(old_hash, new_hash, reason=f"extraction failed: {exc}")
        return None

    problems = kilo_extract.sanity_check(current, extracted)
    if problems:
        log.warning("kilo_extraction_rejected", old=old_hash, new=new_hash, problems=problems)
        await _send_manual_review_email(old_hash, new_hash, reason="; ".join(problems))
        return None

    diff = kilo_extract.diff_from_current(current, extracted)
    if diff is None:
        log.info("kilo_pricing_hash_noise", old=old_hash, new=new_hash)
        return None

    verified_date = date.today().isoformat()
    rendered = kilo_extract.render_kilo_plans_yaml(extracted, verified_date)
    title = f"chore(kilo): auto-update pricing ({verified_date})"
    commit_message = f"{title}\n\n{diff}"
    # One branch per page hash: a retry (or a second run on the same hash)
    # finds the open MR instead of opening another.
    proposal = await propose_file_change(
        KILO_PLANS_REPO_PATH,
        rendered,
        commit_message,
        branch=f"{BOT_BRANCH_PREFIX}{new_hash[:12]}",
        mr_title=title,
        mr_description=(
            "Automated update of `kilo_plans.yaml` from the live kilo.ai/pricing page "
            f"(page hash `{new_hash}`, previous `{old_hash}`).\n\n"
            f"```\n{diff}\n```\n\n"
            "Review the figures against https://kilo.ai/pricing before merging."
        ),
    )

    log.warning(
        "kilo_pricing_mr_proposed",
        diff=diff,
        branch=proposal.branch,
        mr_url=proposal.mr_url,
        created=proposal.created,
    )
    return _Proposal(plans=list(extracted.plans), diff=diff, review_url=proposal.mr_url)


async def _send_manual_review_email(old_hash: str, new_hash: str, reason: str) -> None:
    subject = "[Pricing] Kilo Code pricing page changed — needs manual review"
    body = (
        f"<p>kilo.ai/pricing content hash changed, but the automated extraction "
        f"couldn't be trusted:</p>"
        f"<p><strong>Reason:</strong> {html.escape(reason)}</p>"
        f"<p><strong>Old hash:</strong> {html.escape(old_hash)}<br>"
        f"<strong>New hash:</strong> {html.escape(new_hash)}</p>"
        f"<p>Please check https://kilo.ai/pricing and update "
        f"<code>{KILO_PLANS_REPO_PATH}</code> manually.</p>"
    )
    delivered = await send(
        subject, body, f"Kilo pricing changed but needs manual review: {reason}"
    )
    if not delivered:
        # Nothing else surfaces this change, so keep the old baseline (the job
        # exits non-zero) and re-alert once mail works, instead of recording
        # the new hash and losing the alert for good.
        raise RuntimeError("manual-review alert not delivered (SMTP not configured)")


async def _send_auto_update_email(diff: dict, review_url: str) -> None:
    subject = "[Pricing] Kilo Code pricing update needs review"
    diff_html = "<br>".join(
        f"{html.escape(str(k))}: {html.escape(str(v))}" for k, v in diff.items()
    )
    url = html.escape(review_url, quote=True)
    body = (
        f"<p>kilo.ai/pricing changed. A merge request with the updated "
        f"kilo_plans.yaml was opened for review.</p>"
        f"<p><strong>Changes:</strong><br>{diff_html}</p>"
        f'<p><a href="{url}">{url}</a></p>'
        f"<p>Review and merge it to deploy the new figures.</p>"
    )
    # FYI only: an undelivered email is logged (by send), not an error.
    await send(subject, body, f"Kilo pricing update needs review: {diff} — {review_url}")


async def _notify_proposal(proposal: _Proposal) -> None:
    """FYI mail for an opened MR. Never fatal: the MR and the baseline are already done."""
    log = get_logger("jobs.kilo_diff")
    try:
        await _send_auto_update_email(proposal.diff, proposal.review_url)
    except Exception as exc:
        log.error("kilo_fyi_email_failed", error=str(exc), exc_info=True)


async def _main() -> int:
    configure_logging()
    log = get_logger("jobs.kilo_diff")
    get_settings()

    try:
        new_hash, page_text = await fetch_pricing_hash()
        last_hash = await last_known_hash()

        if last_hash == new_hash:
            log.info("kilo_pricing_unchanged", hash=new_hash)
            return 0

        proposal: _Proposal | None = None
        if last_hash is None:
            log.info("kilo_pricing_baseline_recorded", hash=new_hash)
        else:
            log.warning("kilo_pricing_changed", old=last_hash, new=new_hash)
            proposal = await _handle_change(last_hash, new_hash, page_text)

        # Record only after the change was handled, so a failure (for example
        # the GitLab commit/MR raising, or an undelivered manual-review alert)
        # is retried on the next run. Recorded before the FYI mail, so a mail
        # failure cannot cause a second MR on the next run.
        await record_hash(new_hash, proposal.plans if proposal else None)
        if proposal is not None:
            await _notify_proposal(proposal)
        return 0
    except Exception as exc:
        log.error("kilo_diff_failed", error=str(exc), exc_info=True)
        return 1
    finally:
        # Close Redis/DB connections before the loop tears down, else the async
        # deallocators log noisy "Event loop is closed" tracebacks on exit.
        await cache.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
