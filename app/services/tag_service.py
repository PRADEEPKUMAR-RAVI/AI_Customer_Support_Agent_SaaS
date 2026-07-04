"""M5 tag classification — get-or-create a tenant-scoped ``tag_def``, attach it to a ticket via
``ticket_tag``, and the admin approve/reject flow.

``tag_def.status`` is the single authoritative approval state [IMP-TKT-6]; ``ticket_tag.status``
is a denormalized copy taken at tagging time. Approving/rejecting a def backfills every existing
``pending`` instance of it in the SAME transaction, so nothing is left stale.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tags import initial_status
from app.infra.db.models.tag import TagDef, TicketTag


async def _get_or_create_tag_def(
    session: AsyncSession, *, name: str, allowed_tags: list[str]
) -> TagDef:
    insert_stmt = (
        pg_insert(TagDef)
        .values(name=name, status=initial_status(name, allowed_tags))
        .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
    )
    await session.execute(insert_stmt)
    result = await session.execute(select(TagDef).where(TagDef.name == name))
    return result.scalar_one()


async def propose_tag(
    session: AsyncSession, *, ticket_id: uuid.UUID, name: str, allowed_tags: list[str]
) -> TicketTag:
    """Get-or-create the tag_def (curated -> auto-approved, else pending), then get-or-create
    the ticket_tag linking it to this ticket, denormalizing the def's CURRENT status. Idempotent
    — tagging the same ticket with the same name twice is a no-op the second time."""
    tag_def = await _get_or_create_tag_def(session, name=name, allowed_tags=allowed_tags)
    insert_stmt = (
        pg_insert(TicketTag)
        .values(ticket_id=ticket_id, tag_def_id=tag_def.id, status=tag_def.status)
        .on_conflict_do_nothing(index_elements=["tenant_id", "ticket_id", "tag_def_id"])
    )
    await session.execute(insert_stmt)
    result = await session.execute(
        select(TicketTag).where(
            TicketTag.ticket_id == ticket_id, TicketTag.tag_def_id == tag_def.id
        )
    )
    return result.scalar_one()


async def list_ticket_tags(session: AsyncSession, *, ticket_id: uuid.UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(TagDef.name, TicketTag.status)
            .join(TagDef, TagDef.id == TicketTag.tag_def_id)
            .where(TicketTag.ticket_id == ticket_id)
        )
    ).all()
    return [{"name": name, "status": status} for name, status in rows]


async def _set_tag_def_status(
    session: AsyncSession, *, tag_def_id: uuid.UUID, status: str
) -> TagDef | None:
    result = await session.execute(
        update(TagDef).where(TagDef.id == tag_def_id).values(status=status).returning(TagDef)
    )
    tag_def = result.scalar_one_or_none()
    if tag_def is None:
        return None
    await session.execute(
        update(TicketTag)
        .where(TicketTag.tag_def_id == tag_def_id, TicketTag.status == "pending")
        .values(status=status)
    )
    return tag_def


async def approve_tag_def(session: AsyncSession, *, tag_def_id: uuid.UUID) -> TagDef | None:
    return await _set_tag_def_status(session, tag_def_id=tag_def_id, status="approved")


async def reject_tag_def(session: AsyncSession, *, tag_def_id: uuid.UUID) -> TagDef | None:
    # `rejected` (not a delete) so a name the admin already declined doesn't keep re-flooding
    # the approval tray — future proposals of the same name hit the existing def and inherit
    # `rejected`, so they never surface as pending again.
    return await _set_tag_def_status(session, tag_def_id=tag_def_id, status="rejected")
