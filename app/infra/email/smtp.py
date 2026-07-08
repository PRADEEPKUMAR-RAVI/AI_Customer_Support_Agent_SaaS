"""SMTP dispatch port. In dev this points at MailPit (localhost:1025) which captures every
message — nothing is sent externally. In prod, point it at a transactional provider's SMTP
relay (Brevo/Resend/…) by setting ``smtp_user``/``smtp_password``/``smtp_starttls`` — the send
path is provider-agnostic: any relay speaking SMTP+STARTTLS on port 587 works with only a
credential change, no code change. The notification worker (M9) drains the outbox and calls
``send``; it is the ONLY code that talks to SMTP directly.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


def send(*, to: str, subject: str, body: str) -> None:
    """Synchronous send (called from a Celery worker). Raises on SMTP failure so the M9
    outbox drain can retry / dead-letter.

    Dev (MailPit): ``smtp_user`` empty + ``smtp_starttls`` False → plaintext, no auth.
    Provider relay (Brevo/Resend): set ``smtp_starttls=True`` + ``smtp_user``/``smtp_password``
    → upgrade to TLS via STARTTLS, then authenticate, then send. Nothing reaches a provider
    until those are configured, so offline-first dev stays keyless.
    """
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(msg)
