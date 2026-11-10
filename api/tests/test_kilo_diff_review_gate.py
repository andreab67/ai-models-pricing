"""kilo_diff review gate: bot branch + merge request, record-before-mail, escaped mail.

The job used to commit straight to main, record the baseline only after the FYI
mail, and interpolate raw text into the mail HTML. These tests pin the fixes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from app.jobs import kilo_diff
from app.schemas import KiloPlan
from app.services import gitlab_commit

_S = gitlab_commit._settings
PROJECT = f"{_S.gitlab_api_url}/projects/{_S.gitlab_project_id}"
BRANCH = "bot/kilo-plans-abcdef123456"
MR_URL = "https://gitlab.example/root/model-pricing/-/merge_requests/7"


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitlab_commit._settings, "gitlab_token", "test-token", raising=False)


def _mocks(
    mock: respx.MockRouter, *, open_mrs: list[dict[str, Any]], branch_exists: bool
) -> dict[str, respx.Route]:
    return {
        "mr_list": mock.get(f"{PROJECT}/merge_requests").mock(
            return_value=httpx.Response(200, json=open_mrs)
        ),
        "branch": mock.get(f"{PROJECT}/repository/branches/bot%2Fkilo-plans-abcdef123456").mock(
            return_value=httpx.Response(200 if branch_exists else 404, json={})
        ),
        "commit": mock.post(f"{PROJECT}/repository/commits").mock(
            return_value=httpx.Response(201, json={"id": "c0ffee"})
        ),
        "mr_create": mock.post(f"{PROJECT}/merge_requests").mock(
            return_value=httpx.Response(201, json={"web_url": MR_URL})
        ),
    }


async def _propose() -> gitlab_commit.Proposal:
    return await gitlab_commit.propose_file_change(
        "api/app/data/kilo_plans.yaml", "yaml", "msg", BRANCH, "title", "description"
    )


async def test_commit_goes_to_a_bot_branch_and_mr_is_assigned_to_reviewer() -> None:
    with respx.mock(assert_all_called=False) as mock:
        routes = _mocks(mock, open_mrs=[], branch_exists=False)
        result = await _propose()

    assert result == gitlab_commit.Proposal(branch=BRANCH, mr_url=MR_URL, created=True)
    commit_body = json.loads(routes["commit"].calls.last.request.content)
    assert commit_body["branch"] == BRANCH
    assert commit_body["branch"] != "main"
    assert commit_body["start_branch"] == "main"
    mr_body = json.loads(routes["mr_create"].calls.last.request.content)
    assert mr_body["source_branch"] == BRANCH
    assert mr_body["target_branch"] == "main"
    assert mr_body["assignee_ids"] == [2]
    assert routes["commit"].calls.last.request.headers["PRIVATE-TOKEN"] == "test-token"


async def test_open_mr_for_same_hash_is_reused_not_duplicated() -> None:
    existing = [{"source_branch": BRANCH, "state": "opened", "web_url": MR_URL}]
    with respx.mock(assert_all_called=False) as mock:
        routes = _mocks(mock, open_mrs=existing, branch_exists=True)
        result = await _propose()

    assert result == gitlab_commit.Proposal(branch=BRANCH, mr_url=MR_URL, created=False)
    assert not routes["commit"].called
    assert not routes["mr_create"].called


async def test_existing_branch_without_mr_opens_mr_without_recommitting() -> None:
    """A previous run committed but failed before opening the MR."""
    with respx.mock(assert_all_called=False) as mock:
        routes = _mocks(mock, open_mrs=[], branch_exists=True)
        result = await _propose()

    assert result.created is True
    assert not routes["commit"].called
    assert routes["mr_create"].called


def _plan() -> KiloPlan:
    return KiloPlan(tier="pro", monthly_usd=49.0, paid_credits_usd=49.0, max_bonus_pct=0.4)


def _stub_extraction(monkeypatch: pytest.MonkeyPatch, diff: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _extract(_page_text: str) -> SimpleNamespace:
        return SimpleNamespace(plans=[_plan()])

    async def _propose_stub(*args: Any, **kwargs: Any) -> gitlab_commit.Proposal:
        calls.append({"args": args, **kwargs})
        return gitlab_commit.Proposal(branch=kwargs["branch"], mr_url=MR_URL, created=True)

    monkeypatch.setattr(kilo_diff.kilo, "load_raw", lambda: {})
    monkeypatch.setattr(kilo_diff.kilo_extract, "extract_pricing", _extract)
    monkeypatch.setattr(kilo_diff.kilo_extract, "sanity_check", lambda cur, ext: [])
    monkeypatch.setattr(kilo_diff.kilo_extract, "diff_from_current", lambda cur, ext: diff)
    monkeypatch.setattr(kilo_diff.kilo_extract, "render_kilo_plans_yaml", lambda ext, d: "yaml")
    monkeypatch.setattr(kilo_diff, "propose_file_change", _propose_stub)
    return calls


async def test_handle_change_opens_mr_from_hash_named_bot_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_extraction(monkeypatch, {"pro": {"monthly_usd": {"old": 40, "new": 49}}})

    proposal = await kilo_diff._handle_change("oldhash", "abcdef1234567890", "page")

    assert proposal is not None
    assert proposal.review_url == MR_URL
    assert len(calls) == 1
    assert calls[0]["branch"] == "bot/kilo-plans-abcdef123456"
    assert calls[0]["branch"] != "main"
    assert "kilo_plans.yaml" in calls[0]["args"][0]


class _Closeable:
    async def close(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


async def _run_main(
    monkeypatch: pytest.MonkeyPatch, send: Any, events: list[str]
) -> int:
    async def _fetch() -> tuple[str, str]:
        return "abcdef1234567890", "page"

    async def _last() -> str:
        return "oldhash"

    async def _record(h: str, plans: object = None) -> None:
        events.append(f"record:{h}")

    monkeypatch.setattr(kilo_diff, "fetch_pricing_hash", _fetch)
    monkeypatch.setattr(kilo_diff, "last_known_hash", _last)
    monkeypatch.setattr(kilo_diff, "record_hash", _record)
    monkeypatch.setattr(kilo_diff, "send", send)
    monkeypatch.setattr(kilo_diff, "cache", _Closeable())
    monkeypatch.setattr(kilo_diff, "engine", _Closeable())
    return await kilo_diff._main()


async def test_smtp_error_after_mr_still_records_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    _stub_extraction(monkeypatch, {"pro": {"monthly_usd": {"old": 40, "new": 49}}})

    async def _boom(subject: str, html: str, text: str) -> bool:
        events.append("mail")
        raise OSError("smtp connection refused")

    rc = await _run_main(monkeypatch, _boom, events)

    assert rc == 0
    # Recorded BEFORE the mail was attempted, and the failure did not undo it.
    assert events == ["record:abcdef1234567890", "mail"]


async def test_mr_failure_does_not_record_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _stub_extraction(monkeypatch, {"pro": {"monthly_usd": {"old": 40, "new": 49}}})

    async def _gitlab_down(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("gitlab unreachable")

    async def _send(subject: str, html: str, text: str) -> bool:
        events.append("mail")
        return True

    monkeypatch.setattr(kilo_diff, "propose_file_change", _gitlab_down)
    assert await _run_main(monkeypatch, _send, events) == 1
    assert events == []


async def test_auto_update_email_escapes_every_interpolated_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def _send(subject: str, html: str, text: str) -> bool:
        sent.append(html)
        return True

    monkeypatch.setattr(kilo_diff, "send", _send)
    await kilo_diff._send_auto_update_email(
        {"<img src=x onerror=alert(1)>": {"<b>new</b>": "a&b"}},
        'https://x.example/mr/1"><script>alert(1)</script>',
    )

    html = sent[0]
    assert "<script>" not in html
    assert "<img" not in html
    assert "<b>new</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "a&amp;b" in html


async def test_manual_review_email_escapes_reason_and_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def _send(subject: str, html: str, text: str) -> bool:
        sent.append(html)
        return True

    monkeypatch.setattr(kilo_diff, "send", _send)
    await kilo_diff._send_manual_review_email(
        "<i>old</i>", "<i>new</i>", reason="extraction failed: <script>x</script>"
    )

    html = sent[0]
    assert "<script>" not in html
    assert "<i>old</i>" not in html
    assert "<i>new</i>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
