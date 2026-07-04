"""Auth endpoints (M1 minimal, real): signup / verify-email / login / refresh / logout.

Access token is returned in the body (SPA holds it in memory); the refresh token is a
``SameSite=Strict`` httpOnly cookie ([IMP-FE-4]). Signup provisions the tenant + first admin
+ agent_settings + widget_key and enqueues a verification email via the outbox.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.errors import AppError
from app.core.config import get_settings
from app.core.events import emit
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    mint_widget_key,
    verify_password,
)
from app.domain.tenancy.defaults import default_agent_settings
from app.infra.db.engine import SessionLocal
from app.infra.db.models.tenant import AgentSettings, Staff, Tenant, WidgetKey
from app.infra.db.session import auth_bootstrap_session, set_tenant_guc
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "cs_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        samesite="strict",
        secure=settings.is_prod,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
    )


def _issue_tokens(response: Response, *, staff_id: str, tenant_id: str, email: str, role: str) -> TokenResponse:
    settings = get_settings()
    base = {"sub": staff_id, "tenant_id": tenant_id, "email": email, "role": role}
    access = create_token({**base, "typ": "access"}, settings.access_token_ttl_seconds)
    refresh = create_token({**base, "typ": "refresh"}, settings.refresh_token_ttl_seconds)
    _set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=settings.access_token_ttl_seconds)


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest) -> dict:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                tenant = Tenant(name=body.workspace_name, industry=body.industry.value, status="active")
                session.add(tenant)
                await session.flush()  # obtain tenant.id
                await set_tenant_guc(session, tenant.id)  # subsequent inserts auto-scope
                staff = Staff(
                    email=body.email,
                    password_hash=hash_password(body.password),
                    role="admin",
                    email_verified=False,
                )
                session.add(staff)
                session.add(AgentSettings(config=default_agent_settings(body.industry)))
                session.add(WidgetKey(key=mint_widget_key()))
                await session.flush()
                verify_token = create_token(
                    {"typ": "verify", "sub": str(staff.id), "tenant_id": str(tenant.id),
                     "email": body.email},
                    86_400,
                )
                await emit(
                    session,
                    event_type="email.verify",
                    payload={"to": body.email, "token": verify_token},
                    dedupe_key=f"verify:{staff.id}",
                )
            tenant_id = str(tenant.id)
    except IntegrityError as exc:
        raise AppError(status_code=409, title="Email already registered",
                       code="email_taken") from exc
    return {"tenant_id": tenant_id, "message": "Check your email to verify your account."}


@router.post("/verify-email")
async def verify_email(token: str) -> dict:
    try:
        claims = decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise AppError(status_code=400, title="Invalid or expired token",
                       code="invalid_token") from exc
    if claims.get("typ") != "verify":
        raise AppError(status_code=400, title="Wrong token type", code="invalid_token")
    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, claims["tenant_id"])
            await session.execute(
                update(Staff).where(Staff.id == claims["sub"]).values(email_verified=True)
            )
    return {"status": "verified"}


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> TokenResponse:
    async with auth_bootstrap_session() as session:  # pre-tenant identity read (login only)
        staff = (
            await session.execute(select(Staff).where(Staff.email == body.email))
        ).scalar_one_or_none()
        tenant = None
        if staff is not None:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == staff.tenant_id))
            ).scalar_one_or_none()
    if staff is None or not verify_password(body.password, staff.password_hash):
        raise AppError(status_code=401, title="Invalid credentials", code="invalid_credentials")
    if not staff.is_active:
        raise AppError(status_code=403, title="Account disabled", code="account_disabled")
    if not staff.email_verified:
        raise AppError(status_code=403, title="Email not verified", code="email_unverified")
    if tenant is None or tenant.status != "active":
        raise AppError(status_code=403, title="Workspace unavailable", code="tenant_suspended")
    return _issue_tokens(
        response, staff_id=str(staff.id), tenant_id=str(staff.tenant_id),
        email=staff.email, role=staff.role,
    )


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError(status_code=401, title="No refresh token", code="unauthenticated")
    try:
        claims = decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise AppError(status_code=401, title="Invalid refresh token",
                       code="invalid_token") from exc
    if claims.get("typ") != "refresh":
        raise AppError(status_code=401, title="Wrong token type", code="invalid_token")
    return _issue_tokens(
        response, staff_id=claims["sub"], tenant_id=claims["tenant_id"],
        email=claims["email"], role=claims.get("role", ""),
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return {"status": "logged_out"}
