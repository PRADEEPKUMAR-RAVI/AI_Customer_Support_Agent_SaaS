"""Escalation trigger evaluation — the single source of truth for "when does the AI hand off
to a human" (PRD §4.5). Pure and DB-free: M2 computes each raw signal (grounding, verify,
sensitive-intent keyword match, dispute detection, timeout) and this function only combines
them into ONE canonical reason. Trigger logic must never be split between M2 and here — M2
feeds signals, ``evaluate`` decides.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.escalation.reasons import EscalationReason


@dataclass(frozen=True)
class EscalationSignals:
    """Raw, already-computed signals for a single turn. Every field defaults to the
    "nothing happened" value so a caller only sets what's relevant."""

    dispute: bool = False  # [A1] deterministic record-state escalation (void warranty, etc.)
    sensitive_intent_hit: bool = False  # tenant `sensitive_intent_list` keyword match
    explicit_request: bool = False  # unprompted "talk to a human" (first-class flag, [IMP-ESC-5])
    proactive_accept: bool = False  # accepted the "connect you to a human?" offer [A2]
    verify_attempts_exhausted: bool = False  # durable verify counter hit its cap [IMP-SEC-6]
    grounded: bool = True  # KB retrieval cleared the relevance gate
    tool_answered: bool = False  # a tool (e.g. lookup_record) produced an answer this turn
    timed_out: bool = False  # per-turn stall/timeout guard fired


# Fixed precedence when more than one signal is true in the same turn: deterministic/code-driven
# reasons outrank soft ones, and an explicit human request outranks a passive retrieval failure.
_ORDER: tuple[tuple[str, EscalationReason], ...] = (
    ("dispute", EscalationReason.DISPUTE),
    ("sensitive_intent_hit", EscalationReason.SENSITIVE),
    ("explicit_request", EscalationReason.EXPLICIT),
    ("proactive_accept", EscalationReason.PROACTIVE),
    ("verify_attempts_exhausted", EscalationReason.N_FAILS),
    ("timed_out", EscalationReason.TIMEOUT),
)


def evaluate(signals: EscalationSignals) -> EscalationReason | None:
    """First-match-wins over a fixed severity/certainty order. Returns ``None`` when nothing
    warrants a hand-off — the turn proceeds as a normal AI-handled answer."""
    for field, reason in _ORDER:
        if getattr(signals, field):
            return reason
    if not signals.grounded and not signals.tool_answered:
        return EscalationReason.NO_GROUNDING
    return None
