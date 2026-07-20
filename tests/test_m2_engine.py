"""M2 engine unit tests (no DB): grounding decision, escalate paths, verify-in-code, tag clamp."""

from __future__ import annotations

import asyncio
import uuid

import app.services.ai_engine.engine as engine_mod
from app.core import ratelimit
from app.core.config import estimate_cost_usd
from app.domain.escalation.reasons import EscalationReason
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.llm.base import LLMResult, ToolCall
from app.schemas.metrics import ModelCost, TurnMetricDTO
from app.services.ai_engine.engine import run_turn
from app.services.ai_engine.grounding import Outcome, decide_outcome
from app.services.ai_engine.guardrails import PROACTIVE_OFFER, render_record_answer
from app.services.ai_engine.structured import clamp_tags
from app.services.ai_engine.tools.lookup_record import detect_dispute, lookup_record_tool
from app.services.knowledge_service import KB_NOT_READY, GroundedResult

CFG = {
    "supported_languages": ["en", "es"],
    "default_language": "en",
    "allowed_tags": ["order_status"],
    "max_tool_calls_per_turn": 5,
}


async def test_talk_to_human_escalates_without_model():
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="hi", escalate_request=True)
    assert r.escalate is True
    assert r.escalation_reason is EscalationReason.EXPLICIT
    assert r.target_state.value == "escalated"


def test_decide_outcome_grounded_prefers_model_answer_else_chunk():
    g = GroundedResult(
        chunks=[{"content": "Returns are accepted within 30 days."}],
        citations=[{"index": 0, "source_id": "s1", "title": "Policy"}],
        top_score=0.5,
    )
    # The model's grounded generation is used when present...
    o = decide_outcome(grounded=g, kb_signal=None, model_answer="You have 30 days to return.", record_result=None)
    assert o.escalate is False
    assert o.answer == "You have 30 days to return."
    assert o.retrieval_hits == 1
    # ...and it falls back to the retrieved text verbatim when the model produced nothing (fake).
    o2 = decide_outcome(grounded=g, kb_signal=None, model_answer="", record_result=None)
    assert "Returns are accepted within 30 days." in o2.answer


def test_decide_outcome_verified_record_wins_over_kb():
    # The customer looked up THEIR order and it verified; even if a KB search also matched, the
    # answer must be the record's status — not a documentation dump — and carry NO KB citations.
    g = GroundedResult(
        chunks=[{"content": "placed — we received your order. shipped — it has left our warehouse."}],
        citations=[{"index": 0, "source_id": "s1", "title": "acme_retail_kb.md"}],
        top_score=0.5,
    )
    o = decide_outcome(grounded=g, kb_signal=None, model_answer="",
                       record_result={"status": "ok", "record_type": "order",
                                      "record": {"status": "cancelled"}})
    assert o.escalate is False
    assert "cancel" in o.answer.lower()          # the customer's actual order status
    assert "documentation" not in o.answer.lower()
    assert o.citations == []                       # no KB sources on a record answer


def test_decide_outcome_no_grounding_escalates():
    o = decide_outcome(grounded=None, kb_signal="NO_GROUNDING", model_answer="", record_result=None)
    assert o.escalate is True
    assert o.reason is EscalationReason.NO_GROUNDING


def test_render_record_answer_is_natural_never_a_dict():
    shipped = render_record_answer("order", {"status": "shipped", "eta": "Fri", "tracking_url": "http://t/x"})
    assert "shipped" in shipped.lower() and "track" in shipped.lower()
    assert "delivered on" in render_record_answer("order", {"status": "delivered", "eta": "2026-07-01"}).lower()
    assert "prepared" in render_record_answer("order", {"status": "processing", "eta": "Mon"}).lower()
    assert "active" in render_record_answer("warranty", {"coverage": "active", "expiry": "2027-01-01"}).lower()
    assert "expired on" in render_record_answer("warranty", {"coverage": "expired", "expiry": "2024-01-01"}).lower()
    # never emits a raw dict, for any record type
    for out in (shipped, render_record_answer("booking", {"status": "confirmed", "dates": "Jul 1-5"})):
        assert "{" not in out and "}" not in out


def test_decide_outcome_record_prefers_model_answer_else_renders():
    rr = {"status": "ok", "record_type": "order",
          "record": {"status": "shipped", "eta": "Fri", "tracking_ref": "T1"}}
    # the model's natural, in-language phrasing is used when present...
    o = decide_outcome(grounded=None, kb_signal=None,
                       model_answer="Your order has shipped and arrives Friday.", record_result=rr)
    assert o.escalate is False and o.answer == "Your order has shipped and arrives Friday."
    # ...and it falls back to the deterministic render (NOT a raw dict) when the model said nothing.
    o2 = decide_outcome(grounded=None, kb_signal=None, model_answer="", record_result=rr)
    assert o2.escalate is False and "{" not in o2.answer and "shipped" in o2.answer.lower()


def test_decide_outcome_kb_not_ready_offers_human_without_escalate():
    o = decide_outcome(grounded=None, kb_signal=KB_NOT_READY, model_answer="", record_result=None)
    assert o.escalate is False


def test_clamp_tags_known_approved_unknown_pending():
    tags = {t.name: t.status for t in clamp_tags(["Order Status", "made_up"], ["order_status"])}
    assert tags == {"order_status": "approved", "made_up": "pending"}


class _FakeResolver:
    def __init__(self, rec):
        self._rec = rec

    async def fetch(self, tenant_id, record_type, key):
        if isinstance(self._rec, Exception):
            raise self._rec
        return self._rec


_ORDER = {"order_id": "ORD1", "email": "Alice@x.com", "status": "shipped", "eta": "Fri", "tracking_ref": "T1"}


async def test_lookup_record_verify_ok_returns_only_returned_fields():
    out = await lookup_record_tool(
        None, {"record_type": "order", "key": "ORD1", "verify_value": "alice@x.com"},
        industry="retail", resolver=_FakeResolver(_ORDER),
    )
    assert out["status"] == "ok"
    assert out["record"]["status"] == "shipped"
    assert "email" not in out["record"]  # verify field is never disclosed


async def test_lookup_record_unverified_on_wrong_email():
    out = await lookup_record_tool(
        None, {"record_type": "order", "key": "ORD1", "verify_value": "bob@x.com"},
        industry="retail", resolver=_FakeResolver(_ORDER),
    )
    assert out["status"] == "unverified"


async def test_lookup_record_not_found_and_invalid_type_and_connector_error():
    nf = await lookup_record_tool(
        None, {"record_type": "order", "key": "ZZZ", "verify_value": "x"},
        industry="retail", resolver=_FakeResolver(NOT_FOUND),
    )
    assert nf["status"] == "not_found"

    bad = await lookup_record_tool(
        None, {"record_type": "spaceship", "key": "1", "verify_value": "x"},
        industry="retail", resolver=_FakeResolver(_ORDER),
    )
    assert bad["status"] == "invalid_type"

    err = await lookup_record_tool(
        None, {"record_type": "order", "key": "1", "verify_value": "x"},
        industry="retail", resolver=_FakeResolver(ConnectorError("timeout")),
    )
    assert err["status"] == "connector_error"


def test_turn_metric_cost_contract():
    assert estimate_cost_usd("fake", 100, 100) == 0.0
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == 0.75  # 0.15 in + 0.60 out
    assert estimate_cost_usd("unknown-model", 10, 10) is None
    # OpenAI returns a dated snapshot id — it must still price at the base model's rate.
    assert estimate_cost_usd("gpt-4o-mini-2024-07-18", 1_000_000, 0) == 0.15
    assert estimate_cost_usd("", 10, 10) is None  # no-LLM (explicit-escalate) turn


def test_turn_metric_dto_is_the_single_shape():
    dto = TurnMetricDTO(
        conversation_id=uuid.uuid4(),
        escalated=True,
        escalation_reason=EscalationReason.NO_GROUNDING,
        cost=[ModelCost(model="gpt-4o-mini", prompt_tokens=10, completion_tokens=5, cost_usd=0.0)],
    )
    d = dto.model_dump()
    assert d["escalated"] is True
    assert d["escalation_reason"] is EscalationReason.NO_GROUNDING
    assert d["cost"][0]["model"] == "gpt-4o-mini"


# --- [A1] deterministic record-state dispute -----------------------------------------------

def test_detect_dispute_covers_the_record_state_disputes():
    # [Fix 2] A void warranty is answerable data (the bot reports the coverage), NOT a dispute.
    assert detect_dispute("warranty", {"coverage": "void"}, "is my item covered?") is None
    assert detect_dispute("warranty", {"coverage": "active"}, "is my item covered?") is None
    assert detect_dispute("order", {"status": "delivered"}, "it says delivered but I never got it") == "delivered_not_received"
    assert detect_dispute("order", {"status": "delivered"}, "when will it arrive?") is None  # no dispute intent
    assert detect_dispute("order", {"status": "cancelled"}, "where is my refund?") == "cancelled_refund"
    assert detect_dispute("order", {"status": "shipped"}, "where is my refund?") is None


async def test_lookup_record_void_warranty_is_answerable_not_a_dispute():
    # [Fix 2] A void warranty verifies and returns its coverage status so the bot can ANSWER it;
    # it is no longer flagged as a dispute (which would force a human hand-off).
    warranty = {"serial_no": "S1", "email": "a@x.com", "coverage": "void", "expiry": "2020-01-01"}
    out = await lookup_record_tool(
        None, {"record_type": "warranty", "key": "S1", "verify_value": "a@x.com"},
        industry="retail", resolver=_FakeResolver(warranty),
    )
    assert out["status"] == "ok"
    assert out["record"]["coverage"] == "void"
    assert out["dispute"] is None


# --- [IMP-SEC-6] durable verify-attempt lockout --------------------------------------------

def _patch_counter(monkeypatch):
    store: dict[str, int] = {}

    async def current(key):
        return store.get(key, 0)

    async def hit(key, *, limit, window_seconds):
        store[key] = store.get(key, 0) + 1
        return store[key] <= limit

    async def reset(key):
        store.pop(key, None)

    monkeypatch.setattr(ratelimit, "current", current)
    monkeypatch.setattr(ratelimit, "hit", hit)
    monkeypatch.setattr(ratelimit, "reset", reset)
    return store


async def test_lookup_record_locks_out_after_retail_cap(monkeypatch):
    _patch_counter(monkeypatch)
    args = {"record_type": "order", "key": "ORD1", "verify_value": "wrong@x.com"}
    for _ in range(3):  # retail cap = 3
        out = await lookup_record_tool(None, args, industry="retail", tenant_id="t1", resolver=_FakeResolver(_ORDER))
        assert out["status"] == "unverified"
    locked = await lookup_record_tool(None, args, industry="retail", tenant_id="t1", resolver=_FakeResolver(_ORDER))
    assert locked["status"] == "rate_limited"
    # A correct verify would have reset the counter — prove not_found also consumes an attempt and
    # that healthcare (N=1) locks after a single miss below.


async def test_lookup_record_healthcare_locks_after_one_attempt(monkeypatch):
    _patch_counter(monkeypatch)
    args = {"record_type": "appointment", "key": "B1", "verify_value": "0000"}
    first = await lookup_record_tool(None, args, industry="healthcare", tenant_id="t2", resolver=_FakeResolver(NOT_FOUND))
    assert first["status"] == "not_found"          # counter -> 1 (== cap)
    second = await lookup_record_tool(None, args, industry="healthcare", tenant_id="t2", resolver=_FakeResolver(NOT_FOUND))
    assert second["status"] == "rate_limited"      # cap already hit


async def test_lookup_record_success_resets_the_counter(monkeypatch):
    store = _patch_counter(monkeypatch)
    bad = {"record_type": "order", "key": "ORD1", "verify_value": "wrong@x.com"}
    await lookup_record_tool(None, bad, industry="retail", tenant_id="t3", resolver=_FakeResolver(_ORDER))
    assert store["verifyattempt:t3:order:ORD1"] == 1
    ok = {"record_type": "order", "key": "ORD1", "verify_value": "alice@x.com"}
    out = await lookup_record_tool(None, ok, industry="retail", tenant_id="t3", resolver=_FakeResolver(_ORDER))
    assert out["status"] == "ok"
    assert "verifyattempt:t3:order:ORD1" not in store  # reset on success


# --- [IMP-ENG-3] per-step stall/timeout guard ----------------------------------------------

async def test_run_turn_stall_escalates_timeout(monkeypatch):
    class _SlowLLM:
        supports_tools = True
        supports_structured_output = True

        async def complete(self, messages, **kw):
            await asyncio.sleep(0.05)
            return LLMResult(text="x", model="fake")

    monkeypatch.setattr(engine_mod, "get_llm", lambda: _SlowLLM())
    cfg = {"per_step_budget_seconds": 0.001, "stall_retries": 0,
           "supported_languages": ["en"], "default_language": "en"}
    r = await run_turn(None, cfg=cfg, industry="retail", user_text="hi")
    assert r.escalate is True
    assert r.escalation_reason is EscalationReason.TIMEOUT
    assert r.target_state.value == "escalated"


# --- [A2] proactive human offer -------------------------------------------------------------

class _NoGroundLLM:
    """Produces no tool calls and no answer → the grounding gate fails (NO_GROUNDING)."""

    supports_tools = True
    supports_structured_output = True

    async def complete(self, messages, **kw):
        if kw.get("response_schema"):
            return LLMResult(structured={"answer_complete": False, "detected_language": "en",
                                         "tags": [], "advisory_confidence": None}, model="fake")
        return LLMResult(text="", model="fake")


_A2_CFG = {"supported_languages": ["en"], "default_language": "en"}


async def test_run_turn_offers_human_on_first_ungrounded_turn(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="do you sell unicorns?",
                       human_offer_pending=False)
    assert r.escalate is False           # offer instead of a hard hand-off
    assert r.offered_human is True
    assert r.answer == PROACTIVE_OFFER
    assert r.target_state.value == "ai_handling"


async def test_run_turn_accepts_pending_offer_as_proactive(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="yes please",
                       human_offer_pending=True)
    assert r.escalate is True
    assert r.escalation_reason is EscalationReason.PROACTIVE


async def test_run_turn_declined_offer_still_ungrounded_hands_off(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="what about dragons?",
                       human_offer_pending=True)
    assert r.escalate is True                                    # already offered once → hand off
    assert r.escalation_reason is EscalationReason.NO_GROUNDING


# --- [A3] language rule: code-owned replies reach the customer in THEIR language ---------------

class _LangLLM(_NoGroundLLM):
    """_NoGroundLLM (→ the code-owned PROACTIVE_OFFER) but reporting a chosen detected_language."""

    def __init__(self, lang: str) -> None:
        self.lang = lang

    async def complete(self, messages, **kw):
        if kw.get("response_schema"):
            return LLMResult(structured={"answer_complete": False, "detected_language": self.lang,
                                         "tags": [], "advisory_confidence": None}, model="fake")
        return LLMResult(text="", model="fake")


def _patch_langs(monkeypatch, detected: str):
    """Stub both seams: the engine loop (reports ``detected``) and the translator localize() uses
    (which lazy-imports get_llm from model_router, so patching engine_mod alone would let a real
    API call through). Returns the list of texts handed to the translator."""
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _LangLLM(detected))
    seen: list[str] = []

    class _Translator:
        supports_tools = supports_structured_output = True

        async def complete(self, messages, **kw):
            seen.append(messages[-1]["content"])
            return LLMResult(text="<translated>", model="fake")

    monkeypatch.setattr("app.infra.llm.model_router.get_llm", lambda: _Translator())
    return seen


_HI_CFG = {"supported_languages": ["en", "hi"], "default_language": "en"}


async def test_code_owned_reply_is_localized_to_a_supported_language(monkeypatch):
    """The regression: the engine owns the words on most turns and every canned string is English,
    so a Hindi customer got an English reply. The code-owned text must be translated on the way out."""
    seen = _patch_langs(monkeypatch, "hi")
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="क्या आप यूनिकॉर्न बेचते हैं?")
    assert r.detected_language == "hi"
    assert seen == [PROACTIVE_OFFER]     # the English source went to the translator...
    assert r.answer == "<translated>"    # ...and the customer got the translation, not English


async def test_english_turn_is_not_sent_to_the_translator(monkeypatch):
    seen = _patch_langs(monkeypatch, "en")
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="do you sell unicorns?")
    assert r.answer == PROACTIVE_OFFER and seen == []   # no needless translation call


async def test_bcp47_region_subtag_still_matches_a_supported_language(monkeypatch):
    """The model may answer BCP-47 'hi-IN' while the tenant configured 'hi'; a raw `in` test would
    miss and silently fall the customer back to English."""
    seen = _patch_langs(monkeypatch, "hi-IN")
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="क्या आप यूनिकॉर्न बेचते हैं?")
    assert r.detected_language == "hi-IN" and seen == [PROACTIVE_OFFER]


async def test_unsupported_language_falls_back_to_tenant_default(monkeypatch):
    """[A3]: a language the tenant did NOT configure → reply in default_language (English here),
    so the translator is never called."""
    seen = _patch_langs(monkeypatch, "ja")
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="ユニコーンを売っていますか?")
    assert r.detected_language == "en" and r.answer == PROACTIVE_OFFER and seen == []


async def test_model_authored_answer_is_not_retranslated(monkeypatch):
    """The model already replies in the customer's language (the system prompt's language rule), so
    its text must NOT go through the translator — that would cost a call and paraphrase a grounded
    fact. Only code-owned English is translated."""
    seen = _patch_langs(monkeypatch, "hi")
    hindi = "हमारी वापसी नीति 30 दिनों की है।"

    class _GroundedHindiLLM:
        supports_tools = supports_structured_output = True

        async def complete(self, messages, **kw):
            if kw.get("response_schema"):
                return LLMResult(structured={"answer_complete": True, "detected_language": "hi",
                                             "tags": [], "advisory_confidence": None}, model="fake")
            return LLMResult(text=hindi, model="fake")

    monkeypatch.setattr(engine_mod, "get_llm", lambda: _GroundedHindiLLM())
    monkeypatch.setattr(engine_mod, "decide_outcome", lambda **kw: Outcome(
        answer=kw["model_answer"], escalate=False, reason=None, retrieval_hits=1))
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="आपकी वापसी नीति क्या है?")
    assert r.answer == hindi and seen == []      # relayed untouched, translator never called


async def test_translation_failure_falls_back_to_the_english_source(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _LangLLM("hi"))

    class _Boom:
        supports_tools = supports_structured_output = True

        async def complete(self, messages, **kw):
            raise RuntimeError("provider down")

    monkeypatch.setattr("app.infra.llm.model_router.get_llm", lambda: _Boom())
    r = await run_turn(None, cfg=_HI_CFG, industry="retail", user_text="क्या आप यूनिकॉर्न बेचते हैं?")
    assert r.answer == PROACTIVE_OFFER   # a reply in the wrong language beats no reply


# --- [§4.5] deterministic sensitive-intent trigger (tenant sensitive_intent_list) --------------

_SENSITIVE_CFG = {"supported_languages": ["en"], "default_language": "en",
                  "sensitive_intent_list": ["refund dispute", "complaint", "legal"]}


async def test_run_turn_sensitive_intent_escalates(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    r = await run_turn(None, cfg=_SENSITIVE_CFG, industry="retail",
                       user_text="I want to file a complaint about my order")
    assert r.escalate is True
    assert r.escalation_reason is EscalationReason.SENSITIVE
    assert r.target_state.value == "escalated"


async def test_run_turn_sensitive_list_empty_or_no_match_is_not_sensitive(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    # No sensitive keyword in the text → the ungrounded turn takes the proactive-offer path,
    # never a SENSITIVE hand-off (proves the keyword match, not a blanket escalate).
    r = await run_turn(None, cfg=_SENSITIVE_CFG, industry="retail", user_text="do you sell unicorns?")
    assert r.escalation_reason is not EscalationReason.SENSITIVE
    assert r.offered_human is True


# --- [PRD §4.2] verified-lookup → linked-record pointer capture --------------------------------

class _LookupLLM:
    """Emits one lookup_record tool call, then a plain answer, then the structured metadata."""

    supports_tools = True
    supports_structured_output = True

    def __init__(self):
        self.n = 0

    async def complete(self, messages, **kw):
        if kw.get("response_schema"):
            return LLMResult(structured={"answer_complete": True, "detected_language": "en",
                                         "tags": [], "advisory_confidence": None}, model="fake")
        self.n += 1
        if self.n == 1:
            return LLMResult(text="", model="fake", tool_calls=[ToolCall(
                id="c1", name="lookup_record",
                arguments={"record_type": "order", "key": "ORD1", "verify_value": "alice@x.com"})])
        return LLMResult(text="Your order ORD1 is shipped.", model="fake")


async def test_run_turn_captures_verified_record_pointer(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _LookupLLM())

    async def _ok(session, args, **kw):
        return {"status": "ok", "record": {"status": "shipped"}, "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _ok)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="where is my order ORD1?")
    assert r.verified_record == {"type": "order", "key": "ORD1"}


async def test_run_turn_no_pointer_when_unverified(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _LookupLLM())

    async def _unverified(session, args, **kw):
        return {"status": "unverified"}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _unverified)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="where is my order?")
    assert r.verified_record is None


# --- [§4.8 / scope] deterministic replies for non-grounded conversational turns ---------------

class _ClassifierLLM:
    """No tool calls; emits `text` as the answer and classifies the turn as `turn_type` in the
    metadata pass. Used to exercise the engine's DETERMINISTIC, code-owned non-grounded replies —
    the model's own `text` must never reach the customer on these turns."""

    supports_tools = True
    supports_structured_output = True

    def __init__(self, turn_type: str, text: str, record_type: str | None = None):
        self._tt, self._text, self._rt = turn_type, text, record_type

    async def complete(self, messages, **kw):
        if kw.get("response_schema"):
            return LLMResult(structured={"answer_complete": False, "detected_language": "en",
                                         "tags": [], "turn_type": self._tt, "record_type": self._rt,
                                         "advisory_confidence": None}, model="fake")
        return LLMResult(text=self._text, model="fake")


async def test_slot_fill_asks_deterministically_and_never_leaks_model_text(monkeypatch):
    # The model's own text tries to sneak a fabricated fact ("shipped Friday"); the engine must
    # ship the DETERMINISTIC schema-derived slot-fill prompt instead — the grounding-gate fix.
    monkeypatch.setattr(engine_mod, "get_llm",
                        lambda: _ClassifierLLM("needs_info", "Your order shipped Friday! What's your email?", "order"))
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="where is my order?")
    assert r.escalate is False and r.escalation_reason is None
    assert "order number" in r.answer.lower() and "verify" in r.answer.lower()
    assert "friday" not in r.answer.lower()          # the model's fabricated fact NEVER reaches the customer
    assert r.target_state.value == "ai_handling"


async def test_smalltalk_relays_natural_reply(monkeypatch):
    # Small talk is relayed in the model's OWN words (natural, not a canned line) — no escalation.
    monkeypatch.setattr(engine_mod, "get_llm",
                        lambda: _ClassifierLLM("smalltalk", "Hey! Doing great — how can I help you today?"))
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="hi, how are you?")
    assert r.escalate is False and r.escalation_reason is None
    assert r.answer == "Hey! Doing great — how can I help you today?"


async def test_smalltalk_falls_back_to_template_when_model_silent(monkeypatch):
    # Defensive: if the model returns no text, a safe deterministic greeting is used instead.
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _ClassifierLLM("smalltalk", ""))
    r = await run_turn(None, cfg={**_A2_CFG, "welcome_message": "Hey there! How can I help?"},
                       industry="retail", user_text="hi")
    assert r.escalate is False
    assert r.answer == "Hey there! How can I help?"


# --- cross-turn slot memory: the customer gives the key on one turn, the verify value on the next -

class _SlotLLM:
    """Fake for the multi-turn record-lookup flow: no model tool call (the ENGINE drives the
    lookup), emits a configurable metadata envelope — what the model 'extracts' this turn."""

    supports_tools = True
    supports_structured_output = True

    def __init__(self, *, turn_type="needs_info", record_type="order", has_key=False,
                 has_verify=False, key_value=None, verify_value=None):
        self._meta = {
            "answer_complete": False, "detected_language": "en", "tags": [],
            "turn_type": turn_type, "record_type": record_type,
            "has_lookup_key": has_key, "has_verify_value": has_verify,
            "lookup_key_value": key_value, "verify_value": verify_value, "advisory_confidence": None,
        }

    async def complete(self, messages, **kw):
        if kw.get("response_schema"):
            return LLMResult(structured=self._meta, model="fake")
        return LLMResult(text="", model="fake")


async def test_slot_memory_remembers_key_and_asks_only_for_verify(monkeypatch):
    # Customer gives ONLY the order id: the engine must remember it for the next turn AND ask only
    # for the still-missing verify value, not re-demand the order number.
    llm = _SlotLLM(has_key=True, key_value="1005")
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="my order id is 1005")
    assert r.pending_lookup == {"record_type": "order", "key_value": "1005"}
    assert "email" in r.answer.lower() and r.answer.endswith("?")
    assert "share your order number" not in r.answer.lower()   # doesn't re-ask for the id


async def test_engine_completes_lookup_when_verify_arrives_even_if_model_forgets(monkeypatch):
    # THE bug: the customer gave the order id on an earlier turn, then only the email now, and the
    # model 'forgets' EVERYTHING (record_type + all slot fields null) and does NOT call the tool.
    # The ENGINE must still complete the lookup deterministically — record_type + key from the
    # remembered pending_lookup, email from the message via the regex fallback.
    llm = _SlotLLM(record_type=None, has_key=False, has_verify=False, key_value=None, verify_value=None)
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)
    seen = {}

    async def _capture(session, args, **kw):
        seen.update(args)
        return {"status": "ok", "record": {"status": "shipped", "eta": "Fri"},
                "record_type": "order", "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _capture)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="godbos40534@gmail.com",
                       pending_lookup={"record_type": "order", "key_value": "1005"})
    # The engine called the lookup with the remembered key + the email from the message.
    assert seen == {"record_type": "order", "key": "1005", "verify_value": "godbos40534@gmail.com"}
    assert r.verified_record == {"type": "order", "key": "1005"}   # verified pointer captured
    assert r.escalate is False
    assert "ship" in r.answer.lower()                              # answers with the order status
    # [Fix 1] the verified identity is now carried forward (key only) so a follow-up lookup — even
    # for a different record type — can reuse it instead of re-asking.
    assert r.pending_lookup == {"record_type": "order", "key_value": "1005", "verified": True}


async def test_failed_lookup_retries_instead_of_escalating(monkeypatch):
    # A wrong/mistyped detail (unverified) or a missing record (not_found) must NOT escalate the
    # customer to a human — it returns the SAME neutral retry message so they can fix it and try
    # again. (Regression for the bug where a bad email dumped the user into an after-hours hand-off.)
    llm = _SlotLLM(has_key=True, has_verify=True, key_value="1005", verify_value="wrong@x.com")
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)

    for status in ("unverified", "not_found"):
        async def _fail(session, args, _s=status, **kw):
            return {"status": _s}

        monkeypatch.setattr(engine_mod, "lookup_record_tool", _fail)
        r = await run_turn(None, cfg=CFG, industry="retail",
                           user_text="order 1005, email wrong@x.com")
        assert r.escalate is False                     # not a dead end — retryable
        assert r.verified_record is None
        assert "double-check" in r.answer.lower() and "order number" in r.answer.lower()


async def test_engine_completes_lookup_from_model_extracted_values(monkeypatch):
    # No prior pending_lookup: the model extracts BOTH values from the conversation this turn and
    # the engine performs the lookup — no dependence on model tool-calling.
    llm = _SlotLLM(has_key=True, has_verify=True, key_value="1005", verify_value="a@b.com")
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)

    async def _ok(session, args, **kw):
        return {"status": "ok", "record": {"status": "delivered"}, "record_type": "order",
                "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _ok)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="my order 1005, email a@b.com")
    assert r.verified_record == {"type": "order", "key": "1005"}
    assert "deliver" in r.answer.lower()


async def test_verified_identity_carries_to_followup_lookup_of_another_type(monkeypatch):
    # [Fix 1] The order was verified earlier (identity remembered). The customer now asks about the
    # WARRANTY for "the same one" — the model classifies record_type=warranty but does NOT re-extract
    # the order id or email. The engine must reuse the remembered key (warranty accepts order_id) +
    # the email from history and complete the lookup, instead of re-asking for details already given.
    llm = _SlotLLM(turn_type="needs_info", record_type="warranty",
                   has_key=False, has_verify=False, key_value=None, verify_value=None)
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)
    seen = {}

    async def _capture(session, args, **kw):
        seen.update(args)
        return {"status": "ok", "record": {"coverage": "active", "expiry": "2027-01-01"},
                "record_type": "warranty", "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _capture)
    history = [
        {"role": "user", "content": "my order id is 1006 and email is emma.brown@example.com"},
        {"role": "assistant", "content": "Your order has shipped."},
    ]
    r = await run_turn(None, cfg=CFG, industry="retail",
                       user_text="and what about the warranty for the same one?",
                       history=history,
                       pending_lookup={"record_type": "order", "key_value": "1006", "verified": True})
    assert seen == {"record_type": "warranty", "key": "1006", "verify_value": "emma.brown@example.com"}
    assert r.escalate is False
    assert r.verified_record == {"type": "warranty", "key": "1006"}
    assert "active" in r.answer.lower()


async def test_verified_identity_does_not_trigger_unprompted_relookup(monkeypatch):
    # [Fix 1] guard: a carried-forward VERIFIED identity must NOT cause a lookup on a turn where the
    # customer didn't ask about a record (here: smalltalk) — that would re-answer unprompted. The
    # identity is still preserved for a genuine follow-up later.
    llm = _SlotLLM(turn_type="smalltalk", record_type=None,
                   has_key=False, has_verify=False, key_value=None, verify_value=None)
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)
    called = {"n": 0}

    async def _boom(session, args, **kw):
        called["n"] += 1
        return {"status": "ok", "record": {"status": "shipped"}, "record_type": "order", "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _boom)
    r = await run_turn(None, cfg=CFG, industry="retail", user_text="thanks!",
                       history=[{"role": "user", "content": "email is emma.brown@example.com"}],
                       pending_lookup={"record_type": "order", "key_value": "1006", "verified": True})
    assert called["n"] == 0                       # no unprompted lookup on a non-record turn
    assert r.escalate is False
    assert r.pending_lookup == {"record_type": "order", "key_value": "1006", "verified": True}


async def test_void_warranty_is_answered_not_escalated(monkeypatch):
    # [Fix 2] A verified warranty whose coverage is void is ANSWERED with its status, not handed off.
    llm = _SlotLLM(record_type="warranty", has_key=True, has_verify=True,
                   key_value="1006", verify_value="emma.brown@example.com")
    monkeypatch.setattr(engine_mod, "get_llm", lambda: llm)

    async def _void(session, args, **kw):
        return {"status": "ok", "record": {"coverage": "void", "expiry": "2026-12-31"},
                "record_type": "warranty", "dispute": None}

    monkeypatch.setattr(engine_mod, "lookup_record_tool", _void)
    r = await run_turn(None, cfg=CFG, industry="retail",
                       user_text="warranty for order 1006, email emma.brown@example.com")
    assert r.escalate is False
    assert "void" in r.answer.lower()
    assert r.verified_record == {"type": "warranty", "key": "1006"}


async def test_capability_relays_natural_reply(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _ClassifierLLM(
        "capability", "I'm your support assistant — I can track orders and check warranties. What do you need?"))
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="what can you do?")
    assert r.escalate is False
    assert r.answer.startswith("I'm your support assistant")


async def test_out_of_scope_relays_natural_decline_without_escalating(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _ClassifierLLM(
        "out_of_scope", "That's outside what I can help with here — anything about your orders?"))
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="what does BMW mean?")
    assert r.escalate is False                        # out-of-scope is declined, not escalated
    assert "outside" in r.answer.lower()


async def test_human_request_in_text_escalates_explicit(monkeypatch):
    # Typing "connect me with a human" (turn_type=human_request) must ESCALATE the ticket — not
    # just have the AI claim it did. Same deterministic hand-off as the talk-to-human button.
    monkeypatch.setattr(engine_mod, "get_llm",
                        lambda: _ClassifierLLM("human_request", "Connecting you with a human now."))
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="i want to connect with a human")
    assert r.escalate is True
    assert r.escalation_reason is EscalationReason.EXPLICIT
    assert r.target_state.value == "escalated"


async def test_ungrounded_answer_type_still_offers_human(monkeypatch):
    # turn_type='answer' but nothing grounded (an in-domain question it couldn't answer) → the
    # proactive human offer still fires; the deterministic path is ONLY for the classified types.
    monkeypatch.setattr(engine_mod, "get_llm", lambda: _NoGroundLLM())
    r = await run_turn(None, cfg=_A2_CFG, industry="retail", user_text="do you sell unicorns?")
    assert r.escalate is False and r.offered_human is True and r.answer == PROACTIVE_OFFER
