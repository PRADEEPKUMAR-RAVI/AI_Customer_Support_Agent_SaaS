"""M10 — Platform Operator endpoints: platform-scope auth, audited bypass, and
suspension-rejected-at-session-mint. Needs a live Postgres + Redis."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import create_token
from app.infra.db.engine import SessionLocal
from app.infra.db.models.outbox import Outbox, PlatformAuditLog
from tests.helpers import auth_headers, client, signup_verified_admin

pytestmark = pytest.mark.rls


def _platform_headers() -> dict:
    token = create_token({"scope": "platform", "sub": str(uuid.uuid4())}, 3600)
    return auth_headers(token)


async def test_ops_rejects_a_tenant_scoped_staff_token():
    _, _, _, admin_token = await signup_verified_admin()
    async with client() as c:
        res = await c.get("/api/v1/ops/tenants", headers=auth_headers(admin_token))
        assert res.status_code == 403, res.text


async def test_ops_rejects_missing_auth():
    async with client() as c:
        res = await c.get("/api/v1/ops/tenants")
        assert res.status_code == 401


async def test_list_and_suspend_tenant_writes_audited_log():
    email, password, tenant_id, _ = await signup_verified_admin()
    platform_headers = _platform_headers()

    async with client() as c:
        res = await c.get("/api/v1/ops/tenants", headers=platform_headers)
        assert res.status_code == 200, res.text
        assert any(t["id"] == tenant_id for t in res.json())

        res = await c.patch(
            f"/api/v1/ops/tenants/{tenant_id}",
            json={"status": "suspended", "reason": "non-payment"},
            headers=platform_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "suspended"

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(PlatformAuditLog).where(PlatformAuditLog.target_tenant_id == uuid.UUID(tenant_id))
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "ops.set_tenant_status:suspended"

    # [suspension rejected at session mint] a suspended tenant's staff can no longer log in.
    async with client() as c:
        res = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 403, res.text
        assert res.json()["code"] == "tenant_suspended"


async def test_reactivating_a_tenant_allows_login_again():
    email, password, tenant_id, _ = await signup_verified_admin()
    platform_headers = _platform_headers()

    async with client() as c:
        await c.patch(
            f"/api/v1/ops/tenants/{tenant_id}",
            json={"status": "suspended"},
            headers=platform_headers,
        )
        res = await c.patch(
            f"/api/v1/ops/tenants/{tenant_id}", json={"status": "active"}, headers=platform_headers
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

        res = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text


async def test_ops_health_counts_dead_and_failed_outbox_rows():
    _, _, tenant_id, _ = await signup_verified_admin()
    from app.infra.db.session import with_tenant

    async with with_tenant(tenant_id) as session:
        session.add(Outbox(event_type="email.test", payload={}, status="dead"))
        session.add(Outbox(event_type="email.test", payload={}, status="failed"))
        session.add(Outbox(event_type="email.test", payload={}, status="pending"))

    async with client() as c:
        res = await c.get("/api/v1/ops/health", headers=_platform_headers())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["email_dlq_depth"] >= 1
        assert body["recent_send_failures"] >= 1


async def test_ops_usage_is_an_honest_stub():
    async with client() as c:
        res = await c.get("/api/v1/ops/usage", headers=_platform_headers())
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "unavailable"
