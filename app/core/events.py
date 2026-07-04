"""Transactional outbox primitive (audit [IMP-WRK-1]).

``emit`` adds an ``outbox`` row to the CALLER's session, so the event is committed atomically
with the state change that produced it (or rolled back with it). The M9 relay drains pending
rows out-of-band. ``tenant_id`` auto-fills from the tenant GUC.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def emit(
    session: AsyncSession,
    *,
    event_type: str,
    payload: dict,
    dedupe_key: str | None = None,
) -> None:
    from app.infra.db.models.outbox import Outbox  # lazy import

    session.add(Outbox(event_type=event_type, payload=payload, dedupe_key=dedupe_key))
