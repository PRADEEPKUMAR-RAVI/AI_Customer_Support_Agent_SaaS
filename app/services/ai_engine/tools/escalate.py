"""escalate tool — the model can REQUEST a hand-off (a soft/sensitive signal). The engine still
decides and performs the actual transition via the whitelist. Returns a marker the engine reads.
"""

from __future__ import annotations


def escalate_tool(args: dict) -> dict:
    return {"escalate_requested": True, "reason": (args or {}).get("reason", "")}
