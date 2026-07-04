"""M2 — the bounded, grounded agentic turn.

Runs a bounded tool loop on the LLM, but the code (not the model) makes every safety decision:
the grounding gate, escalate-dominates, the language rule, tag clamping, the deterministic
record-state dispute escalation ([A1]), and the per-step stall/timeout guard ([IMP-ENG-3]).
Verification + the durable attempt lockout run in the lookup_record tool. This function is PURE
reasoning over a read session — it performs no writes and no ticket transitions; the conversation
service persists + transitions afterward.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from app.core.config import TenantDefaults
from app.domain.escalation.reasons import EscalationReason
from app.domain.ticketing.states import TicketState
from app.infra.llm.model_router import get_llm
from app.schemas.records import LookupStatus
from app.services.ai_engine.grounding import decide_outcome
from app.services.ai_engine.guardrails import (
    DISPUTE_HANDOFF,
    ENGINE_GUARD_HANDOFF,
    HUMAN_TAKING_OVER,
    KB_NOT_READY_MSG,
    PROACTIVE_OFFER,
    VERIFY_LOCKED,
    delimit_tool_result,
)
from app.services.ai_engine.prompts import build_system_prompt
from app.services.ai_engine.structured import TURN_METADATA_SCHEMA, TurnMetadata
from app.services.ai_engine.tools import TOOL_SPECS, escalate_tool, kb_retrieve_tool, lookup_record_tool
from app.services.knowledge_service import GroundedResult


@dataclass
class TurnResult:
    answer: str
    citations: list = field(default_factory=list)
    detected_language: str = "en"
    answer_complete: bool = False
    tags_raw: list[str] = field(default_factory=list)
    retrieval_hits: int = 0
    escalate: bool = False
    escalation_reason: EscalationReason | None = None
    advisory_confidence: float | None = None
    tool_calls: int = 0
    status_stages: list[str] = field(default_factory=list)
    target_state: TicketState = TicketState.AI_HANDLING
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    offered_human: bool = False  # [A2] this turn offered a human — persisted so the next turn knows


class _Stalled(Exception):
    """A single model step exceeded its budget after all stall retries ([IMP-ENG-3])."""


# [A2] tight affirmative set — a typed "yes" to a pending human-offer. The widget's talk-to-human
# button remains the primary path (escalate_request → EXPLICIT); this covers free-text acceptance.
_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please", "yes please", "connect me",
    "connect", "human", "agent", "talk to a human", "talk to human", "y", "affirmative",
}


def _is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower().rstrip("!. ")
    return t in _AFFIRMATIVE or t.startswith("yes")


def _dedup(seq: list[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        if not out or out[-1] != s:
            out.append(s)
    return out


def _summarize_kb(out) -> dict | str:
    if isinstance(out, GroundedResult):
        return {"chunks": [c["content"] for c in out.chunks]}
    return out  # signal string


async def _complete_within(llm, messages, *, budget: float, retries: int, **kw):
    """One model step bounded to ``budget`` seconds ([IMP-ENG-3]/[A16]): the per-step budget is
    time-to-first-token, not whole-turn. A stalled step is retried ``retries`` times; exhausting
    them raises ``_Stalled`` so the caller can fail safe to a human."""
    attempt = 0
    while True:
        try:
            return await asyncio.wait_for(llm.complete(messages, **kw), timeout=budget)
        except (asyncio.TimeoutError, TimeoutError):
            if attempt >= retries:
                raise _Stalled from None
            attempt += 1


async def run_turn(
    session,
    *,
    cfg: dict,
    industry: str,
    user_text: str,
    tenant_id: str = "",
    escalate_request: bool = False,
    human_offer_pending: bool = False,
    established_language: str | None = None,
    history: list[dict] | None = None,
) -> TurnResult:
    default_lang = cfg.get("default_language", "en")
    supported = cfg.get("supported_languages", ["en"])
    threshold = cfg.get("relevance_threshold")
    max_calls = int(cfg.get("max_tool_calls_per_turn", TenantDefaults.MAX_TOOL_CALLS_PER_TURN))
    budget = float(cfg.get("per_step_budget_seconds", TenantDefaults.PER_STEP_BUDGET_SECONDS))
    stall_retries = int(cfg.get("stall_retries", TenantDefaults.STALL_RETRIES))
    escalate_on_timeout = bool(cfg.get("escalate_on_timeout", TenantDefaults.ESCALATE_ON_TIMEOUT))

    # First-class "talk to a human" → deterministic escalate, no model call ([IMP-ESC-5]).
    if escalate_request:
        return TurnResult(
            answer=HUMAN_TAKING_OVER,
            detected_language=established_language or default_lang,
            escalate=True,
            escalation_reason=EscalationReason.EXPLICIT,
            status_stages=["generating"],
            target_state=TicketState.ESCALATED,
        )

    llm = get_llm()
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(cfg)}]
    messages += history or []
    messages.append({"role": "user", "content": user_text})

    grounded = None
    kb_signal: str | None = None
    record_result: dict | None = None
    model_escalate: dict | None = None
    tool_calls = 0
    stages: list[str] = []
    final = None
    p_tok = c_tok = 0
    model_name = ""

    def _guard_handoff(reason: EscalationReason) -> TurnResult:
        """Fail-safe turn when the engine can't finish safely (stall / unusable envelope)."""
        return TurnResult(
            answer=ENGINE_GUARD_HANDOFF,
            detected_language=established_language or default_lang,
            escalate=True, escalation_reason=reason,
            status_stages=_dedup(stages + ["generating"]),
            target_state=TicketState.ESCALATED,
            tool_calls=tool_calls, prompt_tokens=p_tok, completion_tokens=c_tok, model=model_name,
        )

    # Bounded tool loop ([IMP-ENG-2]); +1 so a final answer pass follows the last allowed tool.
    # No response_schema here — the loop only calls tools / produces the answer text ([IMP-ENG-1]).
    try:
        for _ in range(max_calls + 1):
            res = await _complete_within(llm, messages, budget=budget, retries=stall_retries,
                                         tools=TOOL_SPECS, temperature=0)
            p_tok += res.prompt_tokens
            c_tok += res.completion_tokens
            model_name = res.model or model_name

            if res.tool_calls and tool_calls < max_calls:
                # Thread the assistant tool-call message BEFORE the tool responses (OpenAI protocol;
                # harmless for FakeLLM). Each tool response carries its tool_call_id.
                messages.append({
                    "role": "assistant",
                    "content": res.text or None,
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in res.tool_calls
                    ],
                })
                for tc in res.tool_calls:
                    tool_calls += 1
                    if tc.name == "kb_retrieve":
                        stages.append("retrieving")
                        out = await kb_retrieve_tool(session, tc.arguments, threshold=threshold)
                        if isinstance(out, GroundedResult):
                            grounded = out
                        else:
                            kb_signal = out
                        payload = _summarize_kb(out)
                    elif tc.name == "lookup_record":
                        stages.append("looking_up")
                        record_result = await lookup_record_tool(
                            session, tc.arguments, industry=industry,
                            tenant_id=tenant_id, user_text=user_text,
                        )
                        payload = record_result
                    elif tc.name == "escalate":
                        model_escalate = escalate_tool(tc.arguments)
                        payload = model_escalate
                    else:
                        payload = {"error": "unknown tool"}
                    messages.append(delimit_tool_result(tc.name, payload, tool_call_id=tc.id))
                continue
            final = res
            break
    except _Stalled:
        if escalate_on_timeout:
            return _guard_handoff(EscalationReason.TIMEOUT)  # [IMP-ENG-3]
        # else: fall through with no answer → the grounding gate will escalate NO_GROUNDING.
    stages.append("generating")

    model_answer = final.text if final else ""

    # Pattern A ([IMP-ENG-1]): a cheap structured pass for the control metadata, VALIDATED then
    # RETRIED once. If it still can't produce a usable envelope AND there's nothing grounded to
    # stand on, fail safe to a human rather than shipping a turn on untrusted control fields.
    model_meta = TurnMetadata()
    meta_ok = False
    for _ in range(2):  # 1 try + 1 retry
        try:
            meta_res = await _complete_within(
                llm, messages + [{"role": "assistant", "content": model_answer}],
                budget=budget, retries=0, response_schema=TURN_METADATA_SCHEMA, temperature=0,
            )
            p_tok += meta_res.prompt_tokens
            c_tok += meta_res.completion_tokens
            if meta_res.structured:
                model_meta = TurnMetadata.model_validate(meta_res.structured)
                meta_ok = True
                break
        except Exception:  # noqa: BLE001 — TimeoutError/validation/parse all retry then fail safe
            continue

    outcome = decide_outcome(
        grounded=grounded, kb_signal=kb_signal, model_answer=model_answer,
        record_result=record_result,
    )
    answer_text = outcome.answer
    escalate, reason = outcome.escalate, outcome.reason
    grounded_answer = isinstance(grounded, GroundedResult) and bool(grounded.chunks)
    offered_human = False

    # A model-requested hand-off is a soft (sensitive) escalate; the engine still owns the action.
    if model_escalate and not escalate:
        escalate, reason = True, EscalationReason.SENSITIVE

    # [IMP-SEC-6] a locked-out verify attempt hands off (unless the KB already answered the turn).
    if (record_result and record_result.get("status") == LookupStatus.RATE_LIMITED.value
            and not grounded_answer):
        escalate, reason, answer_text = True, EscalationReason.SENSITIVE, VERIFY_LOCKED

    # [A1] deterministic record-state dispute → code-driven escalate (dominates). A cancelled-order
    # refund is a dispute only when the KB can't already answer the refund question.
    dispute = record_result.get("dispute") if record_result else None
    if dispute and (dispute != "cancelled_refund" or not grounded_answer):
        escalate, reason, answer_text = True, EscalationReason.DISPUTE, DISPUTE_HANDOFF

    # [IMP-ENG-1] unusable control envelope after a retry, and no grounded/record answer to keep →
    # hand to a human instead of shipping defaults on a turn we couldn't reason about.
    if (not meta_ok and escalate_on_timeout and not escalate and not grounded_answer
            and not (record_result and record_result.get("status") == LookupStatus.OK.value)):
        escalate, reason, answer_text = True, EscalationReason.TIMEOUT, ENGINE_GUARD_HANDOFF

    # [A2] Proactive human offer. Instead of hard-escalating the FIRST ungrounded turn, offer a
    # human and remember it (offered_human). If a prior turn already offered, a typed "yes" now
    # connects them (reason=proactive); otherwise the (still-ungrounded) turn hands off as usual.
    if human_offer_pending and _is_affirmative(user_text) and reason in (None, EscalationReason.NO_GROUNDING):
        escalate, reason, answer_text = True, EscalationReason.PROACTIVE, HUMAN_TAKING_OVER
    elif (not human_offer_pending) and escalate and reason is EscalationReason.NO_GROUNDING:
        escalate, reason, answer_text, offered_human = False, None, PROACTIVE_OFFER, True
    # KB-not-ready is already a soft offer — mark it so a following "yes" is recognised as acceptance.
    if not escalate and answer_text == KB_NOT_READY_MSG:
        offered_human = True

    # Language rule ([A3]): reply in the detected language if supported, else the tenant default.
    detected = model_meta.detected_language or established_language or default_lang
    if detected not in supported:
        detected = default_lang

    return TurnResult(
        answer=answer_text,
        citations=outcome.citations,
        detected_language=detected,
        answer_complete=(model_meta.answer_complete and not escalate),  # escalate dominates [IMP-TKT-3]
        tags_raw=model_meta.tags,
        retrieval_hits=outcome.retrieval_hits,
        escalate=escalate,
        escalation_reason=reason,
        advisory_confidence=model_meta.advisory_confidence,
        tool_calls=tool_calls,
        status_stages=_dedup(stages),
        target_state=TicketState.ESCALATED if escalate else TicketState.AI_HANDLING,
        prompt_tokens=p_tok,
        completion_tokens=c_tok,
        model=model_name,
        offered_human=offered_human,
    )
