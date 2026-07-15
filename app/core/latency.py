"""Lightweight latency instrumentation ([IMP-OBS] / perf).

Logs per-phase timings to the console under the ``app.latency`` logger (INFO) so the
first-query cold-load cost — the OpenAI client connect and the one-time ONNX embed/reranker
model load — is visible without a profiler. Time-to-first-token equals whole-turn latency here
because the SSE stream is computed-then-streamed (see ``conversation_service``), so these phase
timers ARE the perceived-latency breakdown.

Timing only: a phase name, milliseconds, and small numeric/boolean/id fields (counts, flags,
conversation ids). NEVER pass message content, queries, verify values, or record data as a field
— the ``RedactionFilter`` is only a backstop.

Usage::

    async with atimed("kb.rerank") as span:      # async hot paths
        hits = await embedder.rerank(...)
        span["docs"] = len(cand_rows)             # fields discovered mid-block

    with timed("rerank.model_load", model=name):  # sync (e.g. lazy model construction)
        self._reranker = TextCrossEncoder(...)
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager, contextmanager

log = logging.getLogger("app.latency")


def log_latency(phase: str, ms: float, **fields: object) -> None:
    """Emit one ``<phase> ms=<n> k=v ...`` INFO line. ``None`` fields are dropped."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    if extra:
        log.info("%s ms=%.0f %s", phase, ms, extra)
    else:
        log.info("%s ms=%.0f", phase, ms)


@contextmanager
def timed(phase: str, **fields: object):
    """Time a synchronous block; logs on exit even if it raises. Yields a mutable dict so the
    caller can attach fields discovered during the block."""
    span: dict[str, object] = dict(fields)
    start = time.perf_counter()
    try:
        yield span
    finally:
        log_latency(phase, (time.perf_counter() - start) * 1000.0, **span)


@asynccontextmanager
async def atimed(phase: str, **fields: object):
    """Async counterpart of :func:`timed` — for awaited hot paths (LLM steps, retrieval)."""
    span: dict[str, object] = dict(fields)
    start = time.perf_counter()
    try:
        yield span
    finally:
        log_latency(phase, (time.perf_counter() - start) * 1000.0, **span)
