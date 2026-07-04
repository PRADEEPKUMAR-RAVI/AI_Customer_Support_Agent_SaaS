"""M1 Phase-1 slice, end-to-end through the real ASGI app: signup -> verify -> login ->
``GET /admin/settings``. Needs a live Postgres with the migration applied (same harness as
``test_rls_isolation.py``)."""

from __future__ import annotations

import pytest

from tests.helpers import auth_headers, client, signup_verified_admin

pytestmark = pytest.mark.rls


async def test_admin_can_read_agent_settings_after_signup_verify_login():
    _, _, _, access_token = await signup_verified_admin()
    async with client() as c:
        res = await c.get("/api/v1/admin/settings", headers=auth_headers(access_token))
        assert res.status_code == 200, res.text
        config = res.json()["config"]
        assert config["welcome_message"]
        assert config["default_language"] == "en"


async def test_admin_settings_requires_authentication():
    async with client() as c:
        res = await c.get("/api/v1/admin/settings")
        assert res.status_code == 401
