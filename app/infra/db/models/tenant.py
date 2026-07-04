"""Tenancy / IAM tables (M1 surface). ``tenant`` is the root (not tenant-scoped); everything
else is tenant-scoped and RLS-isolated."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TenantMixin, TimestampMixin, uuid_pk


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(32), nullable=False)  # Industry value
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|suspended
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspend_reason: Mapped[str | None] = mapped_column(String(500))


class Staff(Base, TenantMixin, TimestampMixin):
    __tablename__ = "staff"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_staff_tenant_email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="admin")  # admin|agent
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A reset/invite token embeds the `token_version` current at mint time (`ver` claim); it's
    # honoured only if it still matches. Bumped on every password set (reset/invite-accept), so
    # using a token makes it single-use for free, and issuing/using a NEWER token invalidates
    # any older outstanding one — no separate used-tokens table needed. (A wall-clock timestamp
    # comparison doesn't work here: two events in the same second round to equal, which a naive
    # `newer-than` check can't tell apart from a replay.)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WidgetKey(Base, TenantMixin, TimestampMixin):
    __tablename__ = "widget_key"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AllowedDomain(Base, TenantMixin, TimestampMixin):
    __tablename__ = "allowed_domain"

    id: Mapped[uuid.UUID] = uuid_pk()
    domain: Mapped[str] = mapped_column(String(255), nullable=False)


class AgentSettings(Base, TenantMixin, TimestampMixin):
    """One row per tenant. Config held as JSONB (welcome_message, supported_languages,
    default_language, carrier_url_template, sensitive_intent_list, thresholds, timers,
    allowed_tags, autonomy, …) — the seed defaults come from ``TenantDefaults``."""

    __tablename__ = "agent_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_agent_settings_tenant"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
