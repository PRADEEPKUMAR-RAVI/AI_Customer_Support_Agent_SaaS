"""Ticket-transition whitelist matrix — the code-enforced non-negotiable (CI gate)."""

from __future__ import annotations

import itertools

import pytest

from app.domain.ticketing.states import Actor, TicketState
from app.domain.ticketing.transitions import (
    AI_WHITELIST,
    TransitionNotAllowed,
    assert_allowed,
    is_allowed,
)

S = TicketState
A = Actor


def test_ai_may_only_perform_its_three_whitelisted_edges():
    ai_allowed = {
        (f, t)
        for f, t in itertools.product(S, S)
        if is_allowed(f, t, A.AI)
    }
    assert ai_allowed == set(AI_WHITELIST)
    assert ai_allowed == {
        (S.NEW, S.AI_HANDLING),
        (S.AI_HANDLING, S.RESOLVED),
        (S.AI_HANDLING, S.ESCALATED),
    }


def test_ai_cannot_close_or_claim_or_reopen():
    assert not is_allowed(S.RESOLVED, S.CLOSED, A.AI)
    assert not is_allowed(S.ESCALATED, S.WITH_AGENT, A.AI)
    assert not is_allowed(S.CLOSED, S.REOPENED, A.AI)
    assert not is_allowed(S.WITH_AGENT, S.RESOLVED, A.AI)


def test_agent_and_system_edges():
    assert is_allowed(S.ESCALATED, S.WITH_AGENT, A.AGENT)  # claim
    assert is_allowed(S.WITH_AGENT, S.RESOLVED, A.AGENT)
    assert is_allowed(S.RESOLVED, S.CLOSED, A.SYSTEM)  # idle close
    assert is_allowed(S.AI_HANDLING, S.RESOLVED, A.SYSTEM)  # idle auto-resolve
    assert is_allowed(S.REOPENED, S.WITH_AGENT, A.SYSTEM)  # route to prior agent


def test_customer_can_reopen_but_not_arbitrary_moves():
    assert is_allowed(S.RESOLVED, S.REOPENED, A.CUSTOMER)
    assert is_allowed(S.CLOSED, S.REOPENED, A.CUSTOMER)
    assert not is_allowed(S.NEW, S.AI_HANDLING, A.CUSTOMER)
    assert not is_allowed(S.AI_HANDLING, S.RESOLVED, A.CUSTOMER)


def test_assert_allowed_raises_on_illegal_edge():
    with pytest.raises(TransitionNotAllowed):
        assert_allowed(S.WITH_AGENT, S.RESOLVED, A.AI)
