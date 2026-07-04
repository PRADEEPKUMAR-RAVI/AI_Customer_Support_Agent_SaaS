"""Redis-backed rate limiting (fixed window).

Applied to the public, anonymous widget endpoints keyed on (tenant_id, widget_key, client IP)
so the paid LLM path can't be abused, and reused for the durable identity verify-attempt
counter keyed on (tenant_id, record_type, key) ([IMP-SEC-3], [IMP-SEC-6]).
"""

from __future__ import annotations

from app.infra.cache.redis import get_redis


async def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Increment the counter for ``key``; return True if still within ``limit`` for the window.
    The first hit sets the TTL. Returns False once the limit is exceeded."""
    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count <= limit


async def current(key: str) -> int:
    redis = get_redis()
    val = await redis.get(key)
    return int(val) if val is not None else 0


async def reset(key: str) -> None:
    await get_redis().delete(key)
