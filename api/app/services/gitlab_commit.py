"""Minimal GitLab Commits API client.

Used only by the kilo_diff CronJob to push an updated kilo_plans.yaml
directly to main when an extracted pricing change passes sanity checks.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
_settings = get_settings()


async def commit_file(path: str, content: str, message: str, branch: str = "main") -> str:
    """Commit a single-file update and return the commit's web URL."""
    url = f"{_settings.gitlab_api_url}/projects/{_settings.gitlab_project_id}/repository/commits"
    headers = {"PRIVATE-TOKEN": _settings.gitlab_token}
    body = {
        "branch": branch,
        "commit_message": message,
        "actions": [{"action": "update", "file_path": path, "content": content}],
    }
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        commit = resp.json()

    instance_root = _settings.gitlab_api_url.removesuffix("/api/v4")
    return f"{instance_root}/{_settings.gitlab_project_path}/-/commit/{commit['id']}"
