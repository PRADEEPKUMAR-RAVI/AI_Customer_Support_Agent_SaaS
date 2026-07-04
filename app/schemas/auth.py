"""Auth DTOs (M1 surface — signup/verify/login/refresh)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.domain.records.schemas import Industry


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    workspace_name: str = Field(min_length=1, max_length=200)
    industry: Industry


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Also used to accept a staff invite — an invite token has ``typ=invite`` but otherwise
    goes through the exact same set-password + single-use validation path."""

    token: str
    new_password: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    """The access token is returned in the body (held in memory by the SPA); the refresh
    token is set as a ``SameSite=Strict`` httpOnly cookie, never in the body."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class StaffContext(BaseModel):
    staff_id: str
    tenant_id: str
    email: EmailStr
    role: str
    permissions: list[str] = []


class PlatformContext(BaseModel):
    """M10 operator identity — a separate principal from any tenant's staff, never derived
    from a tenant-scoped JWT [IMP-SEC-9]."""

    actor_id: str
