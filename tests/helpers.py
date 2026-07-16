"""Shared RLS-test helpers: signup -> verify -> login through the real ASGI app. Not collected
as a test module itself (no ``test_`` prefix)."""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_token
from app.infra.db.models.tenant import Staff
from app.infra.db.session import with_tenant
from app.main import app


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def signup(c: AsyncClient, *, industry: str = "retail") -> tuple[str, str, str]:
    # `.test` is a syntactically-reserved TLD (RFC 2606) that pydantic's EmailStr rejects even
    # with deliverability checks off; `example.com` is the reserved domain that passes.
    email = f"user-{uuid.uuid4().hex}@example.com"
    password = "correct-horse-battery"
    res = await c.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": password,
            "company_name": "Acme Test Co",
            "industry": industry,
        },
    )
    assert res.status_code == 201, res.text
    return email, password, res.json()["tenant_id"]


async def verify_email(email: str, tenant_id: str) -> None:
    async with with_tenant(tenant_id) as session:
        staff = (await session.execute(select(Staff).where(Staff.email == email))).scalar_one()
    token = create_token(
        {"typ": "verify", "sub": str(staff.id), "tenant_id": str(tenant_id), "email": email},
        86_400,
    )
    async with client() as c:
        res = await c.post("/api/v1/auth/verify-email", params={"token": token})
        assert res.status_code == 200, res.text


async def login(c: AsyncClient, email: str, password: str) -> str:
    res = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


async def signup_verified_admin(industry: str = "retail") -> tuple[str, str, str, str]:
    """Returns ``(email, password, tenant_id, access_token)`` for a fresh, verified admin."""
    async with client() as c:
        email, password, tenant_id = await signup(c, industry=industry)
    await verify_email(email, tenant_id)
    async with client() as c:
        access_token = await login(c, email, password)
    return email, password, tenant_id, access_token


def auth_headers(token: str) -> dict:
    return {"authorization": f"Bearer {token}"}


async def invite_and_activate_staff(
    *, admin_token: str, tenant_id: str, role: str = "agent"
) -> tuple[str, str, str]:
    """Invites a staff member as the given admin, accepts the invite, and logs in. Returns
    ``(staff_id, email, access_token)``."""
    email = f"staff-{uuid.uuid4().hex}@example.com"
    async with client() as c:
        res = await c.post(
            "/api/v1/admin/staff",
            json={"email": email, "role": role},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 201, res.text
        staff_id = res.json()["id"]

    invite_token = create_token(
        {"typ": "invite", "sub": staff_id, "tenant_id": tenant_id, "email": email, "ver": 0},
        7 * 24 * 3600,
    )
    password = "a-brand-new-password"
    async with client() as c:
        res = await c.post(
            "/api/v1/auth/reset-password", json={"token": invite_token, "new_password": password}
        )
        assert res.status_code == 200, res.text
        access_token = await login(c, email, password)
    return staff_id, email, access_token
