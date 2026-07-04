"""Dependency injection: staff auth (JWT), the tenant-scoped DB session, and RBAC gating.

``get_db`` is the request-scoped RLS harness: it resolves the tenant from the staff JWT, opens
ONE transaction, sets ``app.tenant_id`` via ``SET LOCAL`` (set_config(..., true)), and yields
the session. Every staff/admin/agent endpoint depends on it, so RLS isolation is automatic.
Anonymous widget endpoints use their own bootstrap resolver (see ``api/v1/widget.py``).
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.permissions import permissions_for
from app.core.security import decode_token
from app.infra.db.engine import SessionLocal
from app.infra.db.session import set_tenant_guc
from app.schemas.auth import StaffContext


async def get_current_staff(authorization: str | None = Header(default=None)) -> StaffContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(status_code=401, title="Not authenticated", code="unauthenticated")
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_token(token)
    except Exception as exc:  # jwt.PyJWTError etc.
        raise AppError(
            status_code=401, title="Invalid or expired token", code="invalid_token"
        ) from exc
    if claims.get("typ") != "access":
        raise AppError(status_code=401, title="Wrong token type", code="invalid_token")
    role = claims.get("role", "")
    return StaffContext(
        staff_id=claims["sub"],
        tenant_id=claims["tenant_id"],
        email=claims["email"],
        role=role,
        permissions=permissions_for(role),
    )


async def get_db(
    staff: StaffContext = Depends(get_current_staff),
) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, staff.tenant_id)
            yield session


def require_permission(permission: str):
    """FastAPI dependency factory: 403 unless the caller's role grants ``permission``."""

    async def _dep(staff: StaffContext = Depends(get_current_staff)) -> StaffContext:
        if permission not in staff.permissions:
            raise AppError(
                status_code=403,
                title="Forbidden",
                code="forbidden",
                detail=f"missing permission: {permission}",
            )
        return staff

    return _dep
