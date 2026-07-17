"""M9 — the transactional-outbox → SMTP relay (audit [IMP-WRK-1]).

Per drain tick: reap rows stuck in 'sending', claim pending rows with `FOR UPDATE SKIP LOCKED`,
then send each OUTSIDE the claim lock. Dedupe via `email_log UNIQUE(tenant_id, dedupe_key)` —
insert-on-conflict acts as the send lock; a failed send releases it so a retry re-sends.
At-least-once with dedupe (exactly-once over SMTP is impossible). Retry with backoff, then dead.

Worker-side RLS: the outbox is tenant-scoped, so we iterate active tenants (from the non-RLS
`tenant` table) and open `with_tenant()` per tenant before any DML.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import (
    OUTBOX_BACKOFF_BASE_SECONDS,
    OUTBOX_DRAIN_BATCH,
    OUTBOX_MAX_ATTEMPTS,
    OUTBOX_REAPER_STUCK_SECONDS,
    get_settings,
)
from app.infra.db.engine import WorkerSessionLocal
from app.infra.db.models.outbox import EmailLog, Outbox
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.infra.email import smtp
from app.infra.queue.celery_app import celery_app
from app.workers._run import run_async

log = logging.getLogger(__name__)


def _email_html(*, heading: str, paragraphs: list[str], cta_label: str, cta_url: str) -> str:
    """Branded HTML shell shared by every transactional email — logo mark, a primary button,
    and a copy-paste fallback link underneath it (the pattern most products use, since some
    clients/spam filters strip or disable the button). Inline styles + table layout only:
    email clients don't load external stylesheets. Colors mirror the app's own light-mode
    tokens (`src/styles/globals.css`) so the two surfaces read as one product."""
    body_html = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#3a3530;">{p}</p>'
        for p in paragraphs
    )
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:32px 16px;background:#e8e7e2;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="center">
          <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:16px;border:1px solid #e2ded6;">
            <tr>
              <td style="padding:28px 32px 0;">
                <table role="presentation" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="width:32px;height:32px;border-radius:8px;background:#1c1917;text-align:center;">
                      <span style="display:inline-block;line-height:32px;color:#e8e7e2;font-size:15px;font-weight:700;">R</span>
                    </td>
                    <td style="padding-left:10px;font-size:15px;font-weight:600;color:#1c1917;">Relay</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 32px 8px;">
                <h1 style="margin:0 0 16px;font-size:20px;font-weight:600;color:#1c1917;">{heading}</h1>
                {body_html}
              </td>
            </tr>
            <tr>
              <td style="padding:8px 32px 32px;">
                <a href="{cta_url}" style="display:inline-block;background:#1c1917;color:#e8e7e2;text-decoration:none;font-size:14px;font-weight:600;padding:12px 22px;border-radius:8px;">{cta_label}</a>
                <p style="margin:20px 0 0;font-size:12px;line-height:1.6;color:#6b6560;">
                  Or copy and paste this link into your browser:<br>
                  <span style="word-break:break-all;color:#9c5326;">{cta_url}</span>
                </p>
              </td>
            </tr>
          </table>
          <p style="margin:20px 0 0;font-size:11px;color:#9a948d;">Relay &middot; AI customer support, wired to your own data.</p>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _compose(*, heading: str, paragraphs: list[str], cta_label: str, cta_url: str) -> tuple[str, str]:
    """Returns (plain_text, html) built from the same copy, so the two parts never drift."""
    text = heading + "\n\n" + "\n\n".join(paragraphs) + f"\n\n{cta_label}: {cta_url}"
    html = _email_html(heading=heading, paragraphs=paragraphs, cta_label=cta_label, cta_url=cta_url)
    return text, html


def _render(event_type: str, payload: dict) -> tuple[str, str, str, str] | None:
    """(recipient, subject, text_body, html_body) for an outbox EMAIL event, or None to no-op
    (non-email events like ``ticket.*_summary.requested`` fall through and are marked done
    without sending). Event names match the emit() call sites across M1 (auth), M6
    (escalation_service), and admin invite.

    NOTE: the link is only reachable by the recipient if FRONTEND_ORIGIN is a URL THEY can
    open — fine for local testing on your own machine (http://localhost:5173), but set it to
    your deployed domain before inviting real staff on other machines, or their link will
    point at their own localhost."""
    origin = get_settings().frontend_origin.rstrip("/")
    token = payload.get("token", "")
    if event_type == "email.verify":
        link = f"{origin}/verify?token={token}"
        text, html = _compose(
            heading="Confirm your email",
            paragraphs=["Welcome to Relay! Please confirm your email address to activate your account.",
                        "If you didn't create this account, you can safely ignore this email."],
            cta_label="Verify your account",
            cta_url=link,
        )
        return (payload["to"], "Verify your account", text, html)
    if event_type == "email.password_reset":
        link = f"{origin}/reset?token={token}"
        text, html = _compose(
            heading="Reset your password",
            paragraphs=["We received a request to reset your password. This link expires in 1 hour.",
                        "If you didn't request this, you can safely ignore this email."],
            cta_label="Choose a new password",
            cta_url=link,
        )
        return (payload["to"], "Reset your password", text, html)
    if event_type == "email.staff_invite":
        link = f"{origin}/reset?token={token}"
        text, html = _compose(
            heading="You've been invited to a workspace",
            paragraphs=["You've been invited to join a team on Relay. This invite link expires in 7 days."],
            cta_label="Accept invite & set password",
            cta_url=link,
        )
        return (payload["to"], "You've been invited to a workspace", text, html)
    if event_type == "email.escalation_agent_notify":
        # Sent to EACH available agent so any of them can claim the escalated ticket.
        pr = payload.get("priority")
        pr_note = " (high priority)" if pr == "high" else ""
        text, html = _compose(
            heading=f"New escalation to claim{pr_note}",
            paragraphs=[f"A conversation was escalated{pr_note} (reason: {payload.get('reason')}) "
                        "and is waiting in the queue."],
            cta_label="Open agent workspace",
            cta_url=f"{origin}/inbox",
        )
        return (payload["to"], f"New escalation to claim{pr_note}", text, html)
    if event_type in ("email.escalation_support_notify", "escalation.support_notify"):
        text, html = _compose(
            heading="A customer is waiting for a human agent",
            paragraphs=[f"Ticket {payload.get('ticket_id')} was escalated "
                        f"(reason: {payload.get('reason')})."],
            cta_label="Open agent workspace",
            cta_url=f"{origin}/inbox",
        )
        return (payload["to"], "A customer is waiting for a human agent", text, html)
    if event_type == "email.customer_reply":
        # After-hours follow-up: the customer left an email, an agent has now replied — deliver it.
        text, html = _compose(
            heading="You have a new reply from our support team",
            paragraphs=[payload.get("reply", ""),
                        "You can reply by returning to the chat on our website."],
            cta_label="View the conversation",
            cta_url=origin,
        )
        return (payload["to"], "You have a new reply from our support team", text, html)
    return None


async def _claim(tid) -> list[dict]:
    now = datetime.now(timezone.utc)
    async with with_tenant(tid) as s:
        # Reaper: return rows orphaned mid-send back to pending.
        await s.execute(
            update(Outbox)
            .where(Outbox.status == "sending",
                   Outbox.locked_at < now - timedelta(seconds=OUTBOX_REAPER_STUCK_SECONDS))
            .values(status="pending", locked_at=None)
        )
        rows = (
            await s.execute(
                select(Outbox)
                .where(Outbox.status == "pending", Outbox.next_attempt_at <= now)
                .order_by(Outbox.created_at)
                .limit(OUTBOX_DRAIN_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        claimed = []
        for r in rows:
            r.status = "sending"
            r.attempts += 1
            r.locked_at = now
            claimed.append({"id": r.id, "event_type": r.event_type, "payload": r.payload,
                            "dedupe_key": r.dedupe_key or str(r.id), "attempts": r.attempts})
        return claimed


async def _deliver(tid, row: dict) -> str:
    now = datetime.now(timezone.utc)
    rendered = _render(row["event_type"], row["payload"])
    async with with_tenant(tid) as s:
        if rendered is None:
            await s.execute(update(Outbox).where(Outbox.id == row["id"]).values(status="sent"))
            return "skipped"
        to, subject, body, html = rendered
        dk = row["dedupe_key"]
        # Dedupe: the insert IS the send lock. If it conflicts, someone already handled it.
        inserted = (
            await s.execute(
                pg_insert(EmailLog)
                .values(dedupe_key=dk, recipient=to, status="sent")
                .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_key"])
                .returning(EmailLog.id)
            )
        ).first()
        if inserted is None:
            await s.execute(update(Outbox).where(Outbox.id == row["id"]).values(status="sent"))
            return "deduped"
        try:
            await asyncio.to_thread(smtp.send, to=to, subject=subject, body=body, html=html)
            await s.execute(update(Outbox).where(Outbox.id == row["id"]).values(status="sent"))
            return "sent"
        except Exception as exc:  # noqa: BLE001
            log.warning("outbox send failed (id=%s attempts=%s): %s", row["id"], row["attempts"], type(exc).__name__)
            # Release the dedupe marker so a retry re-sends.
            await s.execute(delete(EmailLog).where(EmailLog.dedupe_key == dk))
            if row["attempts"] >= OUTBOX_MAX_ATTEMPTS:
                await s.execute(update(Outbox).where(Outbox.id == row["id"]).values(status="dead"))
                return "dead"
            backoff = OUTBOX_BACKOFF_BASE_SECONDS * (2 ** (row["attempts"] - 1))
            await s.execute(
                update(Outbox).where(Outbox.id == row["id"])
                .values(status="pending", locked_at=None, next_attempt_at=now + timedelta(seconds=backoff))
            )
            return "retry"


async def _drain_all() -> dict:
    async with WorkerSessionLocal() as s:  # tenant table is not RLS-scoped
        tenant_ids = (await s.execute(select(Tenant.id).where(Tenant.status == "active"))).scalars().all()
    totals = {"claimed": 0, "sent": 0, "deduped": 0, "retry": 0, "dead": 0, "skipped": 0}
    for tid in tenant_ids:
        for row in await _claim(tid):
            totals["claimed"] += 1
            totals[await _deliver(tid, row)] += 1
    return totals


@celery_app.task(name="app.workers.notification.drain_outbox")
def drain_outbox() -> dict:
    return run_async(_drain_all())
