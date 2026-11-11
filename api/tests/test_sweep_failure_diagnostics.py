"""Recovery boundaries retain fallback behavior and exception diagnostics."""

import pytest
import respx
import structlog
from structlog.testing import capture_logs

from app.services import accounts, cache, openrouter


@pytest.mark.asyncio
async def test_account_failure_preserves_its_error_and_traceback(monkeypatch):
    monkeypatch.setattr(accounts._settings, "openrouter_api_key", "test-only")
    with capture_logs() as records:
        monkeypatch.setattr(accounts, "log", structlog.get_logger())
        with respx.mock(base_url="https://openrouter.ai") as mock:
            mock.get("/api/v1/credits").respond(503)
            result = await accounts._check_openrouter()
    assert result.configured is True
    assert "503" in result.error
    assert any(r.get("exc_info") for r in records if r["event"] == "openrouter_check_failed")


@pytest.mark.asyncio
async def test_cache_cleanup_failure_is_diagnostic_and_drops_the_client(monkeypatch):
    class FailingClose:
        async def aclose(self):
            raise OSError("closed transport")

    instance = cache.Cache("redis://localhost:6379", default_ttl=1)
    instance._client = FailingClose()
    with capture_logs() as records:
        monkeypatch.setattr(cache, "log", structlog.get_logger())
        await instance.close()
    assert instance._client is None
    assert any(r.get("exc_info") for r in records)


def test_catalog_record_failure_does_not_abort_remaining_records(monkeypatch):
    def broken_normalize(record):
        raise TypeError("unexpected upstream record")

    monkeypatch.setattr(openrouter, "_normalize", broken_normalize)
    with capture_logs() as records:
        monkeypatch.setattr(openrouter, "log", structlog.get_logger())
        assert openrouter.normalize_all([{"id": "example/model"}]) == []
    assert any(r.get("exc_info") for r in records if r["event"] == "openrouter_model_skipped")
