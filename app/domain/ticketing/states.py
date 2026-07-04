"""Ticket lifecycle states and the actors permitted to drive transitions (PRD §4.2.1)."""

from __future__ import annotations

import enum


class TicketState(str, enum.Enum):
    NEW = "new"
    AI_HANDLING = "ai_handling"
    ESCALATED = "escalated"
    WITH_AGENT = "with_agent"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"  # transient router state — the system routes it onward immediately


class Actor(str, enum.Enum):
    AI = "ai"
    AGENT = "agent"
    SYSTEM = "system"
    CUSTOMER = "customer"


class Priority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
