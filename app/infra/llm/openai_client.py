"""Real OpenAI adapter (gpt-4o-mini). Used only when ``USE_FAKE_LLM=false``.

The ``openai`` SDK is imported lazily so the package (and the whole dev/CI run on fakes)
never requires the SDK or an API key to be present.
"""

from __future__ import annotations

import json
from typing import Any

from app.infra.llm.base import LLMPort, LLMResult, ToolCall


class OpenAIClient(LLMPort):
    supports_tools = True
    supports_structured_output = True

    def __init__(self, *, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when USE_FAKE_LLM=false")
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy import

            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> LLMResult:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "turn_output", "schema": response_schema, "strict": True},
            }
        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
            for tc in (choice.tool_calls or [])
        ]
        structured = None
        if response_schema is not None and choice.content:
            structured = json.loads(choice.content)
        usage = resp.usage
        return LLMResult(
            text=choice.content or "",
            tool_calls=tool_calls,
            structured=structured,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=resp.model,
        )
