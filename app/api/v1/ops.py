"""M10 — Platform Operator (minimal, audited).

Every cross-tenant read/write goes through Person-1's `platform_bypass(...)` primitive, which
uses the dedicated BYPASSRLS role on its own connection and writes an append-only
`platform_audit_log` row in the same transaction ([IMP-SEC-9]). The operator is a SEPARATE
principal (`scope=platform`) — a tenant JWT is never accepted here. Suspension is enforced at
session mint + on every message (see widget.py / conversation_service).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import func, select, text, update

from app.api.errors import AppError
from app.core.config import get_settings
from app.core.security import create_token, decode_token
from app.infra.cache.redis import get_redis
from app.infra.db.engine import engine
from app.infra.db.models.metrics import TurnMetric
from app.infra.db.models.outbox import Outbox
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import platform_bypass

router = APIRouter(prefix="/ops", tags=["ops"])

_PLATFORM_NS = uuid.uuid5(uuid.NAMESPACE_URL, "cs-agent:platform-operator")


class PlatformCtx(BaseModel):
    admin_id: uuid.UUID
    email: str


async def get_platform_ctx(authorization: str | None = Header(default=None)) -> PlatformCtx:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(status_code=401, title="Missing operator token", code="unauthenticated")
    try:
        claims = decode_token(authorization.split(" ", 1)[1])
    except Exception as exc:  # noqa: BLE001
        raise AppError(status_code=401, title="Invalid operator token", code="invalid_token") from exc
    # A tenant JWT (typ=access) must NEVER be accepted here.
    if claims.get("typ") != "platform" or claims.get("scope") != "platform":
        raise AppError(status_code=403, title="Not a platform operator", code="forbidden")
    return PlatformCtx(admin_id=uuid.UUID(claims["sub"]), email=claims["email"])


class OpsLogin(BaseModel):
    # A fixed operator credential compared via secrets.compare_digest — NOT a deliverable
    # mailbox, so it must not be coupled to email-validator's TLD policy (the shipped default
    # `ops@platform.local` uses the reserved `.local` TLD that EmailStr rejects).
    email: str
    password: str


@router.post("/login")
async def ops_login(body: OpsLogin) -> dict:
    s = get_settings()
    ok = secrets.compare_digest(body.email, s.platform_admin_email) and secrets.compare_digest(
        body.password, s.platform_admin_password
    )
    if not ok:
        raise AppError(status_code=401, title="Invalid operator credentials", code="invalid_credentials")
    admin_id = str(uuid.uuid5(_PLATFORM_NS, body.email))
    token = create_token(
        {"typ": "platform", "scope": "platform", "sub": admin_id, "email": body.email},
        s.access_token_ttl_seconds,
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": s.access_token_ttl_seconds}


@router.get("/tenants")
async def list_tenants(ctx: PlatformCtx = Depends(get_platform_ctx)) -> dict:
    async with platform_bypass(actor_admin_id=ctx.admin_id, action="ops.list_tenants") as session:
        rows = (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
        return {"tenants": [
            {"id": str(t.id), "name": t.name, "industry": t.industry, "status": t.status,
             "suspended_at": t.suspended_at.isoformat() if t.suspended_at else None}
            for t in rows
        ]}


class TenantPatch(BaseModel):
    status: Literal["active", "suspended"]
    reason: str | None = None


@router.patch("/tenants/{tenant_id}")
async def patch_tenant(tenant_id: str, body: TenantPatch, ctx: PlatformCtx = Depends(get_platform_ctx)) -> dict:
    now = datetime.now(timezone.utc)
    values: dict = {"status": body.status}
    values["suspended_at"] = now if body.status == "suspended" else None
    values["suspend_reason"] = body.reason if body.status == "suspended" else None
    async with platform_bypass(
        actor_admin_id=ctx.admin_id, action=f"ops.set_status:{body.status}", target_tenant_id=uuid.UUID(tenant_id)
    ) as session:
        res = await session.execute(update(Tenant).where(Tenant.id == tenant_id).values(**values))
        if res.rowcount == 0:
            raise AppError(status_code=404, title="Tenant not found", code="not_found")
    return {"tenant_id": tenant_id, "status": body.status}


@router.get("/health")
async def ops_health(ctx: PlatformCtx = Depends(get_platform_ctx)) -> dict:
    components: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["postgres"] = f"down: {type(exc).__name__}"
    try:
        await get_redis().ping()
        components["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["redis"] = f"down: {type(exc).__name__}"

    # Email health across all tenants ([IMP-WRK-5]) — a stalled relay must be visible, not silent.
    async with platform_bypass(actor_admin_id=ctx.admin_id, action="ops.health") as session:
        dlq_depth = await session.scalar(select(func.count()).select_from(Outbox).where(Outbox.status == "dead"))
        retrying = await session.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.status == "pending", Outbox.attempts > 0)
        )
    return {"components": components, "email_dlq_depth": dlq_depth or 0, "email_retrying": retrying or 0}


@router.get("/usage")
async def ops_usage(ctx: PlatformCtx = Depends(get_platform_ctx)) -> dict:
    # Aggregates raw turn_metric for the POC ([T5] — M8's rollup tables are deferred).
    async with platform_bypass(actor_admin_id=ctx.admin_id, action="ops.usage") as session:
        total_turns = await session.scalar(select(func.count()).select_from(TurnMetric)) or 0
        escalations = await session.scalar(
            select(func.count()).select_from(TurnMetric).where(TurnMetric.escalated.is_(True))
        ) or 0
        rows = (await session.execute(select(TurnMetric.tenant_id, TurnMetric.cost))).all()
    total_cost = 0.0
    per_tenant: dict[str, int] = {}
    for tenant_id, cost in rows:
        per_tenant[str(tenant_id)] = per_tenant.get(str(tenant_id), 0) + 1
        for c in cost or []:
            total_cost += (c.get("cost_usd") or 0.0)
    return {
        "total_turns": total_turns,
        "escalations": escalations,
        "total_cost_usd": round(total_cost, 6),
        "turns_by_tenant": per_tenant,
    }
