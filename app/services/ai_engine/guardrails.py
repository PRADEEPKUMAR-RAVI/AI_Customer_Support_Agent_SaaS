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


# ── Deterministic, code-owned replies for NON-grounded conversational turns ──────────────────
# The grounding gate (non-negotiable #3) forbids shipping model-authored prose on a turn where
# nothing was grounded and no record was verified — the model could fabricate a fact. So for
# greetings, capability questions, out-of-scope questions, and record-lookup slot-filling, the
# ENGINE emits these FIXED, schema-derived replies (built from code + tenant config + the industry
# template — never from model free text). The model only CLASSIFIES the turn (turn_type); the code
# owns the words, so no fabricated fact can pass the gate. (English for the POC; per-language
# templates are a follow-up — the widget already localises its own chrome.)

_FIELD_LABELS = {
    "order_id": "order number", "serial_no": "serial number", "tracking_no": "tracking number",
    "account_id": "account ID", "booking_ref": "booking reference", "email": "email address",
    "phone": "phone number", "registered_mobile": "registered mobile number",
    "dob": "date of birth", "last_name": "last name",
}


def _label(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " "))


def _schemas_for(industry: str) -> dict:
    from app.domain.records.schemas import INDUSTRY_SCHEMAS, Industry

    try:
        return INDUSTRY_SCHEMAS.get(Industry(industry), {})
    except ValueError:
        return {}


def _record_types_phrase(industry: str) -> str:
    names = [rt.replace("_", " ") for rt in _schemas_for(industry)]
    if not names:
        return "your account details"
    if len(names) == 1:
        return f"your {names[0]}"
    return "your " + ", ".join(names[:-1]) + f" or {names[-1]}"


def slot_fill_prompt(industry: str, record_type: str | None) -> str:
    """Ask the customer for the lookup key + verify value a record lookup needs — built from the
    industry schema, so it names the right fields per sector and never invents record facts."""
    schemas = _schemas_for(industry)
    schema = schemas.get(record_type or "")
    if schema is None and len(schemas) == 1:  # unambiguous industry — use its only record type
        record_type, schema = next(iter(schemas.items()))
    if schema is None:  # unknown / ambiguous — ask which record and for its details
        return (
            "I can help with that. Which would you like me to look up — "
            f"{_record_types_phrase(industry)} — and could you share the details on it?"
        )
    keys = " or ".join(_label(k) for k in schema.all_key_fields)
    verifies = " or ".join(_label(v.field) for v in schema.verify)
    return (
        f"Sure — to look up your {record_type.replace('_', ' ')}, could you share your {keys}, "
        f"and your {verifies} so I can verify it's you?"
    )


def smalltalk_reply(cfg: dict) -> str:
    """A friendly greeting/social reply — the tenant's configured welcome, or a safe default."""
    return cfg.get("welcome_message") or "Hi! I'm here to help. What can I do for you today?"


def capability_reply(industry: str) -> str:
    """What the assistant can do — grounded in the tenant's actual capabilities, no invented ones."""
    return (
        "I'm the support assistant here. I can answer questions about this business's products, "
        f"services and policies, and look up {_record_types_phrase(industry)} once I've verified "
        "you. What can I help you with?"
    )


def out_of_scope_reply(industry: str) -> str:
    """Politely decline a question unrelated to this business's domain — no guess, no hand-off."""
    return (
        "That's a bit outside what I can help with here — I'm focused on this business's products, "
        f"services and {_record_types_phrase(industry)}. Is there something along those lines I "
        "can help you with?"
    )


def render_record_answer(record_type: str, record: dict) -> str:
    """Deterministic, natural rendering of a VERIFIED record — the safe fallback used only when the
    model produced no phrasing (e.g. FakeLLM). With a real LLM the engine prefers the model's own
    wording (grounded in this record, in the customer's language). Uses the PRD §4.3/§4.4 per-state
    phrasing for order/warranty; a clean sentence from the returned fields for other industries.
    Never a raw dict, never invents fields not present."""
    r = record or {}
    if record_type == "order":
        status = str(r.get("status", "")).lower()
        eta, ref, url = r.get("eta"), r.get("tracking_ref"), r.get("tracking_url")
        track = f" You can track it here: {url}" if url else (f" Tracking reference: {ref}." if ref else "")
        if status in ("placed", "processing"):
            return f"Your order is being prepared and is expected by {eta}." if eta else "Your order is being prepared to ship."
        if status == "shipped":
            base = f"Your order has shipped and is expected by {eta}." if eta else "Your order has shipped."
            return base + track
        if status == "delivered":
            return f"Your order was delivered on {eta}." if eta else "Your order has been delivered."
        if status == "cancelled":
            return "Your order has been cancelled."
        return f"Your order status is: {status or 'unavailable'}." + (f" Expected by {eta}." if eta else "")
    if record_type == "warranty":
        coverage, expiry = str(r.get("coverage", "")).lower(), r.get("expiry")
        if coverage == "active":
            return f"Your warranty is active and is valid until {expiry}." if expiry else "Your warranty is active."
        if coverage == "expired":
            return f"Your warranty expired on {expiry}." if expiry else "Your warranty has expired."
        if coverage == "void":
            return "Your warranty is currently marked void."
        return f"Your warranty status is: {coverage or 'unavailable'}."
    # Other industries (shipment / subscription / billing / appointment / booking): a readable
    # sentence from whatever returned fields are present — not a raw dict.
    parts = [f"{k.replace('_', ' ')}: {v}" for k, v in r.items() if v not in (None, "")]
    return ("Here are your details — " + "; ".join(parts) + ".") if parts else "I found your record."
