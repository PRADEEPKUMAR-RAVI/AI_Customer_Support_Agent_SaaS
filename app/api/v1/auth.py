"""Auth endpoints (M1 minimal, real): signup / verify-email / login / refresh / logout.

Access token is returned in the body (SPA holds it in memory); the refresh token is a
``SameSite=Strict`` httpOnly cookie ([IMP-FE-4]). Signup provisions the tenant + first admin
+ agent_settings + widget_key and enqueues a verification email via the outbox.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
from app.infra.db.session import auth_bootstrap_session, set_tenant_guc, with_tenant
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
)

RESET_TOKEN_TTL_SECONDS = 3600
INVITE_TOKEN_TTL_SECONDS = 7 * 24 * 3600

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


_GENERIC_RESET_RESPONSE = {"message": "If that email is registered, a reset link has been sent."}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    # Same response whether or not the email exists — an account-enumeration oracle here would
    # undermine the exact neutral-message discipline the rest of the system relies on
    # (not_found/unverified parity in the record-lookup flow).
    async with auth_bootstrap_session() as session:
        staff = (
            await session.execute(select(Staff).where(Staff.email == body.email))
        ).scalar_one_or_none()
    if staff is not None and staff.is_active:
        async with with_tenant(staff.tenant_id) as session:
            reset_token = create_token(
                {
                    "typ": "reset",
                    "sub": str(staff.id),
                    "tenant_id": str(staff.tenant_id),
                    "email": staff.email,
                    "ver": staff.token_version,
                },
                RESET_TOKEN_TTL_SECONDS,
            )
            await emit(
                session,
                event_type="email.password_reset",
                payload={"to": staff.email, "token": reset_token},
            )
    return _GENERIC_RESET_RESPONSE


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> dict:
    """Also accepts a staff invite (``typ=invite``) — same set-password path either way.

    Single-use + auto-invalidated-on-password-change via a ``token_version`` counter: the token
    embeds the version current at mint time (``ver``) and is honoured only if it still matches
    the staff row's current version. Using it bumps the version, so a replay of the same token —
    or of any older outstanding token — fails the match. (A wall-clock ``iat`` comparison can't
    do this reliably: two events in the same second round to equal, which a naive
    newer-than check can't tell apart from a replay — a version counter has no such race.)
    """
    try:
        claims = decode_token(body.token)
    except Exception as exc:  # noqa: BLE001
        raise AppError(status_code=400, title="Invalid or expired token",
                       code="invalid_token") from exc
    if claims.get("typ") not in ("reset", "invite"):
        raise AppError(status_code=400, title="Wrong token type", code="invalid_token")

    async with with_tenant(claims["tenant_id"]) as session:
        staff = (
            await session.execute(select(Staff).where(Staff.id == claims["sub"]))
        ).scalar_one_or_none()
        if staff is None:
            raise AppError(status_code=400, title="Invalid or expired token",
                           code="invalid_token")
        if claims.get("ver") != staff.token_version:
            raise AppError(status_code=400, title="This link has already been used",
                           code="token_already_used")
        await session.execute(
            update(Staff)
            .where(Staff.id == staff.id)
            .values(
                password_hash=hash_password(body.new_password),
                password_changed_at=datetime.now(timezone.utc),
                token_version=Staff.token_version + 1,
                email_verified=True,
            )
        )
    return {"status": "password_updated"}
