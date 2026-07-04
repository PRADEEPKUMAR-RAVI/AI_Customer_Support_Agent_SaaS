"""Model router — resolves the active ``LLMPort`` from settings.

Single provider for the POC (gpt-4o-mini). Kept as a seam so a cheaper aux model or a
different provider (e.g. Claude, per PRD §4.1) can be reintroduced later without touching
callers. Fakes are the dev/CI default.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.infra.llm.base import LLMPort


@lru_cache
def get_llm() -> LLMPort:
    settings = get_settings()
    if settings.use_fake_llm:
        from app.infra.llm.fake import FakeLLM

        return FakeLLM()
    from app.infra.llm.openai_client import OpenAIClient

    return OpenAIClient(api_key=settings.openai_api_key, model=settings.llm_model)
