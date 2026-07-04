"""M2 customer-facing endpoints: send a message (SSE stream), rate a turn, load the transcript.

Anonymous auth is the signed widget **session token** minted at /widget/session (bound to
tenant+session+conversation). The message endpoint returns an SSE stream; the others are JSON.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.errors import AppError
from app.core.security import decode_token
from app.infra.db.models.conversation import Conversation, Message
from app.infra.db.session import with_tenant
from app.services.conversation_service import WidgetCtx, handle_message

router = APIRouter(tags=["conversations"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


async def get_widget_ctx(authorization: str | None = Header(default=None)) -> WidgetCtx:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(status_code=401, title="Missing widget session token", code="unauthenticated")
    try:
        claims = decode_token(authorization.split(" ", 1)[1])
    except Exception as exc:  # noqa: BLE001
        raise AppError(status_code=401, title="Invalid or expired session", code="invalid_token") from exc
    if claims.get("typ") != "widget":
        raise AppError(status_code=401, title="Wrong token type", code="invalid_token")
    return WidgetCtx(
        tenant_id=claims["tenant_id"],
        session_id=claims["session_id"],
        conversation_id=claims["conversation_id"],
    )


def _require_own_conversation(conversation_id: str, ctx: WidgetCtx) -> None:
    if conversation_id != ctx.conversation_id:
        raise AppError(status_code=403, title="Not your conversation", code="forbidden")


class MessageRequest(BaseModel):
    client_msg_id: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=8000)
    escalate_request: bool = False  # first-class "talk to a human" ([IMP-ESC-5])
    # [A15] optional follow-up address (after-hours capture); a bad value is ignored, not rejected.
    contact_email: str | None = Field(default=None, max_length=320)


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: str, body: MessageRequest, ctx: WidgetCtx = Depends(get_widget_ctx)
) -> StreamingResponse:
    _require_own_conversation(conversation_id, ctx)
    gen = handle_message(
        ctx, user_text=body.content, client_msg_id=body.client_msg_id,
        escalate_request=body.escalate_request, contact_email=body.contact_email,
    )
    return StreamingResponse(gen, media_type="text/event-stream", headers=_SSE_HEADERS)


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]


@router.post("/conversations/{conversation_id}/messages/{message_id}/feedback")
async def post_feedback(
    conversation_id: str, message_id: str, body: FeedbackRequest,
    ctx: WidgetCtx = Depends(get_widget_ctx),
) -> dict:
    _require_own_conversation(conversation_id, ctx)
    async with with_tenant(ctx.tenant_id) as session:
        msg = (
            await session.execute(
                select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
            )
        ).scalar_one_or_none()
        if msg is None or msg.role != "ai":
            raise AppError(status_code=404, title="Message not found", code="not_found")
        # POC: store thumbs on the message. person-2 moves this to a dedicated feedback table (CSAT).
        so = dict(msg.structured_out or {})
        so["feedback"] = body.rating
        msg.structured_out = so
    return {"status": "recorded"}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, ctx: WidgetCtx = Depends(get_widget_ctx)
) -> dict:
    _require_own_conversation(conversation_id, ctx)
    async with with_tenant(ctx.tenant_id) as session:
        conv = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        ).scalar_one_or_none()
        if conv is None or conv.session_id != ctx.session_id:
            raise AppError(status_code=404, title="Conversation not found", code="not_found")
        msgs = (
            await session.execute(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
            )
        ).scalars().all()
        return {
            "conversation_id": conversation_id,
            "language": conv.language,
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "structured_out": m.structured_out,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in msgs
            ],
        }
