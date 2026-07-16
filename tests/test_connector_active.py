"""One-active-connector-per-record_type invariant (multi-connector support).

Proves on a real Postgres that (a) the ``uq_connector_active_per_type`` partial unique index rejects
a second ENABLED connector for the same (tenant, record_type), (b) many connectors may coexist as
long as only one is enabled, (c) ``get_resolver`` falls back to the upload dataset when all are
paused, and (d) the activate path (``_pause_active_siblings`` then enable) switches the live source
without ever tripping the index. Marked ``rls`` — needs a live pgvector Postgres (``make test-rls``).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.records import _pause_active_siblings
from app.infra.db.engine import SessionLocal
from app.infra.db.models.records import Connector
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.services.record_service import UploadResolver, get_resolver

pytestmark = pytest.mark.rls


@pytest.fixture(autouse=True)
async def _dispose_engines_between_tests():
    """Each test gets a fresh event loop; dispose both the request + worker engines around it so
    every asyncpg connection is created and torn down on the current loop (see test_rls_isolation)."""
    from app.infra.db.engine import engine, worker_engine

    await engine.dispose()
    await worker_engine.dispose()
    yield
    await engine.dispose()
    await worker_engine.dispose()


async def _make_tenant(name: str) -> uuid.UUID:
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=name, industry="retail", status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


def _connector(record_type: str, source_type: str, *, enabled: bool) -> Connector:
    # tenant_id auto-fills from the GUC; config/field_map/version take model defaults.
    return Connector(
        record_type=record_type, source_type=source_type, encrypted_credentials="", enabled=enabled
    )


async def test_second_active_connector_for_a_type_is_rejected():
    tenant = await _make_tenant("Active-A")
    async with with_tenant(tenant) as session:
        session.add(_connector("order", "db", enabled=True))

    # A SECOND enabled connector for the same record_type violates uq_connector_active_per_type.
    with pytest.raises(IntegrityError):
        async with with_tenant(tenant) as session:
            session.add(_connector("order", "api", enabled=True))


async def test_multiple_connectors_allowed_when_only_one_is_active():
    tenant = await _make_tenant("Active-B")
    async with with_tenant(tenant) as session:
        session.add(_connector("order", "db", enabled=True))
        session.add(_connector("order", "api", enabled=False))  # paused sibling — allowed

    async with with_tenant(tenant) as session:
        rows = (
            await session.execute(select(Connector).where(Connector.record_type == "order"))
        ).scalars().all()
        assert len(rows) == 2
        assert sum(1 for c in rows if c.enabled) == 1


async def test_get_resolver_falls_back_to_upload_when_all_paused():
    tenant = await _make_tenant("Active-C")
    async with with_tenant(tenant) as session:
        session.add(_connector("order", "db", enabled=False))

    async with with_tenant(tenant) as session:
        resolver = await get_resolver(session, str(tenant), "order")
        assert isinstance(resolver, UploadResolver)


async def test_activate_pauses_the_previous_source():
    tenant = await _make_tenant("Active-D")
    async with with_tenant(tenant) as session:
        a, b = _connector("order", "db", enabled=True), _connector("order", "api", enabled=False)
        session.add_all([a, b])
        await session.flush()
        a_id, b_id = a.id, b.id

    # Activate B the way the PATCH endpoint does: pause siblings FIRST, then enable — no violation.
    async with with_tenant(tenant) as session:
        await _pause_active_siblings(session, record_type="order", keep_id=b_id)
        (await session.get(Connector, b_id)).enabled = True

    async with with_tenant(tenant) as session:
        assert (await session.get(Connector, a_id)).enabled is False
        assert (await session.get(Connector, b_id)).enabled is True
