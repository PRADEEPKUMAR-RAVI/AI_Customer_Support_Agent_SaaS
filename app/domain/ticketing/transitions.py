"""The ticket-transition whitelist + the guarded compare-and-swap primitive.

This is one of the four code-enforced non-negotiables. Two layers:

  * **Pure whitelist** (``is_allowed`` / ``assert_allowed``) — no DB, fully unit-testable.
    Encodes PRD §4.2.1 exactly, including the AI-only sub-whitelist.
  * **Guarded CAS** (``apply_transition``) — the ONLY way ticket state should ever change.
    Runs ``UPDATE ticket SET state=:to WHERE id=:id AND state=:expected`` so two writers
    (e.g. the M9 idle sweep and the M2 message handler) can never both win. 0 rows affected
    means "someone already moved it" → the caller fires NO side effects. [IMP-TKT-2]
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.ticketing.states import Actor, TicketState

S = TicketState
A = Actor

# (from_state, to_state) -> set of actors permitted to perform it (PRD §4.2.1 table).
_ALLOWED: dict[tuple[TicketState, TicketState], frozenset[Actor]] = {
    (S.NEW, S.AI_HANDLING): frozenset({A.AI}),
    (S.AI_HANDLING, S.RESOLVED): frozenset({A.AI, A.SYSTEM}),  # AI closing-confirm; SYSTEM idle
    (S.AI_HANDLING, S.ESCALATED): frozenset({A.AI}),
    (S.ESCALATED, S.WITH_AGENT): frozenset({A.AGENT}),  # claim (guarded lock, M7)
    (S.WITH_AGENT, S.RESOLVED): frozenset({A.AGENT}),
    (S.WITH_AGENT, S.ESCALATED): frozenset({A.AGENT}),  # release back to the queue
    (S.RESOLVED, S.CLOSED): frozenset({A.SYSTEM}),  # idle close
    (S.RESOLVED, S.REOPENED): frozenset({A.AGENT, A.CUSTOMER}),
    (S.CLOSED, S.REOPENED): frozenset({A.AGENT, A.CUSTOMER}),
    (S.REOPENED, S.AI_HANDLING): frozenset({A.SYSTEM}),
    (S.REOPENED, S.WITH_AGENT): frozenset({A.SYSTEM}),  # route to prior agent if was escalated
}

# The AI may perform ONLY these three edges — enforced in code, never by the model (PRD §4.2.1, §6).
AI_WHITELIST: frozenset[tuple[TicketState, TicketState]] = frozenset(
    {
        (S.NEW, S.AI_HANDLING),
        (S.AI_HANDLING, S.RESOLVED),
        (S.AI_HANDLING, S.ESCALATED),
    }
)


class TransitionNotAllowed(Exception):
    """Raised when (from, to, actor) is not permitted by the whitelist."""


def is_allowed(from_state: TicketState, to_state: TicketState, actor: Actor) -> bool:
    """Pure check: is this transition permitted for this actor?"""
    actors = _ALLOWED.get((from_state, to_state))
    if actors is None or actor not in actors:
        return False
    # Defence-in-depth: the AI is hard-clamped to its three edges even if _ALLOWED changes.
    if actor is Actor.AI and (from_state, to_state) not in AI_WHITELIST:
        return False
    return True


def assert_allowed(from_state: TicketState, to_state: TicketState, actor: Actor) -> None:
    if not is_allowed(from_state, to_state, actor):
        raise TransitionNotAllowed(
            f"actor={actor.value} may not transition {from_state.value} -> {to_state.value}"
        )


@dataclass(frozen=True)
class TransitionResult:
    applied: bool  # True iff the guarded CAS changed exactly one row
    from_state: TicketState
    to_state: TicketState


async def apply_transition(
    session,  # sqlalchemy.ext.asyncio.AsyncSession
    *,
    ticket_id,
    to_state: TicketState,
    actor: Actor,
    expected_from: TicketState,
) -> TransitionResult:
    """Guarded compare-and-swap transition. The single legal way to change ticket.state.

    Validates the whitelist first (raises ``TransitionNotAllowed``), then performs a
    conditional UPDATE. Returns ``applied=False`` (fire no side effects) when another
    writer already moved the ticket out of ``expected_from``.
    """
    assert_allowed(expected_from, to_state, actor)

    # Imported lazily so the pure whitelist above stays importable without the ORM/DB.
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.infra.db.models.ticket import Ticket, TicketEvent

    now = datetime.now(timezone.utc)
    values: dict = {"state": to_state.value, "updated_at": now}
    if to_state is S.RESOLVED:
        values["resolved_at"] = now
    elif to_state is S.CLOSED:
        values["closed_at"] = now
    elif to_state is S.ESCALATED:
        values["escalated_at"] = now  # queue FIFO ordering anchor (M7)

    result = await session.execute(
        update(Ticket)
        .where(Ticket.id == ticket_id, Ticket.state == expected_from.value)
        .values(**values)
    )
    applied = result.rowcount == 1
    if applied:
        session.add(
            TicketEvent(
                ticket_id=ticket_id,
                from_state=expected_from.value,
                to_state=to_state.value,
                actor=actor.value,
            )
        )
    return TransitionResult(applied=applied, from_state=expected_from, to_state=to_state)
