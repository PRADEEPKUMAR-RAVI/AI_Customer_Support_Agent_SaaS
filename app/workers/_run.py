"""Helper to run an async coroutine inside a (sync) Celery task.

Each task run gets a fresh event loop via ``asyncio.run``. Worker DB access goes through the
NullPool ``worker_engine`` (see ``app/infra/db/engine.py``): it opens a fresh connection per
checkout and closes it on return, so nothing is pooled across per-task loops and there is no
engine to dispose here. (The previous per-task ``engine.dispose()`` only papered over cross-loop
pooled connections — which raised asyncpg's "attached to a different loop"; NullPool removes the
cause instead.)
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine


def run_async(coro: Coroutine) -> Any:
    return asyncio.run(coro)
