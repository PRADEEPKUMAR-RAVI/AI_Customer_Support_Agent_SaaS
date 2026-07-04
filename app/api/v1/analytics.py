"""M8 Analytics API — tenant-scoped, date-filterable dashboards over ``turn_metric`` (admin-only).

Live queries ([T5]); no rollup table for the POC. ``from_date``/``to_date`` are optional ISO
datetimes narrowing the window.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.schemas.analytics import AnalyticsOverview, CostStats, LatencyStats, TagStats
from app.services import analytics_service

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_permission("analytics:read"))],
)


@router.get("/overview", response_model=AnalyticsOverview)
async def overview(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    session: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    return await analytics_service.overview(session, since=from_date, until=to_date)


@router.get("/latency", response_model=LatencyStats)
async def latency(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    session: AsyncSession = Depends(get_db),
) -> LatencyStats:
    return await analytics_service.latency(session, since=from_date, until=to_date)


@router.get("/cost", response_model=CostStats)
async def cost(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    session: AsyncSession = Depends(get_db),
) -> CostStats:
    return await analytics_service.cost(session, since=from_date, until=to_date)


@router.get("/tags", response_model=TagStats)
async def tags(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    session: AsyncSession = Depends(get_db),
) -> TagStats:
    return await analytics_service.tags(session, since=from_date, until=to_date)
