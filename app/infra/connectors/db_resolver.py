"""DbResolver — fetch a record live from a tenant's own database ([T4]: Postgres).

Connects to the **tenant's external DB** (a tenant-supplied DSN), never the app DB. Security
([IMP-SEC-5]): the DB host is SSRF-validated (blocks localhost / private / cloud-metadata) before
connecting; the query is a **parameterized template** (``… WHERE key = :key``) so the untrusted
lookup key is never string-built into SQL. Fetch only — verification stays in the engine.

A short-lived async engine is cached per ``(connector_id, version)`` and reused across lookups;
bump the connector's ``version`` on edit to invalidate. 5s wall-clock timeout + 1 retry.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import TenantDefaults
from app.core.ssrf import SSRFBlocked, resolve_and_validate
from app.infra.connectors.base import NOT_FOUND, ConnectorError, RawRecord, _NotFound

_ENGINE_CACHE: dict[tuple[str, int], AsyncEngine] = {}


def normalize_pg_dsn(dsn: str) -> str:
    """Force a Postgres DSN onto the async driver ([T4]: Postgres only). ``postgresql://…`` (or any
    ``+driver``) -> ``postgresql+asyncpg://…``; a non-Postgres scheme is rejected so a mistyped
    ``mysql://`` fails clearly at config time instead of deep in SQLAlchemy."""
    scheme, sep, rest = dsn.strip().partition("://")
    if not sep:
        raise ConnectorError("connection", "invalid DSN (missing scheme)")
    if scheme.split("+", 1)[0] not in ("postgresql", "postgres"):
        raise ConnectorError("connection", "only PostgreSQL sources are supported for now")
    return f"postgresql+asyncpg://{rest}"


async def dispose_engine(connector_id: str) -> None:
    """Best-effort disposal of any cached engine(s) for a connector (on delete). Version-key
    invalidation already keeps lookups correct; this frees the pool promptly."""
    for stale in [k for k in _ENGINE_CACHE if k[0] == connector_id]:
        engine = _ENGINE_CACHE.pop(stale, None)
        if engine is not None:
            await engine.dispose()


def _validate_db_host(dsn: str) -> None:
    parts = urlsplit(dsn)
    host, port = parts.hostname, parts.port or 5432
    if not host:
        raise ConnectorError("connection", "missing DB host in DSN")
    try:
        resolve_and_validate(f"http://{host}:{port}")  # DNS + private/loopback/metadata block
    except SSRFBlocked as exc:
        raise ConnectorError("connection", f"blocked DB host: {exc}") from exc


def _get_engine(connector_id: str, version: int, dsn: str) -> AsyncEngine:
    key = (connector_id, version)
    engine = _ENGINE_CACHE.get(key)
    if engine is None:
        for stale in [k for k in _ENGINE_CACHE if k[0] == connector_id and k[1] != version]:
            _ENGINE_CACHE.pop(stale, None)  # drop superseded versions (GC disposes)
        engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=2, max_overflow=0)
        _ENGINE_CACHE[key] = engine
    return engine


async def _run_query(
    engine: AsyncEngine, query_template: str, key: str, field_map: dict[str, str]
) -> RawRecord | _NotFound:
    async def _once() -> RawRecord | _NotFound:
        async with engine.connect() as conn:
            row = (await conn.execute(text(query_template), {"key": str(key)})).mappings().first()
            if row is None:
                return NOT_FOUND
            # field_map: {source_column: schema_field}
            return {sf: row[src] for src, sf in field_map.items() if src in row}

    timeout = TenantDefaults.CONNECTOR_TIMEOUT_SECONDS
    for attempt in range(TenantDefaults.CONNECTOR_RETRIES + 1):
        try:
            return await asyncio.wait_for(_once(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            if attempt >= TenantDefaults.CONNECTOR_RETRIES:
                raise ConnectorError("timeout", "DB query timed out") from exc
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize any driver error
            raise ConnectorError("connection", str(exc)[:200]) from exc
    return NOT_FOUND  # unreachable


class DbResolver:
    def __init__(
        self,
        *,
        connector_id: str,
        version: int,
        dsn: str,
        query_template: str,
        field_map: dict[str, str],
    ) -> None:
        self._connector_id = connector_id
        self._version = version
        self._dsn = dsn
        self._query_template = query_template
        self._field_map = field_map

    async def fetch(self, tenant_id: str, record_type: str, key: str) -> RawRecord | _NotFound:
        _validate_db_host(self._dsn)
        engine = _get_engine(self._connector_id, self._version, self._dsn)
        return await _run_query(engine, self._query_template, key, self._field_map)
