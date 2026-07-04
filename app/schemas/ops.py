"""M10 platform-operator DTOs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TenantOut(BaseModel):
    id: str
    name: str
    industry: str
    status: str  # active|suspended


class TenantStatusPatchRequest(BaseModel):
    status: str = Field(pattern="^(active|suspended)$")
    reason: str | None = None


class HealthResponse(BaseModel):
    email_dlq_depth: int
    recent_send_failures: int


class UsageResponse(BaseModel):
    """Meant to aggregate person-2's M8 rollups (`turn_metric`), which doesn't exist yet — an
    honest "not available" rather than a fabricated number."""

    status: str  # ok|unavailable
    reason: str | None = None
    tenants: list[dict] = []
