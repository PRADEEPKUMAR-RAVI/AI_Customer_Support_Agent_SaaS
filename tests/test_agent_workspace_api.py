"""M7 HTTP surface: presence, queue, claim/release, reply/notes, and agent-resolve via PATCH.
Needs a live Postgres + Redis."""

from __future__ import annotations

import uuid

import pytest

from app.domain.escalation.reasons import EscalationReason
from app.infra.db.models.conversation import Conversation
from app.infra.db.session import with_tenant
from app.services.escalation_service import escalate
from app.services.ticket_service import get_or_create_ticket, start_ai_handling
from tests.helpers import auth_headers, client, invite_and_activate_staff, signup_verified_admin

pytestmark = pytest.mark.rls


async def _make_escalated_ticket(tenant_id: str) -> str:
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = ticket.id
    async with with_tenant(tenant_id) as session:
        await start_ai_handling(session, ticket_id=ticket_id)
    async with with_tenant(tenant_id) as session:
        result = await escalate(
            session, ticket_id=ticket_id, tenant_id=tenant_id, reason=EscalationReason.EXPLICIT
        )
        assert result.applied
    return str(ticket_id)


async def test_presence_toggle():
    _, _, _, admin_token = await signup_verified_admin()
    async with client() as c:
        res = await c.post(
            "/api/v1/agents/presence", json={"status": "available"}, headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "available"

        res = await c.post(
            "/api/v1/agents/presence", json={"status": "away"}, headers=auth_headers(admin_token)
        )
        assert res.status_code == 200, res.text


async def test_queue_lists_escalated_tickets_fifo():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    first = await _make_escalated_ticket(tenant_id)
    second = await _make_escalated_ticket(tenant_id)

    async with client() as c:
        res = await c.get("/api/v1/agents/queue", headers=auth_headers(admin_token))
        assert res.status_code == 200, res.text
        ids = [item["id"] for item in res.json()]
        assert ids == [first, second]  # FIFO by escalated_at
        assert res.json()[0]["wait_seconds"] >= 0


async def test_claim_then_second_agent_gets_409():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_escalated_ticket(tenant_id)
    _, _, agent_token = await invite_and_activate_staff(admin_token=admin_token, tenant_id=tenant_id)

    async with client() as c:
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/claim", headers=auth_headers(agent_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "with_agent"

        # A second agent trying the same ticket must be rejected — one holder at a time.
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/claim", headers=auth_headers(admin_token)
        )
        assert res.status_code == 409, res.text

    # The queue no longer lists the claimed ticket.
    async with client() as c:
        res = await c.get("/api/v1/agents/queue", headers=auth_headers(admin_token))
        assert ticket_id not in [item["id"] for item in res.json()]


async def test_reply_and_notes_require_being_the_current_assignee():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_escalated_ticket(tenant_id)
    _, _, agent_token = await invite_and_activate_staff(admin_token=admin_token, tenant_id=tenant_id)

    async with client() as c:
        await c.post(f"/api/v1/tickets/{ticket_id}/claim", headers=auth_headers(agent_token))

        # The admin (not the claiming agent) is read-only on this ticket.
        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reply",
            json={"content": "hello"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 403, res.text

        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/reply",
            json={"content": "We're looking into it."},
            headers=auth_headers(agent_token),
        )
        assert res.status_code == 200, res.text

        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/notes",
            json={"content": "customer sounded frustrated"},
            headers=auth_headers(agent_token),
        )
        assert res.status_code == 200, res.text

    async with client() as c:
        res = await c.get(
            f"/api/v1/tickets/{ticket_id}/context", headers=auth_headers(admin_token)
        )
        body = res.json()
        assert any(m["content"] == "We're looking into it." for m in body["transcript"])
        assert any(n["content"] == "customer sounded frustrated" for n in body["internal_notes"])
        assert body["live_record"]["status"] == "unavailable"


async def test_release_requires_current_assignee_then_reopens_the_queue():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_escalated_ticket(tenant_id)
    _, _, agent_token = await invite_and_activate_staff(admin_token=admin_token, tenant_id=tenant_id)

    async with client() as c:
        await c.post(f"/api/v1/tickets/{ticket_id}/claim", headers=auth_headers(agent_token))

        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/release", headers=auth_headers(admin_token)
        )
        assert res.status_code == 403, res.text

        res = await c.post(
            f"/api/v1/tickets/{ticket_id}/release", headers=auth_headers(agent_token)
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "escalated"

    async with client() as c:
        res = await c.get("/api/v1/agents/queue", headers=auth_headers(admin_token))
        assert ticket_id in [item["id"] for item in res.json()]


async def test_resolve_via_patch_requires_current_assignee():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    ticket_id = await _make_escalated_ticket(tenant_id)
    _, _, agent_token = await invite_and_activate_staff(admin_token=admin_token, tenant_id=tenant_id)

    async with client() as c:
        await c.post(f"/api/v1/tickets/{ticket_id}/claim", headers=auth_headers(agent_token))

        res = await c.patch(
            f"/api/v1/tickets/{ticket_id}", json={"state": "resolved"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 403, res.text

        res = await c.patch(
            f"/api/v1/tickets/{ticket_id}", json={"state": "resolved"},
            headers=auth_headers(agent_token),
        )
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "resolved"


async def test_resolve_via_patch_rejected_when_not_with_agent():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    async with with_tenant(tenant_id) as session:
        conversation = Conversation(session_id=f"sess-{uuid.uuid4().hex}")
        session.add(conversation)
        await session.flush()
        ticket = await get_or_create_ticket(session, conversation_id=conversation.id)
        ticket_id = str(ticket.id)  # still `new`

    async with client() as c:
        res = await c.patch(
            f"/api/v1/tickets/{ticket_id}", json={"state": "resolved"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 409
