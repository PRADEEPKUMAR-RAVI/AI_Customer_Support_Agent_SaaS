"""Shared DTOs: the RFC7807 problem envelope + generic pagination."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Problem(BaseModel):
    """RFC 7807 problem details — the single error envelope for every endpoint."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    # Machine-readable code for the FE to branch on (e.g. "tenant_suspended", "unverified").
    code: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
