"""v1 API aggregation. Feature routers (M1 admin, M3 knowledge, M4 records, M5 tickets,
M7 agents, M8 analytics, M10 ops) are added here by their owners as they land."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import analytics, auth, health, knowledge, records, widget

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(widget.router)
api_router.include_router(knowledge.router)
api_router.include_router(records.router)
api_router.include_router(records.live_router)
api_router.include_router(analytics.router)
