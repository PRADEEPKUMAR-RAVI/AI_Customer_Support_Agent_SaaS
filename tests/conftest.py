"""Test config. Pure-logic tests run anywhere (no services). Tests marked ``rls`` need a live
Postgres with the migration applied and are skipped unless ``RUN_RLS_TESTS=1``."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_RLS_TESTS") == "1":
        return
    skip_rls = pytest.mark.skip(reason="set RUN_RLS_TESTS=1 with a live Postgres to run")
    for item in items:
        if "rls" in item.keywords:
            item.add_marker(skip_rls)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engines_between_tests():
    """The app's async engines are module-level singletons, but pytest-asyncio runs each test in
    its OWN event loop. A pooled asyncpg connection bound to a now-closed loop then blows up on
    the next test ("Event loop is closed" -> AttributeError). Disposing after every test makes
    the next test's loop get a fresh pool. Covers both the app engine and the lazily-built
    BYPASSRLS engine (used by M10 ops / auth bootstrap)."""
    yield
    from app.infra.cache.redis import get_redis
    from app.infra.db.engine import engine, get_bypass_sessionmaker

    await engine.dispose()
    if get_bypass_sessionmaker.cache_info().currsize:
        bind = get_bypass_sessionmaker().kw.get("bind")
        if bind is not None:
            await bind.dispose()
        get_bypass_sessionmaker.cache_clear()
    # The Redis client is an lru_cache'd singleton bound to the loop that first used it — reset it
    # too so the next test's loop gets a fresh connection pool.
    if get_redis.cache_info().currsize:
        client = get_redis()
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 — older redis-py exposes close(); either way, best-effort
            pass
        get_redis.cache_clear()
