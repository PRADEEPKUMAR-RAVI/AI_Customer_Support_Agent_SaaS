"""Guardrails: prompt-injection delimiting of tool results ([IMP-SEC-4]) + canned safe replies.

Retrieved KB text and record fields are passed to the model ONLY as delimited tool-result
messages — never concatenated into the system prompt — with a standing instruction (in the
system prompt) that everything inside the delimiters is untrusted data.
"""

from __future__ import annotations

import json
from typing import Any

_OPEN, _CLOSE = "<tool_result>", "</tool_result>"

# Customer-facing canned turns (safe, no model involvement).
HUMAN_TAKING_OVER = "Thanks — I'm connecting you with a human agent who can help. They'll reply here."
NO_CONFIDENT_ANSWER = "I couldn't find a confident answer to that, so I'm getting a human to help you."
KB_NOT_READY_MSG = (
    "I'm still learning this business's documents. Would you like me to connect you with a "
    "human agent in the meantime?"
)
ALREADY_WITH_HUMAN = "A human agent is handling this conversation — they'll reply here shortly."
# Deterministic record-state dispute ([A1]) — void warranty / delivered-but-not-received / cancelled-refund.
DISPUTE_HANDOFF = (
    "I understand this needs closer attention — I'm connecting you with a human agent who can "
    "look into it for you."
)
# Durable verify-attempt lockout ([IMP-SEC-6]) — never distinguishes not_found from unverified.
VERIFY_LOCKED = (
    "For your security I can't make more verification attempts on this right now. I'm connecting "
    "you with a human agent who can help."
)
# Proactive human offer ([A2]) — asked before a hard escalate on a low-confidence / not-ready turn.
PROACTIVE_OFFER = "I'm not able to answer that confidently. Would you like me to connect you with a human agent?"
# Turn-level safety guard fired ([IMP-ENG-3]/[IMP-ENG-1]) — stall/timeout or unusable model envelope.
ENGINE_GUARD_HANDOFF = "Sorry — I'm having trouble completing that right now, so I'm getting a human to help you."


def delimit_tool_result(tool_name: str, payload: Any, *, tool_call_id: str | None = None) -> dict:
    """Wrap a tool result as a `tool`-role message with explicit untrusted-data delimiters.

    ``tool_call_id`` links the response to the assistant's tool call (required by OpenAI's tool
    protocol; harmless for FakeLLM)."""
    body = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    msg: dict = {"role": "tool", "content": f"{_OPEN}\n{body}\n{_CLOSE}"}
    if tool_call_id:
        msg["tool_call_id"] = tool_call_id
    return msg
