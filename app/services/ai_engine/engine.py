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
import re
from dataclasses import dataclass, field

from app.core.config import TenantDefaults
from app.core.latency import atimed
from app.domain.escalation.reasons import EscalationReason
from app.domain.records.schemas import Industry, get_schema
from app.domain.ticketing.states import TicketState
from app.infra.llm.model_router import get_llm
from app.schemas.records import LookupStatus
from app.services.ai_engine.grounding import decide_outcome
from app.services.ai_engine.guardrails import (
    ENGINE_GUARD_HANDOFF,
    HUMAN_TAKING_OVER,
    KB_NOT_READY_MSG,
    PROACTIVE_OFFER,
    VERIFY_LOCKED,
    capability_reply,
    delimit_tool_result,
    dispute_handoff_message,
    localize,
    lookup_retry_prompt,
    out_of_scope_reply,
    slot_fill_prompt,
    slot_progress_note,
    smalltalk_reply,
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
    # PRD §4.2: the verified-lookup identity {type, key} for the ticket's linked-record pointer.
    # Set ONLY when lookup_record returned status=ok this turn (a verified match); else None.
    verified_record: dict | None = None
    # Did the CODE author this answer (a canned/schema-built reply) rather than the model? Code text
    # is always English and must be translated on the way out ([A3]); the model's own text is already
    # in the customer's language (the system prompt's language rule), so re-translating it would just
    # cost a call and paraphrase a grounded fact. See run_turn.
    code_owned: bool = True
    # Cross-turn slot memory {record_type, key_value}: the lookup KEY the customer has given but not
    # yet verified, so the next turn can finish the lookup instead of re-asking. Never the verify
    # value (PII). None once verified / not in a lookup flow. Persisted in the AI message.
    pending_lookup: dict | None = None


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


# Turn types where the ENGINE owns the reply text (a deterministic, code-built message) rather
# than the model — so on a non-grounded turn no model-authored prose (which could fabricate a
# fact) ever reaches the customer. The model only CLASSIFIES the turn; the code writes the words.
_CONVERSATIONAL_TYPES = {"needs_info", "smalltalk", "capability", "out_of_scope"}


def _conversational_reply(turn_type: str, cfg: dict, industry: str, meta) -> str:
    if turn_type == "needs_info":
        return slot_fill_prompt(industry, meta.record_type,
                                has_key=meta.has_lookup_key, has_verify=meta.has_verify_value)
    if turn_type == "smalltalk":
        return smalltalk_reply(cfg)
    if turn_type == "capability":
        return capability_reply(industry)
    if turn_type == "out_of_scope":
        return out_of_scope_reply(industry)
    return PROACTIVE_OFFER  # defensive fallback (never expected)


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


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _record_schema(industry: str, record_type: str | None):
    """The RecordSchema for (industry, record_type), or None if either is unknown."""
    try:
        return get_schema(Industry(industry), record_type or "")
    except ValueError:
        return None


def _find_email_in(history: list[dict] | None, user_text: str) -> str | None:
    """Deterministic fallback for an email verify value: scan the customer's messages (this turn
    first, then earlier) for an email address. Belt-and-suspenders behind the model's extraction so
    the common retail/order path never depends on the model echoing the value correctly."""
    texts = [user_text or ""]
    texts += [m.get("content", "") for m in (history or []) if m.get("role") == "user"]
    for t in texts:
        m = _EMAIL_RE.search(t or "")
        if m:
            return m.group(0).strip(" .,;:!?)\"'")
    return None


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


async def run_turn(session, **kw) -> TurnResult:
    """The bounded, grounded turn, then the [A3] language rule applied to the finished text.

    Localizing HERE — at the single exit — rather than at each of the ~10 places that assign
    ``answer_text`` is what makes the rule hold: the engine owns the words on most turns and every
    code-owned string is authored in English, so any path that doesn't route through here ships
    English to a non-English customer. Model-authored text is already in the customer's language and
    is left alone (``code_owned``).
    """
    result = await _run_turn(session, **kw)
    if result.code_owned:
        result.answer = await localize(result.answer, result.detected_language)
    return result


async def _run_turn(
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
    pending_lookup: dict | None = None,
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
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(cfg, industry=industry)}]
    messages += history or []
    # Cross-turn slot memory: if a record lookup is mid-flight (the customer gave the key on an
    # earlier turn but hasn't verified yet), re-state it explicitly so the model completes the lookup
    # as soon as the verify value arrives — it otherwise doesn't reliably stitch a key from an
    # earlier turn to the verify value given now, and falls back to re-asking for everything. Skipped
    # once the identity is verified ([Fix 1]) — the note is only useful while a lookup is unfinished.
    if pending_lookup and pending_lookup.get("key_value") and not pending_lookup.get("verified"):
        _note = slot_progress_note(industry, pending_lookup.get("record_type"),
                                   str(pending_lookup["key_value"]))
        if _note:
            messages.append({"role": "system", "content": _note})
    messages.append({"role": "user", "content": user_text})

    grounded = None
    kb_signal: str | None = None
    record_result: dict | None = None
    verified_record: dict | None = None  # PRD §4.2 linked-record pointer, set on a verified lookup
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
        for _step in range(max_calls + 1):
            async with atimed("engine.llm.step", step=_step + 1):
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
                        async with atimed("engine.tool.kb_retrieve"):
                            out = await kb_retrieve_tool(session, tc.arguments, threshold=threshold)
                        if isinstance(out, GroundedResult):
                            grounded = out
                        else:
                            kb_signal = out
                        payload = _summarize_kb(out)
                    elif tc.name == "lookup_record":
                        stages.append("looking_up")
                        async with atimed("engine.tool.lookup_record"):
                            record_result = await lookup_record_tool(
                                session, tc.arguments, industry=industry,
                                tenant_id=tenant_id, user_text=user_text,
                            )
                        # PRD §4.2: capture the verified identity for the ticket's linked-record
                        # pointer — set ONLY on a verified match (status=ok), never on
                        # not_found/unverified/rate_limited (a merely-mentioned id leaves it null).
                        if record_result.get("status") == LookupStatus.OK.value:
                            verified_record = {
                                "type": tc.arguments.get("record_type"),
                                "key": str(tc.arguments.get("key", "")),
                            }
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
            async with atimed("engine.llm.meta"):
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

    # ── Engine-driven record lookup (reliability fix) ─────────────────────────────────────────
    # Multi-turn lookups used to stall because completing them depended on the MODEL choosing to
    # call lookup_record once it had the key + verify value — which it does unreliably (it would
    # collect the id on one turn and the email on the next, then re-ask instead of looking up). Now
    # the model only EXTRACTS the values (lookup_key_value / verify_value, over the whole
    # conversation — a task it's reliable at), and the ENGINE performs the lookup here in code as
    # soon as both are present. Skipped if the model already looked up this turn (happy path kept),
    # or if there's no valid record type. Verification still runs in code inside lookup_record_tool.
    # record_type/key fall back to the remembered slot state, so once the key was captured on an
    # earlier turn the verify turn needs NOTHING new from the model (record_type + key from memory,
    # email from the message) — the model can whiff entirely and the lookup still completes.
    # `pending_lookup` may hold an in-progress key (given but not yet verified) OR a verified
    # identity carried from an earlier turn (verified=True), so a FOLLOW-UP lookup — including one
    # for a DIFFERENT record type, e.g. order -> warranty — reuses the key without re-asking. [Fix 1]
    _established = pending_lookup or {}
    # What to look up THIS turn: the model's classification wins; a still-in-progress (unverified)
    # remembered lookup can also trigger one (the model may whiff on the continuation turn). A
    # VERIFIED identity does NOT trigger on its own — that would re-answer unprompted — it only
    # SUPPLIES the key below when the model DOES flag a record question this turn.
    _rec_type = model_meta.record_type or (
        None if _established.get("verified") else _established.get("record_type")
    )
    if record_result is None and _rec_type:
        schema = _record_schema(industry, _rec_type)
        if schema is not None:
            key_val = model_meta.lookup_key_value or _established.get("key_value")
            verify_val = model_meta.verify_value
            if not verify_val and any(v.field == "email" for v in schema.verify):
                verify_val = _find_email_in(history, user_text)  # deterministic email fallback
            if key_val and verify_val:
                async with atimed("engine.tool.lookup_record"):
                    record_result = await lookup_record_tool(
                        session,
                        {"record_type": _rec_type, "key": str(key_val),
                         "verify_value": str(verify_val)},
                        industry=industry, tenant_id=tenant_id, user_text=user_text,
                    )
                tool_calls += 1
                if record_result.get("status") == LookupStatus.OK.value:
                    verified_record = {"type": _rec_type, "key": str(key_val)}
                # The model's pre-lookup text isn't grounded on the record, and a lookup ran, so this
                # is no longer a slot-fill turn — let decide_outcome render from the verified record.
                model_answer = ""
                model_meta.turn_type = "answer"

    outcome = decide_outcome(
        grounded=grounded, kb_signal=kb_signal, model_answer=model_answer,
        record_result=record_result,
    )
    answer_text = outcome.answer
    escalate, reason = outcome.escalate, outcome.reason
    grounded_answer = isinstance(grounded, GroundedResult) and bool(grounded.chunks)
    offered_human = False

    # [§4.5] deterministic sensitive-intent trigger — the tenant's configured keyword list
    # (refund dispute / complaint / legal / cancellation / …). A hard hand-off regardless of
    # grounding; matched here in code, not left to the model. A record-state DISPUTE (more
    # specific) still overrides this below; an explicit human request was handled up top.
    sensitive_terms = [k.strip().lower() for k in (cfg.get("sensitive_intent_list") or []) if k.strip()]
    if sensitive_terms and any(term in user_text.lower() for term in sensitive_terms):
        escalate, reason, answer_text = True, EscalationReason.SENSITIVE, HUMAN_TAKING_OVER

    # [§4.5] Customer explicitly asked IN TEXT to reach a human ("connect me with a human", "talk
    # to an agent", …) — the same deterministic hand-off as the widget's talk-to-human button, so
    # the AI can't just *say* it connected them without the ticket actually escalating. Guarded so
    # a more-specific reason (dispute/sensitive set above) still dominates; otherwise this beats
    # no-grounding / the proactive offer.
    if model_meta.turn_type == "human_request" and reason in (None, EscalationReason.NO_GROUNDING):
        escalate, reason, answer_text = True, EscalationReason.EXPLICIT, HUMAN_TAKING_OVER

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
        # [Fix 2a] tell the customer WHY we're bringing in a human, not a generic line.
        escalate, reason, answer_text = True, EscalationReason.DISPUTE, dispute_handoff_message(dispute)

    # [IMP-ENG-1] unusable control envelope after a retry, and no grounded/record answer to keep →
    # hand to a human instead of shipping defaults on a turn we couldn't reason about.
    if (not meta_ok and escalate_on_timeout and not escalate and not grounded_answer
            and not (record_result and record_result.get("status") == LookupStatus.OK.value)):
        escalate, reason, answer_text = True, EscalationReason.TIMEOUT, ENGINE_GUARD_HANDOFF

    # A record lookup that returned not_found / unverified is RETRYABLE, not a dead end: give the
    # customer the SAME neutral message for both (no enumeration oracle, §4.8.2) so they can correct
    # a typo and try again, instead of being escalated to a human for a mistyped detail. The durable
    # attempt counter still escalates (rate_limited, handled above) once the cap is hit.
    _rec_status = record_result.get("status") if record_result else None
    if (_rec_status in (LookupStatus.NOT_FOUND.value, LookupStatus.UNVERIFIED.value)
            and not grounded_answer and reason in (None, EscalationReason.NO_GROUNDING)):
        escalate, reason, answer_text = False, None, lookup_retry_prompt(industry, _rec_type)

    # [A2] Proactive human offer. Instead of hard-escalating the FIRST ungrounded turn, offer a
    # human and remember it (offered_human). If a prior turn already offered, a typed "yes" now
    # connects them (reason=proactive); otherwise the (still-ungrounded) turn hands off as usual.
    if human_offer_pending and _is_affirmative(user_text) and reason in (None, EscalationReason.NO_GROUNDING):
        escalate, reason, answer_text = True, EscalationReason.PROACTIVE, HUMAN_TAKING_OVER
    elif reason is EscalationReason.NO_GROUNDING and model_meta.turn_type in _CONVERSATIONAL_TYPES:
        # [§4.8 / scope] Not a grounded factual ANSWER — the model classified it as record
        # slot-filling, small talk, a capability/self question, or out-of-scope.
        #   * SLOT-FILLING (needs_info): ship a DETERMINISTIC, schema-derived prompt — NEVER model
        #     free text. This is the highest fabrication-risk path (the safety review showed the
        #     model can smuggle a fake order/ETA into a "question"), so the code owns the words.
        #   * SMALL TALK / CAPABILITY / OUT-OF-SCOPE: relay the model's NATURAL reply so it doesn't
        #     sound robotic. These assert no business facts; the system prompt forbids stating any
        #     un-retrieved policy/price/timeframe/record detail on ANY turn, and the grounding gate
        #     still governs real factual questions (turn_type='answer' → decline if ungrounded).
        # dispute/sensitive/explicit/rate-limit/timeout already claimed a higher-priority reason
        # above (guard: reason is NO_GROUNDING). The talk-to-human button is always available.
        escalate, reason = False, None
        if model_meta.turn_type == "needs_info":
            # Treat the key as "have it" if EITHER the model saw it this turn OR we remembered it
            # from an earlier turn, so we ask only for the still-missing verify value.
            _pending_key = (pending_lookup or {}).get("key_value")
            answer_text = slot_fill_prompt(
                industry,
                model_meta.record_type or (pending_lookup or {}).get("record_type"),
                has_key=model_meta.has_lookup_key or bool(_pending_key),
                has_verify=model_meta.has_verify_value,
            )
        else:
            answer_text = model_answer.strip() or _conversational_reply(
                model_meta.turn_type, cfg, industry, model_meta
            )
    elif (not human_offer_pending) and escalate and reason is EscalationReason.NO_GROUNDING:
        escalate, reason, answer_text, offered_human = False, None, PROACTIVE_OFFER, True
    # KB-not-ready is already a soft offer — mark it so a following "yes" is recognised as acceptance.
    if not escalate and answer_text == KB_NOT_READY_MSG:
        offered_human = True

    # Language rule ([A3]): reply in the detected language if supported, else the tenant default.
    # Compare on the PRIMARY subtag: detected_language is BCP-47, so the model may answer "hi-IN"
    # while the tenant configured "hi" — a raw `in` test would miss and wrongly fall back to English.
    detected = model_meta.detected_language or established_language or default_lang
    _supported = {s.split("-")[0].lower() for s in supported}
    if detected.split("-")[0].lower() not in _supported:
        detected = default_lang

    # Cross-turn slot memory to carry into the next turn: keep the lookup KEY (never the verify
    # value — PII) so a follow-up that supplies the verify value can complete the lookup. Cleared
    # once verified, on escalation, or when the turn isn't part of a record-lookup flow.
    # [Fix 1] Persist the verified identity (key only, never the PII verify value) and carry it
    # forward across later turns, so a follow-up lookup — even for a different record type — reuses
    # it. An in-progress (unverified) key is still remembered the same way; a verified one is tagged
    # so it can't trigger an unprompted re-lookup (see the deterministic-completion guard above).
    pending_lookup_out: dict | None = _established or None
    if verified_record:
        pending_lookup_out = {"record_type": verified_record["type"],
                              "key_value": str(verified_record["key"]), "verified": True}
    elif not escalate and model_meta.turn_type in ("needs_info", "answer"):
        _rt = model_meta.record_type or _established.get("record_type")
        _kv = model_meta.lookup_key_value or _established.get("key_value")
        if _rt and _kv:
            pending_lookup_out = {"record_type": _rt, "key_value": str(_kv)}

    # Every branch above either relayed the model's text verbatim (grounded answer / record phrasing
    # / smalltalk / capability / out_of_scope) or replaced it with a code-owned string — so one
    # comparison against the model's text tells localize() which it is, with no flag to thread
    # through each branch. Empty model text (fake LLM, stall, engine-run lookup) → code-owned.
    code_owned = answer_text != (model_answer or "").strip()

    return TurnResult(
        answer=answer_text,
        citations=outcome.citations,
        detected_language=detected,
        code_owned=code_owned,
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
        verified_record=verified_record,
        pending_lookup=pending_lookup_out,
    )
