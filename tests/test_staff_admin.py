"""M1 Phase-2 full: staff invite/manage, forgot/reset-password, widget-key rotate, embed
snippet, and agent_settings PATCH + hot-cache invalidation."""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_token, decode_token
from app.infra.cache.redis import get_redis
from tests.helpers import auth_headers, client, signup_verified_admin

pytestmark = pytest.mark.rls


async def test_get_tenant_returns_industry_for_onboarding():
    _, _, _, admin_token = await signup_verified_admin(industry="healthcare")
    async with client() as c:
        res = await c.get("/api/v1/admin/tenant", headers=auth_headers(admin_token))
        assert res.status_code == 200, res.text
        assert res.json()["industry"] == "healthcare"
        assert res.json()["status"] == "active"


async def test_admin_invites_staff_and_lists_them():
    _, _, _, admin_token = await signup_verified_admin()
    # `staff.email` has a global-unique index ("one tenant per person" POC constraint) —
    # randomize so reruns against a persistent dev DB never collide with a prior run's row.
    invitee_email = f"agent-{uuid.uuid4().hex}@example.com"
    async with client() as c:
        res = await c.post(
            "/api/v1/admin/staff",
            json={"email": invitee_email, "role": "agent"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 201, res.text
        assert res.json()["role"] == "agent"
        assert res.json()["email_verified"] is False

        res = await c.get("/api/v1/admin/staff", headers=auth_headers(admin_token))
        assert res.status_code == 200, res.text
        emails = {row["email"] for row in res.json()}
        assert invitee_email in emails


async def test_invited_staff_accepts_via_reset_password_and_can_log_in():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    invitee_email = f"agent-{uuid.uuid4().hex}@example.com"
    async with client() as c:
        invite_res = await c.post(
            "/api/v1/admin/staff",
            json={"email": invitee_email, "role": "agent"},
            headers=auth_headers(admin_token),
        )
        staff_id = invite_res.json()["id"]

    # Mint the equivalent invite token directly (mirrors the outbox email, as in the verify
    # flow). `ver: 0` matches the invited staff row's default `token_version`.
    invite_token = create_token(
        {
            "typ": "invite", "sub": staff_id, "tenant_id": tenant_id,
            "email": invitee_email, "ver": 0,
        },
        7 * 24 * 3600,
    )
    async with client() as c:
        res = await c.post(
            "/api/v1/auth/reset-password",
            json={"token": invite_token, "new_password": "a-brand-new-password"},
        )
        assert res.status_code == 200, res.text

        res = await c.post(
            "/api/v1/auth/login",
            json={"email": invitee_email, "password": "a-brand-new-password"},
        )
        assert res.status_code == 200, res.text


async def test_admin_cannot_deactivate_own_account():
    _, _, _, admin_token = await signup_verified_admin()
    claims = decode_token(admin_token)
    async with client() as c:
        res = await c.patch(
            f"/api/v1/admin/staff/{claims['sub']}",
            json={"is_active": False},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 400


async def test_forgot_password_gives_the_same_response_for_unknown_and_known_email():
    async with client() as c:
        res = await c.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
        assert res.status_code == 200
        message_for_unknown = res.json()["message"]

    email, _, _, _ = await signup_verified_admin()
    async with client() as c:
        res = await c.post("/api/v1/auth/forgot-password", json={"email": email})
        assert res.status_code == 200
        assert res.json()["message"] == message_for_unknown


async def test_reset_password_token_is_single_use():
    email, _, tenant_id, admin_token = await signup_verified_admin()
    claims = decode_token(admin_token)
    # `ver: 0` matches the freshly-signed-up admin's default `token_version`.
    reset_token = create_token(
        {"typ": "reset", "sub": claims["sub"], "tenant_id": tenant_id, "email": email, "ver": 0},
        3600,
    )
    async with client() as c:
        res = await c.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "first-new-password"},
        )
        assert res.status_code == 200, res.text

        # Replaying the same token must fail — its `ver: 0` no longer matches token_version=1.
        res = await c.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "second-new-password"},
        )
        assert res.status_code == 400


async def test_widget_key_rotate_deactivates_the_old_key():
    _, _, _, admin_token = await signup_verified_admin()
    async with client() as c:
        before = await c.get("/api/v1/admin/embed-snippet", headers=auth_headers(admin_token))
        old_key = before.json()["widget_key"]

        rotated = await c.post(
            "/api/v1/admin/widget-key/rotate", headers=auth_headers(admin_token)
        )
        assert rotated.status_code == 200, rotated.text
        new_key = rotated.json()["widget_key"]
        assert new_key != old_key

        session_res = await c.post("/api/v1/widget/session", json={"widget_key": old_key})
        assert session_res.status_code == 404

        session_res = await c.post("/api/v1/widget/session", json={"widget_key": new_key})
        assert session_res.status_code == 200


async def test_patch_settings_merges_and_invalidates_hot_cache():
    _, _, tenant_id, admin_token = await signup_verified_admin()
    redis = get_redis()
    await redis.set(f"settings:{tenant_id}", "stale-cached-value")

    async with client() as c:
        res = await c.patch(
            "/api/v1/admin/settings",
            json={"config": {"persona": "A witty, upbeat assistant."}},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 200, res.text
        config = res.json()["config"]
        assert config["persona"] == "A witty, upbeat assistant."
        assert config["welcome_message"]  # untouched keys survive the shallow merge

    assert await redis.get(f"settings:{tenant_id}") is None
