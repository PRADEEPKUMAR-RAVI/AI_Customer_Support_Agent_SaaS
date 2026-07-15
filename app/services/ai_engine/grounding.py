"""The grounding decision — enforced in ENGINE code, not by the model (non-negotiable #3).

Given the tool results, decide the answer and whether to escalate:
  * grounded KB → answer from the retrieved chunk (+ citations)
  * verified record → answer from the record
  * KB not ready → "still learning", offer a human (no hard escalate)
  * nothing grounded and no record → the grounding gate fails → escalate (no_grounding)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.escalation.reasons import EscalationReason
from app.services.ai_engine.guardrails import (
    KB_NOT_READY_MSG,
    NO_CONFIDENT_ANSWER,
    render_record_answer,
)
from app.services.knowledge_service import KB_NOT_READY, GroundedResult


@dataclass
class Outcome:
    answer: str
    escalate: bool
    reason: EscalationReason | None
    retrieval_hits: int
    citations: list = field(default_factory=list)


def decide_outcome(*, grounded, kb_signal, model_answer: str, record_result: dict | None) -> Outcome:
    if record_result and record_result.get("status") == "ok":
        # A VERIFIED personal record wins over generic KB docs: the customer asked about THEIR order,
        # not what order statuses mean, so a successful lookup this turn is the answer — even if the
        # model also ran a KB search on the side. Answer from the record (no KB citations); prefer
        # the model's natural phrasing when present, else a deterministic per-state rendering (§4.8).
        # Never dump the raw record dict.
        answer = model_answer.strip() or render_record_answer(
            record_result.get("record_type", ""), record_result.get("record") or {}
        )
        return Outcome(answer=answer, escalate=False, reason=None, retrieval_hits=0)

    if isinstance(grounded, GroundedResult) and grounded.chunks:
        # Prefer the model's answer (generated from the chunks, which are in its context) so a
        # real LLM's grounded generation shows through; fall back to the retrieved text verbatim
        # when the model produced nothing (e.g. the deterministic fake).
        top = grounded.chunks[0]["content"]
        answer = model_answer.strip() or f"Based on our documentation: {top}"
        return Outcome(answer=answer, escalate=False, reason=None,
                       retrieval_hits=len(grounded.chunks), citations=grounded.citations)

    if kb_signal == KB_NOT_READY:
        return Outcome(answer=KB_NOT_READY_MSG, escalate=False, reason=None, retrieval_hits=0)

    # No grounded KB and no verified record → cannot ground → escalate (grounding gate).
    return Outcome(answer=NO_CONFIDENT_ANSWER, escalate=True,
                   reason=EscalationReason.NO_GROUNDING, retrieval_hits=0)
