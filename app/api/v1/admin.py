"""M1 admin endpoints (Phase-2 full scope): agent_settings read/patch (hot-cache invalidation),
staff invite/manage, and widget-key rotate + embed snippet. Gated by role permissions from the
RBAC catalog ([C5]) — admin-only throughout, since staff/settings/widget-key management is an
admin action per PRD §5.1.1/§7.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_staff, get_db, require_permission
from app.api.errors import AppError
from app.core.config import get_settings
from app.core.events import emit
from app.core.security import create_token, hash_password, mint_widget_key
from app.domain.records.schemas import Industry, max_verify_attempts
from app.infra.cache.redis import get_redis
from app.infra.db.models.tenant import AgentSettings, AllowedDomain, Staff, Tenant, WidgetKey
from app.schemas.admin import (
    AgentSettingsPatchRequest,
    AgentSettingsResponse,
    AllowedDomainRequest,
    AllowedDomainResponse,
    EmbedSnippetResponse,
    TenantResponse,
    WidgetKeyResponse,
)
from app.schemas.auth import StaffContext
from app.schemas.staff import StaffInviteRequest, StaffResponse, StaffUpdateRequest

router = APIRouter(prefix="/admin", tags=["admin"])

_STAFF_INVITE_TTL_SECONDS = 7 * 24 * 3600


def _to_staff_response(row: Staff) -> StaffResponse:
    return StaffResponse(
        id=str(row.id), email=row.email, role=row.role,
        is_active=row.is_active, email_verified=row.email_verified,
    )


# --- tenant (read-only; any authenticated staff, not admin-gated) --------------------------


@router.get("/tenant", response_model=TenantResponse)
async def get_tenant(
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> TenantResponse:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(staff.tenant_id)))
    ).scalar_one()
    return TenantResponse(name=tenant.name, industry=tenant.industry, status=tenant.status)


# --- agent_settings --------------------------------------------------------------------------


@router.get("/settings", response_model=AgentSettingsResponse)
async def get_settings_(
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("settings:manage")),
) -> AgentSettingsResponse:
    row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    if row is None:
        # Every tenant gets an agent_settings row at signup; a miss means data corruption,
        # not a client error — still surfaced as a clean RFC7807 problem, never a 500 leak.
        raise AppError(status_code=404, title="Settings not found", code="settings_not_found")
    return AgentSettingsResponse(config=row.config)


@router.patch("/settings", response_model=AgentSettingsResponse)
async def patch_settings(
    body: AgentSettingsPatchRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("settings:manage")),
) -> AgentSettingsResponse:
    row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    if row is None:
        raise AppError(status_code=404, title="Settings not found", code="settings_not_found")
    # Clamp safety-critical knobs so an admin can't PATCH past a non-negotiable (untyped-dict
    # hardening): verify_max_attempts must never exceed the industry cap — healthcare = 1 per
    # §4.8.2 — and relevance_threshold stays in [0, 1]. Other keys shallow-merge as before.
    incoming = dict(body.config)
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(staff.tenant_id)))
    ).scalar_one()
    cap = max_verify_attempts(Industry(tenant.industry))
    if "verify_max_attempts" in incoming:
        try:
            incoming["verify_max_attempts"] = max(1, min(int(incoming["verify_max_attempts"]), cap))
        except (TypeError, ValueError):
            incoming.pop("verify_max_attempts")
    if incoming.get("relevance_threshold") is not None:
        try:
            incoming["relevance_threshold"] = min(1.0, max(0.0, float(incoming["relevance_threshold"])))
        except (TypeError, ValueError):
            incoming.pop("relevance_threshold")
    row.config = {**row.config, **incoming}
    await session.flush()
    # Drop the hot-cache key in the same handler as the write so a read right after this PATCH
    # never serves the pre-update config. No reader/writer of `settings:{tenant_id}` exists yet
    # (M2's runtime engine will be the consumer) — this only pins the key naming contract early.
    # `get_db` commits when the dependency tears down (after this returns), so there's a narrow
    # window where a concurrent read could refetch and re-cache the pre-commit value; the
    # documented short TTL on that future cache entry is the accepted backstop for this race.
    await get_redis().delete(f"settings:{staff.tenant_id}")
    return AgentSettingsResponse(config=row.config)


# --- staff invite / manage ---------------------------------------------------------------------


@router.post("/staff", status_code=201, response_model=StaffResponse)
async def invite_staff(
    body: StaffInviteRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("staff:manage")),
) -> StaffResponse:
    # The password hash is an unusable random placeholder — nobody can log in until the invite
    # link (a `reset-password`-shaped token) sets a real password; `email_verified=False` blocks
    # login independently in the meantime, so this is belt-and-suspenders.
    new_staff = Staff(
        email=body.email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=body.role,
        email_verified=False,
    )
    session.add(new_staff)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise AppError(status_code=409, title="Email already registered",
                       code="email_taken") from exc

    invite_token = create_token(
        {
            "typ": "invite",
            "sub": str(new_staff.id),
            "tenant_id": staff.tenant_id,
            "email": body.email,
            "ver": new_staff.token_version,
        },
        _STAFF_INVITE_TTL_SECONDS,
    )
    await emit(
        session,
        event_type="email.staff_invite",
        payload={"to": body.email, "token": invite_token, "role": body.role},
        dedupe_key=f"staff_invite:{new_staff.id}",  # exactly-once under the at-least-once outbox
    )
    return _to_staff_response(new_staff)


@router.get("/staff", response_model=list[StaffResponse])
async def list_staff(
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("staff:manage")),
) -> list[StaffResponse]:
    rows = (await session.execute(select(Staff).order_by(Staff.created_at))).scalars().all()
    return [_to_staff_response(r) for r in rows]


@router.patch("/staff/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: uuid.UUID,
    body: StaffUpdateRequest,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("staff:manage")),
) -> StaffResponse:
    row = (await session.execute(select(Staff).where(Staff.id == staff_id))).scalar_one_or_none()
    if row is None:
        raise AppError(status_code=404, title="Staff not found", code="staff_not_found")
    if body.is_active is False and str(row.id) == staff.staff_id:
        # A cheap, worthwhile guard: nothing else in the POC stops the last admin from locking
        # themselves out, and there's no support channel to undo it.
        raise AppError(status_code=400, title="Cannot deactivate your own account",
                       code="self_deactivate_forbidden")
    if body.role is not None:
        row.role = body.role
    if body.is_active is not None:
        row.is_active = body.is_active
    await session.flush()
    return _to_staff_response(row)


# --- widget key + embed snippet ----------------------------------------------------------------


@router.post("/widget-key/rotate", response_model=WidgetKeyResponse)
async def rotate_widget_key(
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("settings:manage")),
) -> WidgetKeyResponse:
    # Atomic: deactivate every existing key and mint the replacement in the same transaction, so
    # there's never a window with two simultaneously-active keys. [IMP-SEC-3] There's no
    # widget_key -> tenant cache yet (the anonymous /widget/session lookup queries Postgres
    # directly); if one is added later it MUST be invalidated here too.
    #
    # Explicit tenant_id filter, not just RLS: `widget_key` carries a PERMISSIVE public-read
    # policy for the anonymous bootstrap lookup (`widget_key_public_read: FOR SELECT USING
    # (true)`), and Postgres OR-combines multiple permissive policies for the same command — so
    # any bare SELECT against this table returns every tenant's rows, RLS or not. The write
    # policy is command-scoped and safe on its own, but filtering explicitly here keeps this
    # endpoint correct even if the policy set changes later.
    await session.execute(
        update(WidgetKey)
        .where(WidgetKey.tenant_id == uuid.UUID(staff.tenant_id))
        .values(active=False)
    )
    new_key = WidgetKey(key=mint_widget_key())
    session.add(new_key)
    await session.flush()
    return WidgetKeyResponse(widget_key=new_key.key)


@router.get("/embed-snippet", response_model=EmbedSnippetResponse)
async def get_embed_snippet(
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(require_permission("embed:read")),
) -> EmbedSnippetResponse:
    # MUST filter by tenant_id explicitly — see the comment in `rotate_widget_key` above.
    # RLS alone does NOT scope reads on this table.
    row = (
        await session.execute(
            select(WidgetKey).where(
                WidgetKey.tenant_id == uuid.UUID(staff.tenant_id), WidgetKey.active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(status_code=404, title="No active widget key", code="widget_key_missing")
    # Placeholder loader URL until FE-Widget (person-1) ships the real `widget.js` bundle/CDN
    # path — the shape (async, <2KB loader, data-widget-key attr) matches [IMP-FE-7] regardless.
    snippet = (
        f'<script async src="{get_settings().frontend_origin}/widget.js" '
        f'data-widget-key="{row.key}"></script>'
    )
    return EmbedSnippetResponse(widget_key=row.key, snippet=snippet)


# --- allowed domains (widget Origin allowlist, §5.1) -------------------------------------------
# Without these endpoints the allowed_domain table stays empty and widget.py's
# `if domains and not any(...)` short-circuits → every Origin is accepted. This is what makes the
# tenant-configurable allowlist actually functional. (widget_key remains the real identifier; the
# Origin check is best-effort browser control, not the security boundary.)


@router.get("/allowed-domains", response_model=list[AllowedDomainResponse])
async def list_allowed_domains(
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("settings:manage")),
) -> list[AllowedDomainResponse]:
    rows = (await session.execute(select(AllowedDomain).order_by(AllowedDomain.created_at))).scalars().all()
    return [AllowedDomainResponse(id=str(r.id), domain=r.domain) for r in rows]


@router.post("/allowed-domains", status_code=201, response_model=AllowedDomainResponse)
async def add_allowed_domain(
    body: AllowedDomainRequest,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("settings:manage")),
) -> AllowedDomainResponse:
    domain = body.domain.strip().lower().rstrip("/")
    existing = (
        await session.execute(select(AllowedDomain).where(AllowedDomain.domain == domain))
    ).scalar_one_or_none()
    if existing is not None:
        return AllowedDomainResponse(id=str(existing.id), domain=existing.domain)
    row = AllowedDomain(domain=domain)
    session.add(row)
    await session.flush()
    return AllowedDomainResponse(id=str(row.id), domain=row.domain)


@router.delete("/allowed-domains/{domain_id}", status_code=204)
async def remove_allowed_domain(
    domain_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _staff: StaffContext = Depends(require_permission("settings:manage")),
) -> None:
    row = (
        await session.execute(select(AllowedDomain).where(AllowedDomain.id == domain_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppError(status_code=404, title="Domain not found", code="domain_not_found")
    await session.delete(row)
