"""Run the real report and mailer with only external effects replaced."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.jobs import daily_report
from app.schemas import ModelPricing
from app.services import mailer


@pytest.mark.parametrize("delivery", [True, False, "raise", "unconfigured"])
@pytest.mark.parametrize("baseline", [True, False])
async def test_report_delivery_exit_and_cache_cleanup(monkeypatch, delivery, baseline):
    captured = []
    closed = []
    settings = Settings(_env_file=None, smtp_host="smtp.invalid", smtp_to=["test@example.invalid"])
    models = [ModelPricing(
        id="example/cheap", name="<script>unsafe</script>", prompt_usd_per_mtok=1,
        completion_usd_per_mtok=2, context_length=2_000_000,
        supports_tools=True, captured_at=datetime.now(UTC),
    )]
    if baseline:
        models.append(models[0].model_copy(update={
            "id": daily_report.BASELINE_MODEL_ID, "name": "Baseline",
            "prompt_usd_per_mtok": 10, "completion_usd_per_mtok": 20,
        }))

    async def catalog(*, use_cache):
        assert use_cache is False
        return models

    async def send(subject, html, text):
        captured.append((subject, html, text))
        if delivery == "raise":
            raise OSError("fixture delivery failed")
        return delivery

    async def close():
        closed.append(True)

    monkeypatch.setattr(daily_report, "get_settings", lambda: settings)
    monkeypatch.setattr(daily_report.openrouter, "list_models", catalog)
    monkeypatch.setattr(daily_report, "cache", SimpleNamespace(close=close))
    if delivery == "unconfigured":
        monkeypatch.setattr(mailer, "_settings", settings.model_copy(update={"smtp_host": ""}))
        monkeypatch.setattr(daily_report, "send", mailer.send)
    else:
        monkeypatch.setattr(daily_report, "send", send)
    assert await daily_report._main() == (0 if delivery is True else 1)
    assert closed == [True]
    if captured:
        assert "&lt;script&gt;unsafe&lt;/script&gt;" in captured[0][1]
        assert "<script>unsafe</script>" not in captured[0][1]
        assert "<script>unsafe</script>" in captured[0][2]


async def test_report_catalog_failure_still_closes_cache(monkeypatch):
    closed = []

    async def catalog(**kwargs):
        raise OSError("fixture catalog failure")

    async def close():
        closed.append(True)

    monkeypatch.setattr(daily_report.openrouter, "list_models", catalog)
    monkeypatch.setattr(daily_report, "cache", SimpleNamespace(close=close))
    assert await daily_report._main() == 1
    assert closed == [True]

@pytest.mark.parametrize("use_tls,start_tls", [(True, False), (False, True)])
async def test_real_mailer_uses_smtp_library_with_configured_tls(monkeypatch, use_tls, start_tls):
    """Exercise the installed library with the network client replaced."""
    from email.message import EmailMessage

    import aiosmtplib.api

    captured = {}

    class FakeSMTP:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send_message(self, message, **kwargs):
            captured["message"] = message
            return {}, "queued"

    settings = Settings(_env_file=None, smtp_host="smtp.invalid", smtp_to=["test@example.invalid"],
                        smtp_from="sender@example.invalid", smtp_use_tls=use_tls,
                        smtp_starttls=start_tls)
    monkeypatch.setattr(mailer, "_settings", settings)
    monkeypatch.setattr(aiosmtplib.api, "SMTP", FakeSMTP)
    assert await mailer.send("Subject", "<b>HTML</b>", "Text") is True
    assert captured["use_tls"] is use_tls
    assert captured["start_tls"] is start_tls
    assert isinstance(captured["message"], EmailMessage)
    assert captured["message"]["To"] == "test@example.invalid"
