"""Minimal GitLab client for the kilo_diff CronJob.

kilo_diff never pushes to main. ``propose_file_change`` commits the updated
kilo_plans.yaml to a bot branch cut from main and opens a merge request
assigned to a human reviewer; a green pipeline and a merge are what deploy it.
Both the Commits API and the Merge Requests API need the ``api`` token scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
_settings = get_settings()

DEFAULT_BRANCH = "main"


@dataclass(frozen=True)
class Proposal:
    """Result of ``propose_file_change``."""

    branch: str
    mr_url: str
    created: bool  # False when an open MR for the branch already existed


def _project_url() -> str:
    return f"{_settings.gitlab_api_url}/projects/{_settings.gitlab_project_id}"


def _client() -> httpx.AsyncClient:
    if not _settings.gitlab_token:
        # An empty PRIVATE-TOKEN header would just come back as a 401 from the
        # first call; fail before any request with a message that names the fix.
        raise RuntimeError("GITLAB_TOKEN is not set; cannot open the pricing merge request")
    return httpx.AsyncClient(
        timeout=30.0, headers={"PRIVATE-TOKEN": _settings.gitlab_token}
    )


async def commit_file(
    path: str,
    content: str,
    message: str,
    branch: str = DEFAULT_BRANCH,
    start_branch: str | None = None,
) -> str:
    """Commit a single-file update and return the commit's web URL.

    With ``start_branch`` the target ``branch`` is created from it (GitLab
    Commits API); the call fails if ``branch`` already exists.
    """
    body: dict[str, object] = {
        "branch": branch,
        "commit_message": message,
        "actions": [{"action": "update", "file_path": path, "content": content}],
    }
    if start_branch:
        body["start_branch"] = start_branch
    async with _client() as client:
        resp = await client.post(f"{_project_url()}/repository/commits", json=body)
        resp.raise_for_status()
        commit = resp.json()

    instance_root = _settings.gitlab_api_url.removesuffix("/api/v4")
    return f"{instance_root}/{_settings.gitlab_project_path}/-/commit/{commit['id']}"


async def find_open_merge_request(
    source_branch: str, target_branch: str = DEFAULT_BRANCH
) -> str | None:
    """Return the web URL of an open MR from ``source_branch``, or None."""
    params = {"state": "opened", "source_branch": source_branch, "target_branch": target_branch}
    async with _client() as client:
        resp = await client.get(f"{_project_url()}/merge_requests", params=params)
        resp.raise_for_status()
        for mr in resp.json():
            # Defence in depth: do not trust the server-side filter alone.
            if mr.get("source_branch") == source_branch and mr.get("state") == "opened":
                return str(mr["web_url"])
    return None


async def branch_exists(branch: str) -> bool:
    async with _client() as client:
        resp = await client.get(f"{_project_url()}/repository/branches/{quote(branch, safe='')}")
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True


async def delete_branch(branch: str) -> None:
    async with _client() as client:
        resp = await client.delete(
            f"{_project_url()}/repository/branches/{quote(branch, safe='')}"
        )
        if resp.status_code != 404:
            resp.raise_for_status()


async def create_merge_request(
    source_branch: str,
    title: str,
    description: str,
    assignee_id: int,
    target_branch: str = DEFAULT_BRANCH,
) -> str:
    """Open an MR assigned to ``assignee_id`` and return its web URL."""
    body = {
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": title,
        "description": description,
        "assignee_ids": [assignee_id],
        "remove_source_branch": True,
    }
    async with _client() as client:
        resp = await client.post(f"{_project_url()}/merge_requests", json=body)
        resp.raise_for_status()
        return str(resp.json()["web_url"])


async def propose_file_change(
    path: str,
    content: str,
    message: str,
    branch: str,
    mr_title: str,
    mr_description: str,
) -> Proposal:
    """Commit to a bot ``branch`` cut from main and open an MR for review.

    Idempotent across retries: an open MR for ``branch`` is returned as is
    (no second MR). A branch that exists with no open MR (a closed MR whose
    branch was not removed, or a run that committed but failed before opening
    the MR) is deleted and recreated from main, so the MR never carries a
    stale commit cut from an old main.
    """
    existing = await find_open_merge_request(branch)
    if existing:
        log.info("kilo_mr_already_open", branch=branch, mr_url=existing)
        return Proposal(branch=branch, mr_url=existing, created=False)

    if await branch_exists(branch):
        log.warning("kilo_branch_exists_without_mr_recreating", branch=branch)
        await delete_branch(branch)
    await commit_file(path, content, message, branch=branch, start_branch=DEFAULT_BRANCH)

    mr_url = await create_merge_request(
        branch, mr_title, mr_description, _settings.gitlab_mr_assignee_id
    )
    return Proposal(branch=branch, mr_url=mr_url, created=True)
