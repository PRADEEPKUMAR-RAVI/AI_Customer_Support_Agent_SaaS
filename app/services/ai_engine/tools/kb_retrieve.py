"""kb_retrieve tool — thin wrapper over M3. Returns GroundedResult or a signal string; the
ENGINE (not the model) turns that into answer-vs-NO_GROUNDING (the grounding-gate non-negotiable).
"""

from __future__ import annotations

from app.services.knowledge_service import kb_retrieve


async def kb_retrieve_tool(session, args: dict, *, threshold: float | None):
    query = (args or {}).get("query", "").strip()
    if not query:
        from app.services.knowledge_service import NO_GROUNDING

        return NO_GROUNDING
    return await kb_retrieve(session, query, threshold=threshold)
