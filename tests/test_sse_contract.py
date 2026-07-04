"""SSE contract drift gate: the shared fixture must validate against the Pydantic union, and
frames must round-trip. The frontend runs the mirror of this test against the same fixture."""

from __future__ import annotations

import json
import pathlib

from app.schemas.sse import FinalEvent, StatusEvent, parse_event, to_sse_frame

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "contracts" / "sse_events.fixture.json"


def test_fixture_events_validate_against_union():
    events = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(events) >= 6
    parsed = [parse_event(ev) for ev in events]
    # The sequence ends with a single validated control envelope, then done.
    assert any(isinstance(e, FinalEvent) for e in parsed)
    assert isinstance(parsed[0], StatusEvent)


def test_final_event_carries_control_metadata_only():
    final = parse_event(
        {
            "type": "final",
            "answer_complete": True,
            "detected_language": "es",
            "tags": [{"name": "billing", "status": "pending"}],
            "retrieval_hits": 3,
            "escalate": True,
            "escalation_reason": "dispute",
            "advisory_confidence": 0.4,
        }
    )
    assert isinstance(final, FinalEvent)
    assert final.escalate is True
    assert final.escalation_reason.value == "dispute"


def test_frame_round_trips():
    ev = StatusEvent(stage="retrieving")
    frame = to_sse_frame(ev, seq=1)
    assert frame.startswith("event: status\n")
    assert "id: 1\n" in frame
    assert frame.endswith("\n\n")
    # data line parses back to the same event
    data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
    payload = json.loads(data_line[len("data: "):])
    assert parse_event(payload).stage == "retrieving"
