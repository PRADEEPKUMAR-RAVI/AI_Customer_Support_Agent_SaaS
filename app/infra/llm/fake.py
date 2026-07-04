"""FakeLLM — deterministic, offline stand-in (dev/CI default; no OpenAI key).

Minimally input-aware so it drives a realistic single-retrieve tool loop for ANY query:
  * first pass (tools available, no tool result yet) → call ``kb_retrieve`` with the user's text
  * after a tool result is present → return a final answer + the structured control metadata

Crucially it does NOT decide grounding/escalation — the ENGINE decides that from the tool
RESULT (non-negotiable). So the flow branches on retrieval, not on this fake's cleverness.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.infra.llm.base import LLMPort, LLMResult, ToolCall

_DEFAULT_META = {
    "answer_complete": True,
    "detected_language": "en",
    "tags": ["general"],
    "retrieval_hits": 0,
    "escalate": False,
    "escalation_reason": None,
    "advisory_confidence": 0.9,
}


class FakeLLM(LLMPort):
    supports_tools = True
    supports_structured_output = True

    def __init__(self, *, answer: str = "Here's what I found in our documentation.") -> None:
        self._answer = answer

    @staticmethod
    def _last_user(messages: list[dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))
        return ""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResult:
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if tools and not has_tool_result:
            return LLMResult(
                tool_calls=[ToolCall(
                    id="call_" + uuid.uuid4().hex[:8],
                    name="kb_retrieve",
                    arguments={"query": self._last_user(messages)},
                )],
                model=model or "fake",
                prompt_tokens=len(str(messages)) // 4,
            )
        return LLMResult(
            text=self._answer,
            structured=dict(_DEFAULT_META) if response_schema is not None else None,
            prompt_tokens=len(str(messages)) // 4,
            completion_tokens=len(self._answer) // 4,
            model=model or "fake",
        )
