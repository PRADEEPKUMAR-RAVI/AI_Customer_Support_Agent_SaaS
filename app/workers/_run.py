"""Helper to run an async coroutine inside a (sync) Celery task.

Each task run gets a fresh event loop; the global async engine's pooled connections are bound
to a loop, so we dispose the engine at the end of every task to avoid 'Event loop is closed' on
the next run. (POC-simple; a long-lived per-worker loop is a later optimisation.)
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine


def run_async(coro: Coroutine) -> Any:
    async def _wrapper():
        try:
            return await coro
        finally:
            from app.infra.db.engine import engine

            await engine.dispose()

    return asyncio.run(_wrapper())
