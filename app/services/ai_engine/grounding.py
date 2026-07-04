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
from app.services.ai_engine.guardrails import KB_NOT_READY_MSG, NO_CONFIDENT_ANSWER
from app.services.knowledge_service import KB_NOT_READY, GroundedResult


@dataclass
class Outcome:
    answer: str
    escalate: bool
    reason: EscalationReason | None
    retrieval_hits: int
    citations: list = field(default_factory=list)


def decide_outcome(*, grounded, kb_signal, model_answer: str, record_result: dict | None) -> Outcome:
    if isinstance(grounded, GroundedResult) and grounded.chunks:
        # Prefer the model's answer (generated from the chunks, which are in its context) so a
        # real LLM's grounded generation shows through; fall back to the retrieved text verbatim
        # when the model produced nothing (e.g. the deterministic fake).
        top = grounded.chunks[0]["content"]
        answer = model_answer.strip() or f"Based on our documentation: {top}"
        return Outcome(answer=answer, escalate=False, reason=None,
                       retrieval_hits=len(grounded.chunks), citations=grounded.citations)

    if record_result and record_result.get("status") == "ok":
        return Outcome(answer=f"Here are your details: {record_result.get('record')}",
                       escalate=False, reason=None, retrieval_hits=0)

    if kb_signal == KB_NOT_READY:
        return Outcome(answer=KB_NOT_READY_MSG, escalate=False, reason=None, retrieval_hits=0)

    # No grounded KB and no verified record → cannot ground → escalate (grounding gate).
    return Outcome(answer=NO_CONFIDENT_ANSWER, escalate=True,
                   reason=EscalationReason.NO_GROUNDING, retrieval_hits=0)
