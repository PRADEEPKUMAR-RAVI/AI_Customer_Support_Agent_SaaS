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


async def test_patch_settings_clamps_healthcare_verify_attempts_to_one():
    # Safety: an admin must NOT be able to raise a healthcare tenant's verify attempts above the
    # §4.8.2 N=1 non-negotiable via the untyped settings PATCH.
    _, _, _, token = await signup_verified_admin(industry="healthcare")
    async with client() as c:
        res = await c.patch(
            "/api/v1/admin/settings", headers=auth_headers(token),
            json={"config": {"verify_max_attempts": 99}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["config"]["verify_max_attempts"] == 1


async def test_patch_settings_clamps_relevance_threshold_to_unit_interval():
    _, _, _, token = await signup_verified_admin()
    async with client() as c:
        res = await c.patch(
            "/api/v1/admin/settings", headers=auth_headers(token),
            json={"config": {"relevance_threshold": 5.0}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["config"]["relevance_threshold"] == 1.0


async def test_allowed_domain_crud_roundtrip():
    _, _, _, token = await signup_verified_admin()
    async with client() as c:
        add = await c.post(
            "/api/v1/admin/allowed-domains", headers=auth_headers(token),
            json={"domain": "Example.com/"},
        )
        assert add.status_code == 201, add.text
        assert add.json()["domain"] == "example.com"  # normalized (lowercased, trailing / stripped)
        domain_id = add.json()["id"]

        listed = await c.get("/api/v1/admin/allowed-domains", headers=auth_headers(token))
        assert any(d["domain"] == "example.com" for d in listed.json())

        removed = await c.delete(
            f"/api/v1/admin/allowed-domains/{domain_id}", headers=auth_headers(token)
        )
        assert removed.status_code == 204
        listed2 = await c.get("/api/v1/admin/allowed-domains", headers=auth_headers(token))
        assert all(d["id"] != domain_id for d in listed2.json())
