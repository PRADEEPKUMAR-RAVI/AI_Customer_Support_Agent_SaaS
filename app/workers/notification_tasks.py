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


def _render(event_type: str, payload: dict) -> tuple[str, str, str] | None:
    """(recipient, subject, body) for an outbox EMAIL event, or None to no-op (non-email events
    like ``ticket.*_summary.requested`` fall through and are marked done without sending). Event
    names match the emit() call sites across M1 (auth), M6 (escalation_service), and admin invite.

    Bodies are plain text with a CLICKABLE action link built from ``FRONTEND_ORIGIN`` + the token
    (email clients auto-linkify the URL) — the raw token is not shown. NOTE: the link is only
    reachable by the recipient if FRONTEND_ORIGIN is a URL THEY can open — fine for local testing on
    your own machine (http://localhost:5173), but set it to your deployed domain before inviting
    real staff on other machines, or their link will point at their own localhost."""
    origin = get_settings().frontend_origin.rstrip("/")
    token = payload.get("token", "")
    if event_type == "email.verify":
        link = f"{origin}/verify?token={token}"
        return (payload["to"], "Verify your account",
                "Welcome! Please confirm your email address to activate your account:\n\n"
                f"{link}\n\nIf you didn't create this account, you can safely ignore this email.")
    if event_type == "email.password_reset":
        link = f"{origin}/reset?token={token}"
        return (payload["to"], "Reset your password",
                "We received a request to reset your password. Choose a new one here "
                "(this link expires in 1 hour):\n\n"
                f"{link}\n\nIf you didn't request this, you can safely ignore this email.")
    if event_type == "email.staff_invite":
        link = f"{origin}/reset?token={token}"
        return (payload["to"], "You've been invited to a workspace",
                "You've been invited to a workspace on the AI Customer Support Agent.\n\n"
                "Accept the invitation and set your password here (link expires in 7 days):\n\n"
                f"{link}")
    if event_type == "email.escalation_agent_notify":
        # Sent to EACH available agent so any of them can claim the escalated ticket.
        pr = payload.get("priority")
        pr_note = " (high priority)" if pr == "high" else ""
        return (payload["to"], f"New escalation to claim{pr_note}",
                f"A conversation was escalated{pr_note} (reason: {payload.get('reason')}) and is "
                f"waiting in the queue. Claim it in your agent workspace to help the customer:\n\n"
                f"{origin}/inbox")
    if event_type in ("email.escalation_support_notify", "escalation.support_notify"):
        return (payload["to"], "A customer is waiting for a human agent",
                f"Ticket {payload.get('ticket_id')} was escalated (reason: {payload.get('reason')}).\n\n"
                f"Please claim it in the agent workspace:\n\n{origin}/inbox")
    if event_type == "email.customer_reply":
        # After-hours follow-up: the customer left an email, an agent has now replied — deliver it.
        return (payload["to"], "You have a new reply from our support team",
                "Our support team has replied to your request:\n\n"
                f"{payload.get('reply', '')}\n\n"
                "You can reply by returning to the chat on our website.")
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
        to, subject, body = rendered
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
            await asyncio.to_thread(smtp.send, to=to, subject=subject, body=body)
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
