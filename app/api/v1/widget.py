"""Anonymous widget bootstrap: ``POST /widget/session``.

Mints a server-side opaque session id ([IMP-SEC-3]), scopes conversation continuity to it,
and returns the public widget config. The widget_key is a PUBLIC identifier, so the anonymous
endpoint is the abuse-control point: rate-limited per (tenant, widget_key, client IP)
independent of CORS. Suspended tenants are rejected here at mint time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.errors import AppError
from app.core import ratelimit
from app.core.security import create_token, mint_session_id
from app.infra.db.engine import SessionLocal
from app.infra.db.models.conversation import Conversation
from app.infra.db.models.tenant import AgentSettings, AllowedDomain, Tenant, WidgetKey
from app.infra.db.session import set_tenant_guc

router = APIRouter(prefix="/widget", tags=["widget"])

_RATE_LIMIT = 30          # sessions per window
_RATE_WINDOW_SECONDS = 60


class SessionRequest(BaseModel):
    widget_key: str


class SessionResponse(BaseModel):
    session_id: str
    conversation_id: str
    # Signed bearer the widget sends on subsequent /conversations calls; binds tenant+session+
    # conversation so an anonymous caller can only touch its own conversation ([IMP-SEC-3]).
    session_token: str
    config: dict


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/session", response_model=SessionResponse)
async def create_session(body: SessionRequest, request: Request) -> SessionResponse:
    origin = request.headers.get("origin", "")
    ip = _client_ip(request)

    async with SessionLocal() as session:
        async with session.begin():
            # widget_key has a permissive SELECT policy (it is public) — readable pre-context.
            wk = (
                await session.execute(
                    select(WidgetKey).where(WidgetKey.key == body.widget_key, WidgetKey.active.is_(True))
                )
            ).scalar_one_or_none()
            if wk is None:
                raise AppError(status_code=404, title="Unknown widget key", code="unknown_widget_key")

            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == wk.tenant_id))
            ).scalar_one_or_none()
            if tenant is None or tenant.status != "active":
                raise AppError(status_code=403, title="Workspace unavailable", code="tenant_suspended")

            # From here on, scope to the tenant.
            await set_tenant_guc(session, wk.tenant_id)

            # Abuse control (independent of CORS/Origin).
            allowed = await ratelimit.hit(
                f"widgetsess:{wk.tenant_id}:{wk.key}:{ip}",
                limit=_RATE_LIMIT,
                window_seconds=_RATE_WINDOW_SECONDS,
            )
            if not allowed:
                raise AppError(status_code=429, title="Too many requests", code="rate_limited")

            # Origin allowlist (best-effort browser control; not the security boundary).
            if origin:
                domains = (
                    await session.execute(select(AllowedDomain.domain))
                ).scalars().all()
                if domains and not any(origin.rstrip("/").endswith(d) for d in domains):
                    raise AppError(status_code=403, title="Origin not allowed", code="origin_forbidden")

            settings_row = (
                await session.execute(select(AgentSettings))
            ).scalar_one_or_none()
            cfg = settings_row.config if settings_row else {}

            session_id = mint_session_id()
            ttl = int(cfg.get("session_id_ttl_seconds", 30 * 24 * 3600))
            conversation = Conversation(
                session_id=session_id,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
            )
            session.add(conversation)
            await session.flush()  # obtain conversation.id
            session_token = create_token(
                {
                    "typ": "widget",
                    "tenant_id": str(wk.tenant_id),
                    "session_id": session_id,
                    "conversation_id": str(conversation.id),
                },
                ttl,
            )
            conversation_id = str(conversation.id)

    public_config = {
        "welcome_message": cfg.get("welcome_message", "Hi! How can I help you today?"),
        "supported_languages": cfg.get("supported_languages", ["en"]),
        "default_language": cfg.get("default_language", "en"),
    }
    return SessionResponse(
        session_id=session_id,
        conversation_id=conversation_id,
        session_token=session_token,
        config=public_config,
    )
