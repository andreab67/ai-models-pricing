"""SMTP mailer for the daily report."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
_settings = get_settings()


async def send(subject: str, html: str, text: str) -> None:
    if not _settings.smtp_host or not _settings.smtp_to:
        log.warning("smtp_not_configured", host=_settings.smtp_host, to=_settings.smtp_to)
        return

    msg = EmailMessage()
    msg["From"] = _settings.smtp_from
    msg["To"] = ", ".join(_settings.smtp_to)
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=_settings.smtp_host,
        port=_settings.smtp_port,
        username=_settings.smtp_username or None,
        password=_settings.smtp_password or None,
        start_tls=_settings.smtp_starttls,
    )
    log.info(
        "daily_report_sent",
        to=_settings.smtp_to,
        subject=subject,
        bytes=len(html),
    )
