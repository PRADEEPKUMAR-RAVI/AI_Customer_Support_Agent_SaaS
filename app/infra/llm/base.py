"""LLMPort — the swappable seam for the language model.

The POC uses a single provider (gpt-4o-mini) for the tool loop, structured output, and aux
tasks (audit §14.0; Groq dropped). The port keeps capability flags so a future non-tool aux
model could slot in without assuming parity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""  # provider tool-call id — threaded back as tool_call_id (OpenAI protocol)


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


@runtime_checkable
class LLMPort(Protocol):
    supports_tools: bool
    supports_structured_output: bool

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResult: ...
