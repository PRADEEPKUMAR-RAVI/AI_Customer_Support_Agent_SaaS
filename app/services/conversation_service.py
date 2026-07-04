"""M2 — the conversation turn orchestrator (session/idempotency, state gate, persist, stream).

Flow per inbound message:
  1. idempotency SETNX on (tenant, conversation, client_msg_id) — a duplicate replays, never
     re-runs the loop ([IMP-ENG-4]); single-active-turn Redis lock ([IMP-ENG-5]).
  2. in ONE tenant-scoped transaction: load conversation+ticket, persist the customer message,
     apply the ticket-state gate ([IMP-TKT-1] — AI answers only in {new, ai_handling}), run the
     engine, persist the AI message + turn_metric, and drive the ticket transitions via guarded
     CAS (new→ai_handling; escalate dominates → escalated). Commit.
  3. stream the computed SSE events (status → tokens → citations → final → done).

FakeLLM is non-streaming, so we compute-then-stream. Real token-by-token streaming (and the
per-step 20s timeout FSM) are Phase-2 hardening.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import estimate_cost_usd
from app.core.events import emit
from app.domain.escalation.reasons import EscalationReason
from app.domain.ticketing.states import Actor, TicketState
from app.infra.cache.redis import get_redis
from app.infra.db.models.conversation import Conversation, Message
from app.infra.db.models.tenant import AgentSettings, Tenant
from app.infra.db.session import with_tenant
from app.schemas.metrics import ModelCost, TurnMetricDTO
from app.services import ticket_service
from app.services.ai_engine import engine
from app.services.analytics_service import record_turn_metric
from app.services.ai_engine.guardrails import ALREADY_WITH_HUMAN
from app.services.ai_engine.structured import clamp_tags
from app.schemas.sse import (
    Citation,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    FinalEvent,
    StatusEvent,
    Tag,
    TokenEvent,
    to_sse_frame,
)

_TURN_LOCK_TTL = 30
_IDEM_TTL = 120
_HISTORY_LIMIT = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


@dataclass
class WidgetCtx:
    tenant_id: str
    session_id: str
    conversation_id: str


def _chunk_tokens(text: str, size: int = 6):
    words = text.split()
    for i in range(0, len(words), size):
        yield " ".join(words[i : i + size]) + (" " if i + size < len(words) else "")


async def _load_history(session, conversation_id) -> list[dict]:
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(_HISTORY_LIMIT)
        )
    ).scalars().all()
    role_map = {"customer": "user", "ai": "assistant", "agent": "assistant"}
    return [
        {"role": role_map.get(m.role, "user"), "content": m.content}
        for m in reversed(rows)
        if m.role in role_map
    ]


async def handle_message(ctx: WidgetCtx, *, user_text: str, client_msg_id: str,
                         escalate_request: bool, contact_email: str | None = None):
    """Async generator yielding SSE frame strings for one customer message."""
    redis = get_redis()
    idem_key = f"idem:{ctx.tenant_id}:{ctx.conversation_id}:{client_msg_id}"
    turn_key = f"turnlock:{ctx.tenant_id}:{ctx.conversation_id}"
    seq = 0

    # (1) idempotency: a duplicate client_msg_id must never re-run the loop.
    if not await redis.set(idem_key, "in_progress", nx=True, ex=_IDEM_TTL):
        async for frame in _replay_or_wait(ctx, client_msg_id):
            yield frame
        return

    if not await redis.set(turn_key, client_msg_id, nx=True, ex=_TURN_LOCK_TTL):
        await redis.delete(idem_key)
        yield to_sse_frame(ErrorEvent(code="busy", message="Another message is being processed."), 0)
        yield to_sse_frame(DoneEvent(turn_id="", ticket_state="ai_handling"), 1)
        return

    started = time.monotonic()
    try:
        events: list = []
        async with with_tenant(ctx.tenant_id) as session:
            conv = (
                await session.execute(select(Conversation).where(Conversation.id == ctx.conversation_id))
            ).scalar_one_or_none()
            if conv is None or conv.session_id != ctx.session_id:
                events = [ErrorEvent(code="not_found", message="Conversation not found."),
                          DoneEvent(turn_id="", ticket_state="")]
            else:
                events = await _run_and_persist(session, ctx, conv, user_text, client_msg_id,
                                                escalate_request, started, contact_email)
        for ev in events:
            yield to_sse_frame(ev, seq)
            seq += 1
    finally:
        await redis.delete(turn_key)


async def _run_and_persist(session, ctx, conv, user_text, client_msg_id, escalate_request, started,
                           contact_email=None) -> list:
    tenant = (await session.execute(select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one_or_none()
    if tenant is None or tenant.status != "active":
        return [ErrorEvent(code="tenant_suspended", message="This workspace is unavailable."),
                DoneEvent(turn_id="", ticket_state="")]
    cfg = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    cfg = cfg.config if cfg else {}

    now = datetime.now(timezone.utc)
    session.add(Message(conversation_id=conv.id, role="customer", content=user_text,
                        client_msg_id=client_msg_id))
    ticket = await ticket_service.get_or_create_ticket(session, conversation_id=conv.id,
                                                       language=conv.language)
    ticket.last_customer_msg_at = now

    # [A15] After-hours email capture — a non-LLM write that lands even while the ticket is
    # escalated, so a customer can leave a follow-up address without re-invoking the model (the
    # one deliberate exception to the [IMP-TKT-1] state gate). Kept distinct from any verified id.
    if contact_email and _looks_like_email(contact_email):
        ticket.contact_email = contact_email.strip()

    # State gate ([IMP-TKT-1]): once a human owns it, the AI does NOT answer.
    if ticket.state in (TicketState.ESCALATED.value, TicketState.WITH_AGENT.value):
        return await _persist_canned(session, conv, ticket, client_msg_id, ALREADY_WITH_HUMAN)

    history = await _load_history(session, conv.id)
    # [A2] did the previous AI turn offer a human? A typed "yes" now becomes a proactive escalate.
    last_ai = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "ai")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    human_offer_pending = bool(last_ai and (last_ai.structured_out or {}).get("offered_human"))

    result = await engine.run_turn(
        session, cfg=cfg, industry=tenant.industry, user_text=user_text, tenant_id=ctx.tenant_id,
        escalate_request=escalate_request, human_offer_pending=human_offer_pending,
        established_language=conv.language, history=history,
    )

    conv.language = result.detected_language
    if not ticket.language:
        ticket.language = result.detected_language

    # Transitions (guarded CAS, whitelist): AI first response → ai_handling; escalate dominates.
    if ticket.state == TicketState.NEW.value:
        await ticket_service.transition(session, ticket=ticket, to_state=TicketState.AI_HANDLING, actor=Actor.AI)
    if result.escalate and ticket.state == TicketState.AI_HANDLING.value:
        await ticket_service.transition(session, ticket=ticket, to_state=TicketState.ESCALATED, actor=Actor.AI)
        # priority per trigger ([C4]); support-notify email via the outbox → M9 sends it.
        # (person-3's M6 will own the full escalation routing, incl. presence + after-hours SLA.)
        ticket.priority = "high" if result.escalation_reason in (
            EscalationReason.SENSITIVE, EscalationReason.DISPUTE) else "normal"
        support_to = cfg.get("support_notification_email") or "support@tenant.local"
        await emit(
            session,
            event_type="escalation.support_notify",
            payload={"to": support_to, "ticket_id": str(ticket.id),
                     "reason": result.escalation_reason.value if result.escalation_reason else "escalated"},
            dedupe_key=f"escalation:{ticket.id}",
        )

    tags = clamp_tags(result.tags_raw, cfg.get("allowed_tags", []))
    structured_out = {
        "answer_complete": result.answer_complete,
        "detected_language": result.detected_language,
        "tags": [t.model_dump() for t in tags],
        "retrieval_hits": result.retrieval_hits,
        "escalate": result.escalate,
        "escalation_reason": result.escalation_reason.value if result.escalation_reason else None,
        "advisory_confidence": result.advisory_confidence,
        "citations": result.citations,
        "offered_human": result.offered_human,  # [A2] cross-turn: next turn treats "yes" as acceptance
    }
    ai_msg = Message(conversation_id=conv.id, role="ai", content=result.answer,
                     structured_out=structured_out, client_msg_id=client_msg_id)
    session.add(ai_msg)
    await session.flush()

    # Persist metrics through the single typed write contract ([IMP-DAT-5]).
    await record_turn_metric(session, TurnMetricDTO(
        conversation_id=conv.id,
        message_id=ai_msg.id,
        detected_language=result.detected_language,
        retrieval_hits=result.retrieval_hits,
        tool_calls=result.tool_calls,
        escalated=result.escalate,
        escalation_reason=result.escalation_reason,
        latency_ms=int((time.monotonic() - started) * 1000),
        cost=[ModelCost(
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=estimate_cost_usd(result.model, result.prompt_tokens, result.completion_tokens),
        )],
    ))

    return _build_events(result.status_stages, result.answer, result.citations, structured_out,
                         str(ai_msg.id), ticket.state)


async def _persist_canned(session, conv, ticket, client_msg_id, text) -> list:
    ai_msg = Message(conversation_id=conv.id, role="ai", content=text, client_msg_id=client_msg_id,
                     structured_out={"answer_complete": False, "detected_language": conv.language or "en",
                                     "tags": [], "retrieval_hits": 0, "escalate": False,
                                     "escalation_reason": None, "advisory_confidence": None,
                                     "citations": [], "offered_human": False})
    session.add(ai_msg)
    await session.flush()
    return _build_events(["generating"], text, [],
                         ai_msg.structured_out, str(ai_msg.id), ticket.state)


def _build_events(stages, answer, citations, structured_out, turn_id, ticket_state) -> list:
    events: list = [StatusEvent(stage=s) for s in stages]
    for chunk in _chunk_tokens(answer):
        events.append(TokenEvent(text=chunk))
    for c in citations:
        events.append(CitationEvent(citation=Citation(**c)))
    events.append(FinalEvent(
        answer_complete=structured_out["answer_complete"],
        detected_language=structured_out["detected_language"],
        tags=[Tag(**t) for t in structured_out["tags"]],
        retrieval_hits=structured_out["retrieval_hits"],
        escalate=structured_out["escalate"],
        escalation_reason=structured_out["escalation_reason"],
        advisory_confidence=structured_out["advisory_confidence"],
    ))
    events.append(DoneEvent(turn_id=turn_id, ticket_state=ticket_state))
    return events


async def _replay_or_wait(ctx: WidgetCtx, client_msg_id: str):
    """Duplicate client_msg_id: replay the persisted AI answer if it exists, else say we're
    still processing. Never re-runs the tool loop (no double escalate/ticket/metric)."""
    async with with_tenant(ctx.tenant_id) as session:
        ai_msg = (
            await session.execute(
                select(Message).where(
                    Message.conversation_id == ctx.conversation_id,
                    Message.client_msg_id == client_msg_id,
                    Message.role == "ai",
                )
            )
        ).scalar_one_or_none()
        ticket_state = "ai_handling"
    seq = 0
    if ai_msg is not None:
        for ev in _build_events(["generating"], ai_msg.content, ai_msg.structured_out.get("citations", []),
                                ai_msg.structured_out, str(ai_msg.id), ticket_state):
            yield to_sse_frame(ev, seq)
            seq += 1
    else:
        yield to_sse_frame(StatusEvent(stage="waiting"), 0)
        yield to_sse_frame(DoneEvent(turn_id="", ticket_state=ticket_state), 1)
