"""v1 API aggregation. Feature routers are registered here by their owners as they land."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import admin, agents, auth, conversations, health, ops, records, tickets, widget

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(records.router)
api_router.include_router(tickets.router)
api_router.include_router(agents.router)
api_router.include_router(ops.router)
api_router.include_router(widget.router)
api_router.include_router(conversations.router)
