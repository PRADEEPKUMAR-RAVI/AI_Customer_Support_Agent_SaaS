"""FakeLLM — deterministic, offline stand-in (dev/CI default).

Returns canned structured output and can replay scripted tool calls, so the engine loop and
its tests run with no OpenAI key and produce the same output every run.
"""

from __future__ import annotations

from typing import Any

from app.infra.llm.base import LLMPort, LLMResult, ToolCall


class FakeLLM(LLMPort):
    supports_tools = True
    supports_structured_output = True

    def __init__(self, *, scripted_tool_calls: list[ToolCall] | None = None,
                 answer: str = "This is a grounded fake answer.",
                 structured: dict[str, Any] | None = None) -> None:
        # Tool calls are popped one per turn to simulate a bounded tool loop.
        self._scripted = list(scripted_tool_calls or [])
        self._answer = answer
        self._structured = structured or {
            "answer_complete": True,
            "detected_language": "en",
            "tags": [{"name": "general", "status": "approved"}],
            "retrieval_hits": 1,
            "escalate": False,
            "escalation_reason": None,
            "advisory_confidence": 0.9,
        }

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResult:
        if self._scripted:
            call = self._scripted.pop(0)
            return LLMResult(tool_calls=[call], model=model or "fake")
        return LLMResult(
            text=self._answer,
            structured=self._structured if response_schema is not None else None,
            prompt_tokens=len(str(messages)) // 4,
            completion_tokens=len(self._answer) // 4,
            model=model or "fake",
        )
