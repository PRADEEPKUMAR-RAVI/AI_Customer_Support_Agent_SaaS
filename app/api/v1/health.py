"""Liveness + readiness. (The authed deep dependency probe is M10 ``GET /ops/health``.)"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.infra.cache.redis import get_redis
from app.infra.db.engine import engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Shallow, unauthenticated liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness: ping Postgres + Redis. 503 if any dependency is down."""
    components: dict[str, str] = {}
    ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        components["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["postgres"] = f"down: {type(exc).__name__}"
        ok = False
    try:
        await get_redis().ping()
        components["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["redis"] = f"down: {type(exc).__name__}"
        ok = False
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "components": components},
    )
