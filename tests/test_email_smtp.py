"""Email send seam (M9 → SMTP). Proves the single ``smtp.send`` adapter is provider-agnostic:
the dev MailPit path uses no auth/TLS, while a transactional-provider relay (Brevo/Resend) is
enabled purely by config (STARTTLS + login on port 587) with NO code change. Also guards against
a silent-empty-body regression — the plain-text body must reach the message content."""

from __future__ import annotations

import smtplib

import pytest

from app.core.config import Settings
from app.infra.email import smtp


class _FakeSMTP:
    """Records what ``smtp.send`` drives, without opening a socket."""

    last: "_FakeSMTP | None" = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list = []
        _FakeSMTP.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    _FakeSMTP.last = None
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)


def _use_settings(monkeypatch, **over):
    # Explicit kwargs beat env/.env in pydantic-settings, so the test is hermetic regardless of
    # any local .env SMTP_* values.
    settings = Settings(**over)
    monkeypatch.setattr(smtp, "get_settings", lambda: settings)


def test_mailpit_dev_path_has_no_auth_or_tls(monkeypatch):
    _use_settings(
        monkeypatch,
        smtp_host="localhost",
        smtp_port=1025,
        smtp_from="no-reply@cs-agent.local",
        smtp_user="",
        smtp_password="",
        smtp_starttls=False,
    )
    smtp.send(to="user@example.com", subject="Verify your account", body="Token: abc123")

    sent = _FakeSMTP.last
    assert (sent.host, sent.port) == ("localhost", 1025)
    assert sent.started_tls is False          # dev MailPit is plaintext
    assert sent.login_args is None            # ...and unauthenticated
    msg = sent.sent[0]
    assert msg["From"] == "no-reply@cs-agent.local"
    assert msg["To"] == "user@example.com"
    assert msg["Subject"] == "Verify your account"
    assert msg.get_content().strip() == "Token: abc123"


def test_provider_relay_path_starttls_then_login(monkeypatch):
    # Brevo/Resend look identical here — only creds + host differ.
    _use_settings(
        monkeypatch,
        smtp_host="smtp-relay.brevo.com",
        smtp_port=587,
        smtp_from="support@acme.example",
        smtp_user="brevo-login@smtp-brevo.com",
        smtp_password="xkeysib-secret",
        smtp_starttls=True,
    )
    smtp.send(to="cust@example.com", subject="A customer is waiting", body="Ticket 42 escalated.")

    sent = _FakeSMTP.last
    assert (sent.host, sent.port) == ("smtp-relay.brevo.com", 587)
    assert sent.started_tls is True                                   # TLS upgrade happened
    assert sent.login_args == ("brevo-login@smtp-brevo.com", "xkeysib-secret")  # ...before send
    assert sent.sent[0].get_content().strip() == "Ticket 42 escalated."


def test_send_raises_on_smtp_failure(monkeypatch):
    # The M9 outbox drain relies on send() raising so it can retry/dead-letter.
    _use_settings(monkeypatch, smtp_host="localhost", smtp_port=1025)

    def _boom(self, msg):
        raise smtplib.SMTPException("relay refused")

    monkeypatch.setattr(_FakeSMTP, "send_message", _boom)
    with pytest.raises(smtplib.SMTPException):
        smtp.send(to="user@example.com", subject="x", body="y")


def test_render_templates_links_and_new_notification_types():
    """Email bodies carry clickable links (not raw tokens), plus the new agent-notify and
    after-hours customer-reply templates; non-email outbox events no-op."""
    from app.workers.notification_tasks import _render

    to = "user@example.com"
    assert "/verify?token=TOK" in _render("email.verify", {"to": to, "token": "TOK"})[2]
    assert "/reset?token=TOK" in _render("email.password_reset", {"to": to, "token": "TOK"})[2]
    assert "/reset?token=TOK" in _render("email.staff_invite", {"to": to, "token": "TOK"})[2]

    # NEW: per-available-agent escalation notice (with priority) → workspace link
    r_ag = _render("email.escalation_agent_notify",
                   {"to": to, "ticket_id": "T1", "reason": "explicit", "priority": "high"})
    assert r_ag[0] == to and "/inbox" in r_ag[2] and "high" in (r_ag[1] + r_ag[2]).lower()

    # NEW: after-hours follow-up delivers the agent's reply text to the customer
    r_cust = _render("email.customer_reply", {"to": to, "reply": "It ships Monday!"})
    assert r_cust[0] == to and "It ships Monday!" in r_cust[2]

    # non-email outbox events are a no-op (drained + marked done, never sent)
    assert _render("ticket.escalation_summary.requested", {"ticket_id": "T1"}) is None
