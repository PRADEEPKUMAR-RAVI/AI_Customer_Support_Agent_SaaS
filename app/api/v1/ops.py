"""M10 — Platform Operator: the cross-tenant admin surface. Every read/mutation goes through
Person-1's audited ``platform_bypass`` primitive on its own least-privilege connection — never
a raw superuser query [IMP-SEC-9]. Kept intentionally tiny: this is the single most
security-critical module by blast radius, since it *intentionally* breaches tenant isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import require_platform_permission
from app.api.errors import AppError
from app.infra.db.models.metrics import TurnMetric
from app.infra.db.models.outbox import Outbox
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import platform_bypass
from app.schemas.auth import PlatformContext
from app.schemas.ops import HealthResponse, TenantOut, TenantStatusPatchRequest, UsageResponse

router = APIRouter(prefix="/ops", tags=["ops"])


def _to_tenant_out(t: Tenant) -> TenantOut:
    return TenantOut(id=str(t.id), name=t.name, industry=t.industry, status=t.status)


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(
    principal: PlatformContext = Depends(require_platform_permission("ops:read")),
) -> list[TenantOut]:
    async with platform_bypass(
        actor_admin_id=uuid.UUID(principal.actor_id), action="ops.list_tenants"
    ) as session:
        rows = (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
        return [_to_tenant_out(t) for t in rows]


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def set_tenant_status(
    tenant_id: uuid.UUID,
    body: TenantStatusPatchRequest,
    principal: PlatformContext = Depends(require_platform_permission("ops:manage")),
) -> TenantOut:
    # Suspension is rejected at session mint: `auth.login` and `widget.create_session` both
    # already 403 when `tenant.status != "active"` — flipping this field here is the entire
    # enforcement point, no separate "kill switch" needed.
    async with platform_bypass(
        actor_admin_id=uuid.UUID(principal.actor_id),
        action=f"ops.set_tenant_status:{body.status}",
        target_tenant_id=tenant_id,
    ) as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise AppError(status_code=404, title="Tenant not found", code="tenant_not_found")
        tenant.status = body.status
        if body.status == "suspended":
            tenant.suspended_at = datetime.now(timezone.utc)
            tenant.suspend_reason = body.reason
        else:
            tenant.suspended_at = None
            tenant.suspend_reason = None
        await session.flush()
        return _to_tenant_out(tenant)


@router.get("/health", response_model=HealthResponse)
async def ops_health(
    principal: PlatformContext = Depends(require_platform_permission("ops:read")),
) -> HealthResponse:
    """[IMP-WRK-5] Surfaces the email DLQ depth + recent send-failure count so a stalled SMTP
    relay is visible, not silent."""
    async with platform_bypass(
        actor_admin_id=uuid.UUID(principal.actor_id), action="ops.health"
    ) as session:
        dead = (
            await session.execute(select(func.count()).select_from(Outbox).where(Outbox.status == "dead"))
        ).scalar_one()
        # The M9 relay (P1) never sets a "failed" status — a transient send failure is bounced back
        # to "pending" with attempts incremented + a backoff. So "failed at least once, still
        # retrying" == pending rows with attempts > 0; that's the real recent-send-failure signal.
        retrying = (
            await session.execute(
                select(func.count()).select_from(Outbox).where(
                    Outbox.status == "pending", Outbox.attempts > 0
                )
            )
        ).scalar_one()
        return HealthResponse(email_dlq_depth=dead, recent_send_failures=retrying)


@router.get("/usage", response_model=UsageResponse)
async def ops_usage(
    principal: PlatformContext = Depends(require_platform_permission("ops:read")),
) -> UsageResponse:
    """Platform-wide usage across ALL tenants, aggregated from M8's ``turn_metric`` — read through
    the audited BYPASSRLS ops connection so it legitimately spans tenants (the operator's job). One
    row per tenant: conversation volume, turns, escalations, autonomous-resolution rate, and token
    cost. Tenants with no activity appear with zeros so the operator sees the full roster."""
    async with platform_bypass(
        actor_admin_id=uuid.UUID(principal.actor_id), action="ops.usage"
    ) as session:
        tenants = (await session.execute(select(Tenant).order_by(Tenant.created_at))).scalars().all()
        # BYPASSRLS → these turn_metric rows span every tenant. Aggregate per tenant_id in Python
        # (POC volume); `cost` is a per-model JSONB list, so sum its cost_usd entries.
        rows = (
            await session.execute(
                select(TurnMetric.tenant_id, TurnMetric.conversation_id,
                       TurnMetric.escalated, TurnMetric.cost)
            )
        ).all()
        agg: dict = {}
        for tid, conv_id, escalated, cost in rows:
            a = agg.setdefault(tid, {"convs": set(), "turns": 0, "esc": set(), "cost": 0.0})
            a["convs"].add(conv_id)
            a["turns"] += 1
            if escalated:
                a["esc"].add(conv_id)
            for c in cost or []:
                a["cost"] += float(c.get("cost_usd") or 0.0)
        out: list[dict] = []
        for t in tenants:
            a = agg.get(t.id, {"convs": set(), "turns": 0, "esc": set(), "cost": 0.0})
            convs, esc = len(a["convs"]), len(a["esc"])
            out.append({
                "tenant": t.name,
                "industry": t.industry,
                "status": t.status,
                "conversations": convs,
                "turns": a["turns"],
                "escalations": esc,
                "autonomous_resolution_rate": round((convs - esc) / convs, 3) if convs else 0.0,
                "cost_usd": round(a["cost"], 4),
            })
        return UsageResponse(status="ok", tenants=out)
