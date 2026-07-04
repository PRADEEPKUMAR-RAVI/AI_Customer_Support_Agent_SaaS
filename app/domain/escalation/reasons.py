"""Canonical escalation-reason taxonomy (audit [C6]).

One source of truth: M6 raises it, M2 records it into ``turn_metric``, M8 groups by it.
Extends the PRD §4.5 named triggers with ``dispute`` (deterministic record-state
escalations — void warranty / delivered-but-not-received / cancelled-refund-not-in-KB [A1])
and ``timeout`` (the per-turn stall path, PRD §4.1).
"""

from __future__ import annotations

import enum


class EscalationReason(str, enum.Enum):
    NO_GROUNDING = "no_grounding"  # retrieval cleared nothing AND no tool answer (PRD §4.5)
    EXPLICIT = "explicit"          # customer asked for a human (or accepted the proactive offer)
    SENSITIVE = "sensitive"        # tenant-configured sensitive-intent hit (refund/legal/…)
    DISPUTE = "dispute"            # deterministic, code-driven record-state escalation [A1]
    N_FAILS = "n_fails"            # same issue unresolved after N attempts
    PROACTIVE = "proactive"        # customer accepted the "connect you to a human?" offer [A2]
    TIMEOUT = "timeout"            # per-turn timeout / stall guard fired (PRD §4.1)
