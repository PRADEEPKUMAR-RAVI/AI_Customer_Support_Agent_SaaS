"""M2 — the conversation turn orchestrator (session/idempotency, state gate, persist, stream).

Flow per inbound message:
  1. idempotency SETNX on (tenant, conversation, client_msg_id) — a duplicate replays, never
     re-runs the loop ([IMP-ENG-4]); single-active-turn Redis lock ([IMP-ENG-5]).
  2. in ONE tenant-scoped transaction: load conversation+ticket, persist the customer message,
     apply the ticket-state gate ([IMP-TKT-1] — the AI stays silent only once a HUMAN agent has
     actually replied; escalated/claimed-but-silent tickets are still AI-answered so the customer
     isn't left waiting), run the engine, persist the AI message + turn_metric, and drive the
     ticket transitions via guarded CAS (new→ai_handling; escalate dominates → escalated). Commit.
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

from app.core.config import TenantDefaults, estimate_cost_usd
from app.core.latency import atimed, log_latency
from app.domain.escalation.reasons import EscalationReason
from app.domain.ticketing.states import Actor, TicketState
from app.infra.cache.redis import get_redis
from app.infra.db.models.conversation import Conversation, Message
from app.infra.db.models.tenant import AgentSettings, Tenant
from app.infra.db.session import with_tenant
from app.schemas.metrics import ModelCost, TurnMetricDTO
from app.services import escalation_service, knowledge_service, tag_service, ticket_service
from app.services.ai_engine import engine
from app.services.analytics_service import record_turn_metric
from app.services.ai_engine.guardrails import CONTACT_EMAIL_SAVED
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
# Loose finder for an email embedded in free text (e.g. "my email is a@b.com"). Trailing
# sentence punctuation is stripped by the caller.
_EMAIL_SEARCH_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def _extract_email(text: str) -> str | None:
    """First email-looking token in ``text``, or None. Strips trailing sentence punctuation the
    loose pattern may have swept up (``a@b.com.`` → ``a@b.com``)."""
    m = _EMAIL_SEARCH_RE.search(text or "")
    return m.group(0).strip(" .,;:!?)\"'") if m else None


async def _agent_has_replied(session, conversation_id) -> bool:
    """True once a HUMAN support agent has posted at least one message in this conversation — the
    single signal that a human has actually taken over. The AI stays silent from that point on
    ([IMP-TKT-1]); merely being queued (``escalated``) or claimed (``with_agent``) does NOT silence
    the AI, so the customer keeps getting help while they wait for the agent's first reply."""
    row = (
        await session.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation_id, Message.role == "agent")
            .limit(1)
        )
    ).first()
    return row is not None


@dataclass
class WidgetCtx:
    tenant_id: str
    session_id: str
    conversation_id: str


def _chunk_tokens(text: str, size: int = 6):
    """Split the answer into ~``size``-word streaming chunks WITHOUT collapsing whitespace.

    The client renders the answer as Markdown, so newlines — which delimit headings, list items,
    table rows and paragraphs — must survive to the browser. The old ``text.split()`` +
    ``" ".join(...)`` flattened the whole answer onto ONE line, so Markdown lost all block
    structure and list/table markers (``1.`` ``-`` ``|``) showed up as raw characters. Here each
    token keeps its trailing whitespace, so re-joining is lossless. (Token text is JSON-encoded on
    the wire by ``to_sse_frame``, so embedded newlines are escaped and decoded back on the client.)
    """
    tokens = re.findall(r"\S+\s*", text)
    for i in range(0, len(tokens), size):
        chunk = "".join(tokens[i : i + size])
        if chunk:
            yield chunk


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
    ticket = await ticket_service.get_or_create_ticket(session, conversation_id=conv.id)
    ticket.last_customer_msg_at = now
    if not ticket.language:
        ticket.language = conv.language

    # Contact email supplied out-of-band by the client (the request field) — a plain, non-LLM
    # field write. Kept distinct from any verified linked-record identity.
    if contact_email and _looks_like_email(contact_email):
        ticket.contact_email = contact_email.strip()

    # [§4.2.2] Customer re-message on a resolved/closed ticket reopens the SAME conversation
    # (within 72h → prior agent if it had one, else back to the AI). Done BEFORE the state gate
    # so the resumed state (ai_handling / with_agent) is what the gate below then sees.
    if ticket.state in (TicketState.RESOLVED.value, TicketState.CLOSED.value):
        await ticket_service.reopen_ticket(
            session, ticket_id=ticket.id, actor=Actor.CUSTOMER,
            reopen_window_seconds=int(
                cfg.get("reopen_window_seconds", TenantDefaults.REOPEN_WINDOW_SECONDS)
            ),
        )
        await session.refresh(ticket)

    # Snapshot the state this message arrived in, BEFORE any transition this turn drives. "Handed
    # off" = the ticket is already escalated (queued) or claimed (with_agent) — a human hand-off is
    # in flight, even though no agent has necessarily spoken yet.
    entry_state = ticket.state
    handed_off = entry_state in (TicketState.ESCALATED.value, TicketState.WITH_AGENT.value)

    # [A15] Capture a contact email from the message TEXT while a hand-off is in flight — the
    # "share your email" round-trip (after-hours escalation prompts the customer for it). A plain
    # field write, never an LLM turn, so the agent's later reply can be emailed to the customer
    # (agents.py reply → email.customer_reply, gated on ticket.contact_email). Only when we don't
    # already hold one, and only while handed off, so a normal AI turn never quietly harvests an
    # address a customer merely mentioned in a question.
    captured_email = False
    if handed_off and not ticket.contact_email:
        found = _extract_email(user_text)
        if found:
            ticket.contact_email = found
            captured_email = True

    # State gate ([IMP-TKT-1], revised): the AI stays silent ONLY once a HUMAN agent has actually
    # replied in this conversation — not merely because the ticket is queued or claimed. While a
    # customer waits for the agent's first message the AI keeps helping, so nobody is left in
    # silence. The customer's message is persisted (above) so the agent sees it; the agent's
    # replies reach the customer via the widget's live poll, and the widget drops the (empty)
    # assistant bubble for this silent turn.
    if await _agent_has_replied(session, conv.id):
        await session.flush()
        return [DoneEvent(turn_id="", ticket_state=ticket.state)]

    # If the customer just handed us their contact email (and nothing else) while waiting for a
    # human, acknowledge it deterministically and skip the engine — there's no question to answer,
    # and a code-owned reply can't fabricate a fact. Persisted so a reconnect replays it.
    if captured_email and _looks_like_email(user_text.strip()):
        return await _persist_simple_ai_turn(
            session, conv, client_msg_id, CONTACT_EMAIL_SAVED, ticket.state
        )

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
    # Cross-turn slot memory: the lookup key the customer gave on an earlier turn (persisted on the
    # last AI message), so the engine can finish the lookup once they add the verify value.
    pending_lookup = (last_ai.structured_out or {}).get("pending_lookup") if last_ai else None

    async with atimed("engine.run_turn", conv=conv.id):
        result = await engine.run_turn(
            session, cfg=cfg, industry=tenant.industry, user_text=user_text, tenant_id=ctx.tenant_id,
            escalate_request=escalate_request, human_offer_pending=human_offer_pending,
            established_language=conv.language, history=history, pending_lookup=pending_lookup,
        )

    conv.language = result.detected_language
    if not ticket.language:
        ticket.language = result.detected_language

    # Transitions via P3's M5/M6 service API (all guarded CAS; escalate dominates [IMP-TKT-3]).
    # new -> ai_handling on the first AI response (idempotent no-op on later turns).
    await ticket_service.start_ai_handling(session, ticket_id=ticket.id)
    answer_text = result.answer
    # Escalate only if the ticket wasn't ALREADY handed off when this turn began. If it was, the AI
    # was helping while the customer waits for the agent (see the state gate above); re-running the
    # hand-off would be a no-op CAS anyway and would waste a retrieval rebuilding the summary.
    if result.escalate and result.escalation_reason is not None and not handed_off:
        # [IMP-ESC-6] M2 produces the agent-facing hand-off context (why + KB sources used +
        # grounding-gated suggested reply + linked-record ref); M6 stores it on the summary row.
        summary_context = await _build_escalation_context(
            session, cfg=cfg, user_text=user_text, reason=result.escalation_reason,
            citations=result.citations, verified_record=result.verified_record,
            turns=len(history) + 1,
        )
        # Delegate the whole hand-off to M6: it does the ai_handling -> escalated CAS, sets
        # priority [C4], fills the escalation-summary row, and (after-hours) emits the single
        # support-notify email — replacing P1's earlier inline block. M2 supplies reason + context.
        handoff = await escalation_service.escalate(
            session, ticket_id=ticket.id, tenant_id=ctx.tenant_id,
            reason=result.escalation_reason, summary_context=summary_context,
        )
        # After-hours (no agent available): surface M6's "leave your email — {SLA}" prompt to the
        # customer instead of the engine's generic hand-off line ([A15]/§4.5.1). The queued case
        # keeps the engine's reason-specific message (e.g. dispute hand-off).
        if handoff.applied and handoff.mode == "after_hours" and handoff.customer_message:
            answer_text = handoff.customer_message
    # The service calls UPDATE by id; refresh the loaded object so the SSE `done` event and the
    # returned events below report the ticket's true post-transition state.
    await session.refresh(ticket)

    # PRD §4.2: set the single nullable linked-record pointer AFTER a verified lookup (never a copy
    # of the record's fields; a merely-mentioned/unverified id leaves it null). Refreshed object,
    # so this mutation is flushed on commit.
    if result.verified_record:
        ticket.linked_record_type = result.verified_record.get("type")
        ticket.linked_record_key = result.verified_record.get("key")

    tags = clamp_tags(result.tags_raw, cfg.get("allowed_tags", []))
    # [§4.2.3] Persist the AI's tags to tag_def/ticket_tag so they actually land on the ticket
    # (curated → approved; novel → pending, surfaced in the admin tray). Idempotent per
    # (ticket, tag). Previously the tags were only echoed into structured_out and never applied.
    _allowed_norm = [a.strip().lower() for a in cfg.get("allowed_tags", [])]
    for _t in tags:
        await tag_service.propose_tag(
            session, ticket_id=ticket.id, name=_t.name, allowed_tags=_allowed_norm
        )
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
        "pending_lookup": result.pending_lookup,  # cross-turn: remembered lookup key (never verify value)
    }
    ai_msg = Message(conversation_id=conv.id, role="ai", content=answer_text,
                     structured_out=structured_out, client_msg_id=client_msg_id)
    session.add(ai_msg)
    await session.flush()

    # Whole-turn latency: because the SSE stream is computed-then-streamed, this ≈ time-to-first
    # token the customer perceives. Logged to the console (logger `app.latency`) next to the
    # per-phase timers above, and persisted into turn_metric for the analytics p50/p95.
    latency_ms = int((time.monotonic() - started) * 1000)
    log_latency("turn.total", latency_ms, conv=conv.id, escalate=result.escalate,
                hits=result.retrieval_hits, tools=result.tool_calls)

    # Persist metrics through the single typed write contract ([IMP-DAT-5]).
    await record_turn_metric(session, TurnMetricDTO(
        conversation_id=conv.id,
        message_id=ai_msg.id,
        detected_language=result.detected_language,
        retrieval_hits=result.retrieval_hits,
        tool_calls=result.tool_calls,
        escalated=result.escalate,
        escalation_reason=result.escalation_reason,
        latency_ms=latency_ms,
        cost=[ModelCost(
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=estimate_cost_usd(result.model, result.prompt_tokens, result.completion_tokens),
        )],
    ))

    return _build_events(result.status_stages, answer_text, result.citations, structured_out,
                         str(ai_msg.id), ticket.state)


# [IMP-ESC-6] Human-readable reason blurbs for the agent-facing escalation summary.
_REASON_BLURB = {
    EscalationReason.NO_GROUNDING: "the AI could not find a grounded answer in the knowledge base",
    EscalationReason.EXPLICIT: "the customer asked to speak with a human",
    EscalationReason.SENSITIVE: "the message matched a sensitive intent (dispute / complaint / legal / cancellation)",
    EscalationReason.DISPUTE: "a record-state dispute was detected (void warranty / delivered-not-received / cancelled-refund)",
    EscalationReason.N_FAILS: "identity verification failed the maximum number of times",
    EscalationReason.PROACTIVE: "the customer accepted the offer to connect with a human",
    EscalationReason.TIMEOUT: "the turn timed out or the engine could not complete it safely",
}


async def _build_escalation_context(
    session, *, cfg: dict, user_text: str, reason: EscalationReason, citations: list,
    verified_record: dict | None, turns: int,
) -> dict:
    """[IMP-ESC-6] The agent-facing hand-off packet stored on the escalation summary row:
    why it escalated, the KB sources the AI used this turn, a grounding-gated suggested reply
    (never an ungrounded guess), and the live linked-record ref. LLM-free, deterministic."""
    suggestion = await knowledge_service.suggested_reply(
        session, user_text, threshold=cfg.get("relevance_threshold")
    )
    blurb = _REASON_BLURB.get(reason, reason.value)
    summary = (
        f"Escalated because {blurb}. "
        f'Customer\'s latest message: "{user_text[:400]}". '
        f"Conversation length: ~{turns} message(s)."
    )
    linked_ref = None
    if verified_record:
        linked_ref = f"{verified_record.get('type')}:{verified_record.get('key')}"
    return {
        "summary": summary,
        "kb_sources": citations or [],
        "suggested_reply": suggestion.get("text") if suggestion else None,
        "linked_record_ref": linked_ref,
    }


async def _persist_simple_ai_turn(session, conv, client_msg_id, text, ticket_state) -> list:
    """Persist a deterministic, engine-free AI reply (e.g. the contact-email ack) and build its SSE
    events. No retrieval, no metadata pass, no ticket transition — a code-owned message only, so it
    can't fabricate a fact. The structured_out mirrors a normal turn's so a reconnect replays it."""
    structured_out = {
        "answer_complete": True,
        "detected_language": conv.language,
        "tags": [],
        "retrieval_hits": 0,
        "escalate": False,
        "escalation_reason": None,
        "advisory_confidence": None,
        "citations": [],
        "offered_human": False,
    }
    ai_msg = Message(conversation_id=conv.id, role="ai", content=text,
                     structured_out=structured_out, client_msg_id=client_msg_id)
    session.add(ai_msg)
    await session.flush()
    return _build_events(["generating"], text, [], structured_out, str(ai_msg.id), ticket_state)


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
