"""M6 escalation trigger evaluation — pure, no DB needed."""

from __future__ import annotations

from app.domain.escalation.reasons import EscalationReason
from app.domain.escalation.triggers import EscalationSignals, evaluate


def test_no_signals_means_no_escalation():
    assert evaluate(EscalationSignals()) is None


def test_no_grounding_and_no_tool_answer_escalates():
    assert evaluate(EscalationSignals(grounded=False, tool_answered=False)) == (
        EscalationReason.NO_GROUNDING
    )


def test_no_grounding_but_tool_answered_does_not_escalate():
    assert evaluate(EscalationSignals(grounded=False, tool_answered=True)) is None


def test_dispute_outranks_everything():
    assert evaluate(EscalationSignals(dispute=True, sensitive_intent_hit=True)) == (
        EscalationReason.DISPUTE
    )


def test_sensitive_intent_outranks_explicit_and_proactive():
    assert evaluate(
        EscalationSignals(sensitive_intent_hit=True, explicit_request=True)
    ) == EscalationReason.SENSITIVE


def test_explicit_request_is_recorded_as_explicit():
    assert evaluate(EscalationSignals(explicit_request=True)) == EscalationReason.EXPLICIT


def test_proactive_accept_is_recorded_as_proactive_not_explicit():
    # [A2]: accepting the AI's own offer is tagged distinctly from an unprompted request.
    assert evaluate(EscalationSignals(proactive_accept=True)) == EscalationReason.PROACTIVE


def test_verify_attempts_exhausted_maps_to_n_fails():
    assert evaluate(EscalationSignals(verify_attempts_exhausted=True)) == (
        EscalationReason.N_FAILS
    )


def test_timeout_maps_to_timeout():
    assert evaluate(EscalationSignals(timed_out=True)) == EscalationReason.TIMEOUT


def test_grounded_with_no_other_signal_never_escalates():
    assert evaluate(EscalationSignals(grounded=True, tool_answered=False)) is None
