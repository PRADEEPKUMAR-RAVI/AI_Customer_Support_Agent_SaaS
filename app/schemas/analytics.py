"""M8 analytics response DTOs (tenant-scoped, date-filterable dashboards)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyticsOverview(BaseModel):
    volume: int  # distinct conversations in the window
    turns: int
    autonomous_resolution_rate: float  # conversations with no escalated turn / total
    escalation_reasons: dict[str, int] = Field(default_factory=dict)
    language_distribution: dict[str, int] = Field(default_factory=dict)


class LatencyStats(BaseModel):
    count: int
    p50_ms: float | None = None
    p95_ms: float | None = None


class CostStats(BaseModel):
    total_cost_usd: float
    cost_per_conversation: float
    total_prompt_tokens: int
    total_completion_tokens: int
    by_model: dict[str, float] = Field(default_factory=dict)


class TagStats(BaseModel):
    """Deferred: real tag counts need M5's ``ticket_tag`` (P3). Empty until that lands."""

    tags: dict[str, int] = Field(default_factory=dict)
    note: str | None = None
