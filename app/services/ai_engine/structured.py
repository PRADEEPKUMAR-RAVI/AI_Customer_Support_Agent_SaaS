"""Per-turn structured control envelope + tag clamping ([IMP-ENG-1], PRD §4.2.3, §5.3).

The natural-language ANSWER streams as `token` events; this validated metadata rides the single
trailing `final` event. Control fields the engine owns (escalate / escalation_reason /
retrieval_hits) are set by the engine, not trusted from the model. Model-proposed tags are
clamped against the tenant's allowed list — never trusted as raw strings for control.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.escalation.reasons import EscalationReason
from app.schemas.sse import Tag


class TurnMetadata(BaseModel):
    """The model-advisory + engine-owned per-turn control envelope (validated before use)."""

    answer_complete: bool = False
    detected_language: str = "en"          # BCP-47
    tags: list[str] = Field(default_factory=list)   # RAW model-proposed names (pre-clamp)
    retrieval_hits: int = 0                # engine-owned
    escalate: bool = False                 # engine-owned
    escalation_reason: EscalationReason | None = None  # engine-owned
    advisory_confidence: float | None = None  # observability only — NEVER the escalate trigger


# JSON schema handed to a real LLM's structured-output mode (metadata only; the answer streams).
# Strict-compliant for OpenAI: every property is listed in `required` (advisory_confidence is
# nullable) and additionalProperties is false.
TURN_METADATA_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer_complete": {"type": "boolean"},
        "detected_language": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "advisory_confidence": {"type": ["number", "null"]},
    },
    "required": ["answer_complete", "detected_language", "tags", "advisory_confidence"],
}


def clamp_tags(raw_tags: list[str], allowed: list[str]) -> list[Tag]:
    """Known tag → approved; unknown → pending (surfaced in the admin tray). De-duplicated,
    normalised. The model can propose a net-new tag, but it is never auto-trusted."""
    allowed_set = {a.strip().lower() for a in (allowed or [])}
    out: list[Tag] = []
    seen: set[str] = set()
    for name in raw_tags or []:
        n = name.strip().lower().replace(" ", "_")
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(Tag(name=n, status="approved" if n in allowed_set else "pending"))
    return out
