"""M5 tickets HTTP surface: list/filter, detail, patch, reopen, tag approve, and the aggregated
``GET /tickets/{id}/context`` payload."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.infra.db.models.conversation import Conversation
from app.infra.db.models.ticket import Ticket
from app.infra.db.session import with_tenant
from app.services.tag_service import propose_tag
from app.services.ticket_service import get_or_create_ticket, resolve_ticket, start_ai_handling
from tests.helpers import auth_headers, client, signup_verified_admin

pytestmark = pytest.mark.rls


async def _make_resolved_ticket(
    tenant_id: str, *, closed_hours_ago: float | None = None, assignee_id: uuid.UUID | None = None
) -> uuid.UUID:
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = ticket.id
        await start_ai_handling(session, ticket_id=ticket_id)
    async with with_tenant(tenant_id) as session:
        await resolve_ticket(session, ticket_id=ticket_id)
    if closed_hours_ago is not None or assignee_id is not None:
        values = {"state": "closed"}
        values["closed_at"] = datetime.now(timezone.utc) - timedelta(
            hours=closed_hours_ago if closed_hours_ago is not None else 0
        )
        if assignee_id is not None:
            values["assignee_id"] = assignee_id
        async with with_tenant(tenant_id) as session:
            await session.execute(update(Ticket).where(Ticket.id == ticket_id).values(**values))
    return ticket_id


async def test_list_tickets_filters_by_status_and_tag():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        await propose_tag(session, ticket_id=ticket_id, name="billing", allowed_tags=["billing"])

    async with client() as c:
        res = await c.get(
            "/api/v1/tickets", params={"status": "resolved"}, headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 1
        assert res.json()["items"][0]["tags"][0]["name"] == "billing"

        res = await c.get(
            "/api/v1/tickets", params={"tag": "billing"}, headers=auth_headers(admin_token)
        )
        assert res.json()["total"] == 1

        res = await c.get(
            "/api/v1/tickets", params={"tag": "nope"}, headers=auth_headers(admin_token)
        )
        assert res.json()["total"] == 0


async def test_get_and_patch_ticket():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id)

    async with client() as c:
        res = await c.get(f"/api/v1/tickets/{ticket_id}", headers=auth_headers(admin_token))
        assert res.status_code == 200, res.text
        assert res.json()["priority"] == "normal"

        res = await c.patch(
            f"/api/v1/tickets/{ticket_id}", json={"priority": "high"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 200, res.text
        assert res.json()["priority"] == "high"


async def test_ticket_context_is_a_clean_pending_state_before_m2_exists():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id)

    async with client() as c:
        res = await c.get(
            f"/api/v1/tickets/{ticket_id}/context", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["transcript"] == []
        assert body["ai_summary"] is None
        assert body["linked_record_pointer"] is None


async def test_reopen_within_window_with_no_prior_agent_routes_to_ai_handling():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id, closed_hours_ago=1)

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reopen", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "ai_handling"


async def test_reopen_of_a_merely_resolved_not_yet_closed_ticket_is_always_eligible():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    # No closed_hours_ago -> state stays `resolved`, closed_at stays NULL: the 72h clock
    # hasn't started, so this must reopen even though "beyond window" would otherwise apply.
    ticket_id = await _make_resolved_ticket(tenant_id)

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reopen", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "ai_handling"


async def test_reopen_beyond_window_also_routes_to_ai_handling():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id, closed_hours_ago=100)  # > 72h default

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reopen", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "ai_handling"


async def test_reopen_within_window_with_prior_agent_routes_back_to_with_agent():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(
        tenant_id, closed_hours_ago=1, assignee_id=uuid.uuid4()
    )

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reopen", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "with_agent"


async def test_reopen_rejected_when_ticket_is_not_resolved_or_closed():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = ticket.id  # still `new`

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reopen", headers=auth_headers(admin_token)
        )
        assert res.status_code == 409


async def test_tag_approve_endpoint():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_resolved_ticket(tenant_id)
    async with with_tenant(tenant_id) as session:
        tag = await propose_tag(session, ticket_id=ticket_id, name="novel", allowed_tags=[])
        tag_def_id = tag.tag_def_id

    async with client() as c:
        res = await c.post(
            f"/api/v1/admin/tags/{tag_def_id}/approve", headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "approved"
