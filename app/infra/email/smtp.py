"""SMTP dispatch port. In dev this points at MailHog (localhost:1025) which captures every
message — nothing is sent externally. The notification worker (M9) drains the outbox and
calls ``send``; it is the ONLY code that talks to SMTP directly.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send(*, to: str, subject: str, body: str) -> None:
    """Synchronous send (called from a Celery worker). Raises on SMTP failure so the M9
    outbox drain can retry / dead-letter."""
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        client.send_message(msg)
