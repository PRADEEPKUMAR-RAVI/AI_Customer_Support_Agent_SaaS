"""M1 staff invite/manage DTOs (Phase-2 full M1). No ``owner`` role — admin + agent only [C5]."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class StaffInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|agent)$")


class StaffUpdateRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|agent)$")
    is_active: bool | None = None


class StaffResponse(BaseModel):
    id: str
    email: EmailStr
    role: str
    is_active: bool
    email_verified: bool
