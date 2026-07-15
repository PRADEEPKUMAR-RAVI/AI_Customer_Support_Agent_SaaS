"""AI-engine tools. Transitions are NOT a model tool — they're code-enforced via the whitelist.

`lookup_record` is deliberately NOT exposed to the model: record lookups are driven by ENGINE code
(``engine.run_turn`` calls ``lookup_record_tool`` once it has the extracted key + verify value), so
they don't depend on the model choosing to call a tool or constructing its arguments correctly —
which proved unreliable across turns. The model only EXTRACTS the slot values into the turn
metadata. So the model-facing menu is just KB retrieval + escalate. (``lookup_record_tool`` is still
imported here — the engine imports it from this package — and the engine's tool loop still tolerates
a hallucinated ``lookup_record`` call for defence in depth.)"""

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
            "name": "escalate",
            "description": "Hand the conversation to a human agent.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        },
    },
]
