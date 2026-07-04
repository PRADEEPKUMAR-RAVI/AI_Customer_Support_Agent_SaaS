"""Redis client factory (cache, idempotency locks, pub/sub). Async redis-py."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_redis():
    import redis.asyncio as aioredis  # lazy so importing the package needs no live Redis

    return aioredis.from_url(get_settings().redis_url, decode_responses=True)
