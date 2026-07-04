"""Export the OpenAPI spec (the contract the FE typed client is generated from) and validate
that the checked-in SSE fixture still round-trips against the Pydantic union (drift gate)."""

from __future__ import annotations

import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "contracts"
OPENAPI_OUT = CONTRACTS / "openapi.json"
SSE_FIXTURE = CONTRACTS / "sse_events.fixture.json"


def main() -> None:
    from app.main import app
    from app.schemas.sse import parse_event

    CONTRACTS.mkdir(exist_ok=True)
    OPENAPI_OUT.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"wrote {OPENAPI_OUT.relative_to(REPO_ROOT)}")

    if SSE_FIXTURE.exists():
        events = json.loads(SSE_FIXTURE.read_text(encoding="utf-8"))
        for ev in events:
            parse_event(ev)  # raises if the fixture drifts from the union
        print(f"validated {len(events)} SSE fixture events against the union")


if __name__ == "__main__":
    main()
