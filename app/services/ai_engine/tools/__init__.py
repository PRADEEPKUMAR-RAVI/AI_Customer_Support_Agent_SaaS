"""AI-engine tools. Transitions are NOT a model tool — they're code-enforced via the whitelist
in the engine — so only KB retrieval, record lookup, and escalate are exposed to the model."""

from app.services.ai_engine.tools.escalate import escalate_tool  # noqa: F401
from app.services.ai_engine.tools.kb_retrieve import kb_retrieve_tool  # noqa: F401
from app.services.ai_engine.tools.lookup_record import lookup_record_tool  # noqa: F401

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "kb_retrieve",
            "description": "Search the business knowledge base to answer a general question.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_record",
            "description": (
                "Look up a customer's personal record (order/warranty/etc.) AFTER collecting the "
                "lookup key and one identity verification value."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "record_type": {"type": "string"},
                    "key": {"type": "string"},
                    "verify_value": {"type": "string"},
                },
                "required": ["record_type", "key", "verify_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Hand the conversation to a human agent.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
]
