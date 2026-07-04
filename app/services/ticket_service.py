"""M5 — Ticketing.

Owns exactly one thing beyond storage: the ONLY legal way to create and drive a ticket through
its lifecycle from this module is through the functions below, which delegate every state
change to Person-1's guarded-CAS ``apply_transition`` primitive. Callers (the M2 engine, once
built) never write ``ticket.state = ...`` directly [watch-out #1].
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import emit
from app.domain.ticketing.states import Actor, TicketState
from app.domain.ticketing.transitions import TransitionResult, apply_transition, assert_allowed
from app.infra.db.models.ticket import ResolutionSummary, Ticket, TicketEvent


async def get_or_create_ticket(session: AsyncSession, *, conversation_id: uuid.UUID) -> Ticket:
    """Idempotent get-or-create keyed by ``(tenant_id, conversation_id)`` [IMP-TKT-4].

    Uses ``INSERT ... ON CONFLICT DO NOTHING`` so two concurrent first-messages on the same
    conversation can't create two tickets: the loser's insert is a no-op and the SELECT below
    (naturally RLS-scoped to the caller's tenant) finds the winner's row either way.
    """
    insert_stmt = (
        pg_insert(Ticket)
        .values(conversation_id=conversation_id)
        .on_conflict_do_nothing(index_elements=["tenant_id", "conversation_id"])
    )
    await session.execute(insert_stmt)
    result = await session.execute(select(Ticket).where(Ticket.conversation_id == conversation_id))
    return result.scalar_one()


async def start_ai_handling(session: AsyncSession, *, ticket_id: uuid.UUID) -> TransitionResult:
    """``new -> ai_handling``, AI actor — fired on the ticket's first AI response.

    A no-op (``applied=False``) if the ticket has already left ``new`` (e.g. a later message on
    the same conversation), which is exactly the desired idempotent behaviour: call this on
    every turn and only the first one actually transitions the ticket.
    """
    return await apply_transition(
        session,
        ticket_id=ticket_id,
        to_state=TicketState.AI_HANDLING,
        actor=Actor.AI,
        expected_from=TicketState.NEW,
    )


async def resolve_ticket(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    actor: Actor = Actor.AI,
    expected_from: TicketState = TicketState.AI_HANDLING,
) -> TransitionResult:
    """``{ai_handling,with_agent} -> resolved`` via the guarded CAS [IMP-TKT-2].

    ``expected_from`` defaults to ``ai_handling`` (the AI/system auto-resolve path); M7's
    agent-resolve passes ``with_agent`` instead — the whitelist allows AGENT only on that edge,
    never on ``ai_handling -> resolved``, so this can't be misused to skip the human hand-off.

    On success only, writes a resolution-summary STUB row [IMP-ESC-6] (``summary=None``) so
    "summary pending" has something to render immediately, and enqueues async summary
    generation via the outbox — the summary *text* is produced later by M2's engine; this
    service only guarantees storage and never blocks the transition on it. Fires nothing if
    another writer (e.g. the Phase-4 idle-resolve sweep) already moved the ticket.
    """
    result = await apply_transition(
        session,
        ticket_id=ticket_id,
        to_state=TicketState.RESOLVED,
        actor=actor,
        expected_from=expected_from,
    )
    if result.applied:
        session.add(ResolutionSummary(ticket_id=ticket_id, type="resolution", summary=None))
        await emit(
            session,
            event_type="ticket.resolution_summary.requested",
            payload={"ticket_id": str(ticket_id)},
            dedupe_key=f"resolution_summary:{ticket_id}",
        )
    return result


async def escalate_ticket(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    actor: Actor,
    priority: str,
    expected_from: TicketState = TicketState.AI_HANDLING,
) -> TransitionResult:
    """``ai_handling -> escalated`` via the guarded CAS. ``apply_transition`` stamps
    ``escalated_at`` itself (the queue's FIFO ordering anchor); this additionally sets
    ``priority`` [C4] and writes the escalation-summary STUB in the same call — the summary
    *text* is produced later by M2/M6; this only guarantees storage exists immediately.
    """
    result = await apply_transition(
        session, ticket_id=ticket_id, to_state=TicketState.ESCALATED,
        actor=actor, expected_from=expected_from,
    )
    if result.applied:
        await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(priority=priority))
        session.add(ResolutionSummary(ticket_id=ticket_id, type="escalation", summary=None))
        await emit(
            session,
            event_type="ticket.escalation_summary.requested",
            payload={"ticket_id": str(ticket_id)},
            dedupe_key=f"escalation_summary:{ticket_id}",
        )
    return result


async def claim_ticket(
    session: AsyncSession, *, ticket_id: uuid.UUID, agent_staff_id: uuid.UUID
) -> TransitionResult:
    """``escalated -> with_agent`` claim [IMP-ESC-2]. A single guarded CAS sets BOTH the state
    and the assignee atomically — ``apply_transition`` alone can't (it only sets state +
    timestamps) — but the whitelist is still asserted first and the same ``TicketEvent`` audit
    row is written on success.

    ``AND assignee_id IS NULL`` is defence-in-depth: the state-only condition
    (``state='escalated'``) already prevents a double-claim by itself, since the loser's match
    fails the instant the winner's UPDATE lands (0 rows -> caller returns 409 + current holder).
    """
    assert_allowed(TicketState.ESCALATED, TicketState.WITH_AGENT, Actor.AGENT)
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.state == TicketState.ESCALATED.value,
            Ticket.assignee_id.is_(None),
        )
        .values(state=TicketState.WITH_AGENT.value, assignee_id=agent_staff_id, updated_at=now)
    )
    applied = result.rowcount == 1
    if applied:
        session.add(
            TicketEvent(
                ticket_id=ticket_id, from_state=TicketState.ESCALATED.value,
                to_state=TicketState.WITH_AGENT.value, actor=Actor.AGENT.value,
            )
        )
    return TransitionResult(
        applied=applied, from_state=TicketState.ESCALATED, to_state=TicketState.WITH_AGENT
    )


async def release_ticket(
    session: AsyncSession, *, ticket_id: uuid.UUID, agent_staff_id: uuid.UUID
) -> TransitionResult:
    """``with_agent -> escalated`` — an agent hands a ticket back to the queue. The API layer
    checks the caller is the current holder for a clean 403 message; this re-checks
    ``assignee_id`` in the CAS itself so a stale client can never release a ticket someone else
    has since claimed. Re-stamps ``escalated_at`` to "now" — a released ticket re-enters the
    queue with a fresh wait clock rather than an ever-growing one from its original escalation.
    """
    assert_allowed(TicketState.WITH_AGENT, TicketState.ESCALATED, Actor.AGENT)
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.state == TicketState.WITH_AGENT.value,
            Ticket.assignee_id == agent_staff_id,
        )
        .values(
            state=TicketState.ESCALATED.value, assignee_id=None,
            updated_at=now, escalated_at=now,
        )
    )
    applied = result.rowcount == 1
    if applied:
        session.add(
            TicketEvent(
                ticket_id=ticket_id, from_state=TicketState.WITH_AGENT.value,
                to_state=TicketState.ESCALATED.value, actor=Actor.AGENT.value,
            )
        )
    return TransitionResult(
        applied=applied, from_state=TicketState.WITH_AGENT, to_state=TicketState.ESCALATED
    )


async def reopen_ticket(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    actor: Actor,
    reopen_window_seconds: int,
) -> TransitionResult:
    """[IMP-TKT-4] Reopen a ``resolved``/``closed`` ticket, anchored on ``closed_at`` (a merely
    `resolved`-not-yet-`closed` ticket is always eligible — the 72h clock only starts once it's
    actually closed).

    ``REOPENED`` has no fixed outbound edge on its own — it's "recompute where this goes" — so
    this persists ``prior_state``/``prior_assignee_id`` and immediately routes onward in the
    same call: within the window AND the ticket previously had an assignee -> back to
    ``with_agent`` (reassign); otherwise -> ``ai_handling``, treated as a fresh AI conversation.

    The plan calls the beyond-window case "a fresh ticket"; the frozen
    ``UNIQUE(tenant_id, conversation_id)`` constraint makes one-ticket-per-conversation a
    deliberate, accepted POC simplification (see ``00_TEAM_TASK_SPLIT.md``), so "fresh" is
    implemented as resetting THIS ticket back into ``ai_handling`` rather than a second row.
    """
    ticket = (await session.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one_or_none()
    if ticket is None or ticket.state not in (TicketState.RESOLVED.value, TicketState.CLOSED.value):
        return TransitionResult(applied=False, from_state=TicketState.REOPENED, to_state=TicketState.REOPENED)

    from_state = TicketState(ticket.state)
    result = await apply_transition(
        session, ticket_id=ticket_id, to_state=TicketState.REOPENED,
        actor=actor, expected_from=from_state,
    )
    if not result.applied:
        return result

    had_agent = ticket.assignee_id is not None
    await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id)
        .values(prior_state=from_state.value, prior_assignee_id=ticket.assignee_id)
    )

    # A merely `resolved`-not-yet-`closed` ticket (closed_at is still None) is always eligible —
    # the 72h clock hasn't started yet. It only turns "beyond window" once `closed_at` is set
    # and that far in the past.
    within_window = (
        ticket.closed_at is None
        or (datetime.now(timezone.utc) - ticket.closed_at).total_seconds() <= reopen_window_seconds
    )

    if within_window and had_agent:
        # assignee_id was never cleared by resolve/close, so it's already the prior agent —
        # TODO(Phase 3 / M7 presence): route to `escalated` instead if that agent is now Away,
        # rather than silently reassigning a possibly-absent one.
        await apply_transition(
            session, ticket_id=ticket_id, to_state=TicketState.WITH_AGENT,
            actor=Actor.SYSTEM, expected_from=TicketState.REOPENED,
        )
    else:
        await apply_transition(
            session, ticket_id=ticket_id, to_state=TicketState.AI_HANDLING,
            actor=Actor.SYSTEM, expected_from=TicketState.REOPENED,
        )
    return result


async def sweep_idle_ai_handling_to_resolved(session: AsyncSession, *, idle_seconds: int) -> int:
    """[IMP-WRK-3] Query-driven, idempotent sweep: auto-resolve every ``ai_handling`` ticket
    idle past ``idle_seconds``. Anchored on ``last_customer_msg_at``, falling back to
    ``updated_at`` until M2 populates that column, so a normal in-progress conversation is
    never swept mid-turn. Goes through the same guarded CAS as every other transition, so it's
    safe to run concurrently with an incoming-message handler — a missed Beat tick self-corrects
    on the next one, and nothing double-fires.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=idle_seconds)
    candidate_ids = (
        await session.execute(
            select(Ticket.id).where(
                Ticket.state == TicketState.AI_HANDLING.value,
                func.coalesce(Ticket.last_customer_msg_at, Ticket.updated_at) <= cutoff,
            )
        )
    ).scalars().all()
    applied = 0
    for ticket_id in candidate_ids:
        result = await resolve_ticket(
            session, ticket_id=ticket_id, actor=Actor.SYSTEM,
            expected_from=TicketState.AI_HANDLING,
        )
        if result.applied:
            applied += 1
    return applied


async def sweep_idle_resolved_to_closed(session: AsyncSession, *, idle_seconds: int) -> int:
    """[IMP-WRK-3] Auto-close every ``resolved`` ticket idle past ``idle_seconds`` from
    ``resolved_at``. Same query-driven, guarded-CAS pattern as the resolve sweep above."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=idle_seconds)
    candidate_ids = (
        await session.execute(
            select(Ticket.id).where(
                Ticket.state == TicketState.RESOLVED.value,
                Ticket.resolved_at <= cutoff,
            )
        )
    ).scalars().all()
    applied = 0
    for ticket_id in candidate_ids:
        result = await apply_transition(
            session, ticket_id=ticket_id, to_state=TicketState.CLOSED,
            actor=Actor.SYSTEM, expected_from=TicketState.RESOLVED,
        )
        if result.applied:
            applied += 1
    return applied
