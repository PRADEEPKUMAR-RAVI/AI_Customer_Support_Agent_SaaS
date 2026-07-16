"""M4 Connectors — SSRF guard (critical), field mapping, and encrypted-creds round-trip.

The API-mapping tests use httpx.MockTransport (offline, no real network) with a public test IP so
the SSRF guard genuinely passes; the SSRF-block tests point at localhost and must fail closed.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.infra.connectors.api_resolver import ApiResolver
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.connectors.db_resolver import DbResolver, _run_query

# ---------------------------------------------------------------------------------------------
# SSRF guard (unit, no services) — the security-critical behavior
# ---------------------------------------------------------------------------------------------

async def test_api_resolver_blocks_localhost():
    r = ApiResolver(base_url="http://localhost:8080", path_template="/orders/{key}", field_map={})
    with pytest.raises(ConnectorError) as ei:
        await r.fetch("t", "order", "1001")
    assert ei.value.kind == "connection"


async def test_api_resolver_blocks_cloud_metadata_ip():
    r = ApiResolver(base_url="http://169.254.169.254", path_template="/latest/{key}", field_map={})
    with pytest.raises(ConnectorError):
        await r.fetch("t", "order", "x")


async def test_db_resolver_blocks_localhost_dsn():
    r = DbResolver(
        connector_id="c1", version=1,
        dsn="postgresql+asyncpg://u:p@localhost:5432/x",
        query_template="SELECT email FROM orders WHERE order_id = :key", field_map={},
    )
    with pytest.raises(ConnectorError):
        await r.fetch("t", "order", "1001")


# ---------------------------------------------------------------------------------------------
# ApiResolver field mapping (unit, MockTransport + public IP so SSRF passes)
# ---------------------------------------------------------------------------------------------

def _mock(status: int, json_body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json_body or {})
    return httpx.MockTransport(handler)


async def test_api_resolver_maps_response_fields():
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}",
        field_map={"e": "email", "st": "status", "track": "tracking_ref"},
        transport=_mock(200, {"e": "a@x.test", "st": "shipped", "track": "TRK1", "extra": "ignored"}),
    )
    rec = await r.fetch("t", "order", "1001")
    assert rec == {"email": "a@x.test", "status": "shipped", "tracking_ref": "TRK1"}


async def test_api_resolver_404_is_not_found():
    r = ApiResolver(base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"e": "email"},
                    transport=_mock(404))
    assert await r.fetch("t", "order", "9999") is NOT_FOUND


async def test_api_resolver_401_is_auth_error():
    r = ApiResolver(base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"e": "email"},
                    transport=_mock(401))
    with pytest.raises(ConnectorError) as ei:
        await r.fetch("t", "order", "1001")
    assert ei.value.kind == "auth"


# ---------------------------------------------------------------------------------------------
# DbResolver query + mapping and creds round-trip (rls — live Postgres)
# ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    from app.infra.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.rls
async def test_db_run_query_binds_key_and_maps_columns():
    # Use the non-RLS `tenant` table as a stand-in "external" table to prove parameterized binding
    # + column->field mapping without any DDL.
    from app.infra.db.engine import SessionLocal, engine
    from app.infra.db.models.tenant import Tenant

    name = f"dbconn-{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as session:
        async with session.begin():
            session.add(Tenant(name=name, industry="retail", status="active"))

    rec = await _run_query(
        engine,
        "SELECT name, status FROM tenant WHERE name = :key",
        name,
        {"name": "customer_name", "status": "state"},
    )
    assert rec == {"customer_name": name, "state": "active"}

    missing = await _run_query(engine, "SELECT name FROM tenant WHERE name = :key", "nope-xyz", {"name": "n"})
    assert missing is NOT_FOUND


@pytest.mark.rls
async def test_get_resolver_decrypts_connector_credentials():
    from app.core.security import encrypt_credential
    from app.infra.db.engine import SessionLocal
    from app.infra.db.models.records import Connector
    from app.infra.db.models.tenant import Tenant
    from app.infra.db.session import with_tenant
    from app.services.record_service import get_resolver

    dsn = "postgresql+asyncpg://readonly:secret@db.example.com:5432/shop"
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"conn-{uuid.uuid4().hex[:8]}", industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            tid = tenant.id
    async with with_tenant(tid) as session:
        connector = Connector(record_type="order", source_type="db", version=1,
                              encrypted_credentials="", config={"query_template": "SELECT 1"}, field_map={})
        session.add(connector)
        await session.flush()
        connector.encrypted_credentials = encrypt_credential(
            dsn, tenant_id=str(tid), connector_id=str(connector.id)
        )

    async with with_tenant(tid) as session:
        resolver = await get_resolver(session, str(tid), "order")
        assert isinstance(resolver, DbResolver)
        assert resolver._dsn == dsn  # decrypted back to the original DSN
