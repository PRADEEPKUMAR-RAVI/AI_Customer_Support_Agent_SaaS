"""M2 engine unit tests (no DB): grounding decision, escalate paths, verify-in-code, tag clamp."""

from __future__ import annotations

import asyncio
import uuid

import app.services.ai_engine.engine as engine_mod
from app.core import ratelimit
from app.core.config import estimate_cost_usd
from app.domain.escalation.reasons import EscalationReason
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.llm.base import LLMResult
from app.schemas.metrics import ModelCost, TurnMetricDTO
from app.services.ai_engine.engine import run_turn
from app.services.ai_engine.grounding import decide_outcome
from app.services.ai_engine.guardrails import PROACTIVE_OFFER
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


def test_decide_outcome_no_grounding_escalates():
    o = decide_outcome(grounded=None, kb_signal="NO_GROUNDING", model_answer="", record_result=None)
    assert o.escalate is True
    assert o.reason is EscalationReason.NO_GROUNDING


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

def test_detect_dispute_covers_the_three_record_states():
    assert detect_dispute("warranty", {"coverage": "void"}, "is my item covered?") == "void_warranty"
    assert detect_dispute("warranty", {"coverage": "active"}, "is my item covered?") is None
    assert detect_dispute("order", {"status": "delivered"}, "it says delivered but I never got it") == "delivered_not_received"
    assert detect_dispute("order", {"status": "delivered"}, "when will it arrive?") is None  # no dispute intent
    assert detect_dispute("order", {"status": "cancelled"}, "where is my refund?") == "cancelled_refund"
    assert detect_dispute("order", {"status": "shipped"}, "where is my refund?") is None


async def test_lookup_record_ok_flags_void_warranty_dispute():
    warranty = {"serial_no": "S1", "email": "a@x.com", "coverage": "void", "expiry": "2020-01-01"}
    out = await lookup_record_tool(
        None, {"record_type": "warranty", "key": "S1", "verify_value": "a@x.com"},
        industry="retail", resolver=_FakeResolver(warranty),
    )
    assert out["status"] == "ok"
    assert out["record"]["coverage"] == "void"
    assert out["dispute"] == "void_warranty"


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
