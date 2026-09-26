"""Regression tests for fixes from the Kilo Code Review on GitHub #3."""

from __future__ import annotations

import pytest

from app.jobs import kilo_diff
from app.services.cache import Cache


async def test_invalid_redis_url_falls_back_to_memory() -> None:
    c = Cache("http://not-a-redis-url", default_ttl=60)
    await c.set("k", {"v": 1})
    assert await c.get("k") == {"v": 1}
    assert await c.ping() is False


async def test_manual_review_alert_raises_when_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_sent(subject: str, html: str, text: str) -> bool:
        return False

    monkeypatch.setattr(kilo_diff, "send", _not_sent)
    with pytest.raises(RuntimeError, match="not delivered"):
        await kilo_diff._send_manual_review_email("old", "new", reason="r")


async def test_manual_review_alert_passes_when_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _sent(subject: str, html: str, text: str) -> bool:
        return True

    monkeypatch.setattr(kilo_diff, "send", _sent)
    await kilo_diff._send_manual_review_email("old", "new", reason="r")


async def test_auto_update_fyi_does_not_raise_when_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_sent(subject: str, html: str, text: str) -> bool:
        return False

    monkeypatch.setattr(kilo_diff, "send", _not_sent)
    await kilo_diff._send_auto_update_email({"pro": {}}, "https://example/commit")
