"""OAuth2 client-credentials token acquisition + short-lived cache for API connectors ([T4]).

Fetches an access token from the tenant's token endpoint (SSRF-validated, fetch-only) and caches
it in Redis keyed by ``(connector_id, version)`` with a TTL just under the token's expiry. A version
bump or a delete orphans the key (its TTL reaps it — no explicit invalidation needed). A
``connector_id`` of ``None`` (test-before-save) always fetches fresh and caches nothing.
"""

from __future__ import annotations

import httpx

from app.core.config import TenantDefaults
from app.core.ssrf import SSRFBlocked, resolve_and_validate
from app.infra.connectors.base import ConnectorError

_TTL_MARGIN_SECONDS = 60  # refresh a minute before the provider's expiry to avoid edge-of-expiry 401s


async def get_access_token(
    *,
    connector_id: str | None,
    version: int | None,
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    cache_key = f"oauth:{connector_id}:{version}" if connector_id else None
    if cache_key:
        cached = await _cache_get(cache_key)
        if cached:
            return cached

    try:
        resolve_and_validate(token_url)  # blocks localhost / private / cloud-metadata
    except SSRFBlocked as exc:
        raise ConnectorError("connection", f"blocked token URL: {exc}") from exc

    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        data["scope"] = scope

    timeout = TenantDefaults.CONNECTOR_TIMEOUT_SECONDS
    try:
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=timeout, transport=transport
        ) as client:
            resp = await client.post(token_url, data=data)
    except httpx.TimeoutException as exc:
        raise ConnectorError("timeout", "OAuth token request timed out") from exc
    except httpx.HTTPError as exc:
        raise ConnectorError("connection", str(exc)[:200]) from exc

    if resp.status_code in (401, 403):
        raise ConnectorError("auth", f"token endpoint returned {resp.status_code}")
    if resp.status_code >= 400:
        raise ConnectorError("connection", f"token endpoint returned {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ConnectorError("connection", "non-JSON token response") from exc
    token = payload.get("access_token")
    if not token:
        raise ConnectorError("auth", "token response missing access_token")

    if cache_key:
        expires_in = int(payload.get("expires_in", 3600) or 3600)
        ttl = max(expires_in - _TTL_MARGIN_SECONDS, 1)
        await _cache_set(cache_key, token, ttl)
    return token


async def clear_cached_token(connector_id: str, version: int) -> None:
    """Best-effort drop of a connector's cached token (on delete/rotate). TTL would reap it anyway."""
    from app.infra.cache.redis import get_redis

    await get_redis().delete(f"oauth:{connector_id}:{version}")


async def _cache_get(key: str) -> str | None:
    from app.infra.cache.redis import get_redis  # lazy so importing needs no live Redis

    return await get_redis().get(key)  # decode_responses=True -> str | None


async def _cache_set(key: str, value: str, ttl: int) -> None:
    from app.infra.cache.redis import get_redis

    await get_redis().setex(key, ttl, value)
