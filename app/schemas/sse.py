"""The SSE event protocol — the single source of truth for the streamed chat turn.

OpenAPI codegen cannot describe an ``text/event-stream``, so this discriminated union is
authored once here (Pydantic) and mirrored to a TS type in ``frontend/src/types/sse.ts``.
A shared fixture (``contracts/sse_events.fixture.json``) is asserted by both a backend test
(``tests/test_sse_contract.py``) and a frontend test — the drift gate (audit [A?]/[IMP-FE-5]).

Key design point [IMP-ENG-1]: the natural-language answer streams ONLY on ``token`` events;
all validated control metadata (tags, escalate, detected_language, answer_complete, …) rides
the single trailing ``final`` event, so streaming and JSON-validation never fight.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from app.domain.escalation.reasons import EscalationReason


class StatusEvent(BaseModel):
    """Progress affordance during the pre-first-token tool phase. The widget maps ``stage``
    to a pre-translated chrome string, so filler is localised without server-side language
    knowledge [IMP-ENG-7]."""

    type: Literal["status"] = "status"
    stage: Literal["retrieving", "looking_up", "generating", "waiting"]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class Citation(BaseModel):
    index: int
    source_id: str
    title: str
    page_number: int | None = None  # [A13] file sources render "from <file>, p.<n>"
    source_url: str | None = None    # [A13] crawled pages render a clickable link


class CitationEvent(BaseModel):
    type: Literal["citation"] = "citation"
    citation: Citation


class Tag(BaseModel):
    """Tags are {name, status} objects, never plain strings (PRD §4.2.3)."""

    name: str
    status: Literal["approved", "pending"]


class FinalEvent(BaseModel):
    """The validated per-turn control envelope. Emitted once, after the answer tokens."""

    type: Literal["final"] = "final"
    answer_complete: bool = False  # [A5] gates the closing question / auto-resolve path
    detected_language: str  # BCP-47, e.g. "en", "es", "hi"
    tags: list[Tag] = Field(default_factory=list)
    retrieval_hits: int = 0
    escalate: bool = False
    escalation_reason: EscalationReason | None = None
    # Observability only — NEVER the escalation trigger (that is retrieval-grounding-based).
    advisory_confidence: float | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    turn_id: str
    ticket_state: str


SSEEvent = Annotated[
    Union[StatusEvent, TokenEvent, CitationEvent, FinalEvent, ErrorEvent, DoneEvent],
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[SSEEvent] = TypeAdapter(SSEEvent)


def parse_event(data: dict | str) -> SSEEvent:
    """Validate an inbound event payload against the union (raises on drift)."""
    if isinstance(data, (bytes, bytearray, str)):
        return _ADAPTER.validate_json(data)
    return _ADAPTER.validate_python(data)


def to_sse_frame(event: SSEEvent, seq: int | None = None) -> str:
    """Render an event as a wire SSE frame: ``event:``/``id:``/``data:`` lines.

    ``id:`` is a monotonic sequence carried at the transport layer only (kept trivially, per
    trim [T7]); reconnect relies on ``client_msg_id`` idempotent whole-turn replay, not a
    per-event replay buffer.
    """
    payload = event.model_dump(mode="json", exclude_none=True)
    lines = [f"event: {payload['type']}"]
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"data: {json.dumps(payload, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"
