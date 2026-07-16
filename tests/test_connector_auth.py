"""Phase-1 connector helpers — API auth strategies, response-path extraction, DSN normalization,
and OAuth2 client-credentials token fetch. All offline: httpx.MockTransport at a public IP so the
SSRF guard genuinely passes, and OAuth uses connector_id=None (no Redis).
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.infra.connectors.api_resolver import ApiResolver, _extract_path
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.connectors.db_resolver import normalize_pg_dsn
from app.infra.connectors.oauth import get_access_token
from app.services.record_service import _build_db_dsn


# ── response-path extractor ──────────────────────────────────────────────────────────────────

def test_extract_path_dotted():
    assert _extract_path({"data": {"order": {"id": 1}}}, "data.order") == {"id": 1}


def test_extract_path_blank_returns_body():
    body = {"id": 1}
    assert _extract_path(body, None) is body
    assert _extract_path(body, "") is body


def test_extract_path_missing_returns_none():
    assert _extract_path({"data": {}}, "data.order") is None
    assert _extract_path({"data": "x"}, "data.order") is None


# ── DSN normalization + guided DSN build ─────────────────────────────────────────────────────

def test_normalize_pg_dsn_variants():
    assert normalize_pg_dsn("postgresql://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"
    assert normalize_pg_dsn("postgres://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"
    assert normalize_pg_dsn("postgresql+psycopg2://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"
    assert normalize_pg_dsn("postgresql+asyncpg://u:p@h/d") == "postgresql+asyncpg://u:p@h/d"


def test_normalize_pg_dsn_rejects_non_postgres():
    for bad in ("mysql://u:p@h/d", "sqlite:///x.db", "no-scheme"):
        with pytest.raises(ConnectorError):
            normalize_pg_dsn(bad)


def test_build_db_dsn_guided_encodes_credentials():
    dsn = _build_db_dsn(
        {"host": "db.example.com", "port": 5432, "database": "shop", "username": "ro"}, "p@ss:word"
    )
    assert dsn == "postgresql+asyncpg://ro:p%40ss%3Aword@db.example.com:5432/shop"


def test_build_db_dsn_raw_secret_is_dsn():
    assert _build_db_dsn({}, "postgresql://u:p@h:5432/d") == "postgresql+asyncpg://u:p@h:5432/d"


# ── API auth strategies (assert what the outgoing request carries) ───────────────────────────

def _recording_transport(record_body: dict):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        return httpx.Response(200, json=record_body)

    return httpx.MockTransport(handler), seen


async def test_api_key_header():
    transport, seen = _recording_transport({"email": "a@x.test"})
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={"type": "api_key", "in": "header", "name": "X-Api-Key", "secret": "k123"},
        transport=transport,
    )
    assert await r.fetch("t", "order", "1") == {"email": "a@x.test"}
    assert seen[0].headers["x-api-key"] == "k123"


async def test_api_key_query():
    transport, seen = _recording_transport({"email": "a@x.test"})
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={"type": "api_key", "in": "query", "name": "api_key", "secret": "k123"},
        transport=transport,
    )
    await r.fetch("t", "order", "1")
    assert seen[0].url.params.get("api_key") == "k123"


async def test_bearer():
    transport, seen = _recording_transport({"email": "a@x.test"})
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={"type": "bearer", "secret": "tok"}, transport=transport,
    )
    await r.fetch("t", "order", "1")
    assert seen[0].headers["authorization"] == "Bearer tok"


async def test_basic():
    transport, seen = _recording_transport({"email": "a@x.test"})
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={"type": "basic", "username": "u", "secret": "p"}, transport=transport,
    )
    await r.fetch("t", "order", "1")
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert seen[0].headers["authorization"] == expected


async def test_oauth2_fetches_token_then_applies_bearer():
    transport, seen = _recording_transport({"email": "a@x.test"})
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={
            "type": "oauth2_client_credentials",
            "token_url": "http://8.8.8.8/oauth/token",
            "client_id": "cid", "secret": "csecret",
        },
        connector_id=None, transport=transport,
    )
    rec = await r.fetch("t", "order", "1")
    assert rec == {"email": "a@x.test"}
    assert any(req.url.path.endswith("/oauth/token") for req in seen)
    record_req = next(req for req in seen if req.url.path == "/orders/1")
    assert record_req.headers["authorization"] == "Bearer tok-123"


async def test_response_path_extraction():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"order": {"email": "a@x.test", "extra": "x"}}})

    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        response_path="data.order", transport=httpx.MockTransport(handler),
    )
    assert await r.fetch("t", "order", "1") == {"email": "a@x.test"}


async def test_response_path_missing_is_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        response_path="data.order", transport=httpx.MockTransport(handler),
    )
    assert await r.fetch("t", "order", "1") is NOT_FOUND


async def test_unsupported_auth_type_raises():
    r = ApiResolver(
        base_url="http://8.8.8.8", path_template="/orders/{key}", field_map={"email": "email"},
        auth={"type": "kerberos", "secret": "x"}, transport=_recording_transport({})[0],
    )
    with pytest.raises(ConnectorError) as ei:
        await r.fetch("t", "order", "1")
    assert ei.value.kind == "auth"


# ── OAuth2 token endpoint (no Redis: connector_id=None) ──────────────────────────────────────

async def test_oauth_token_fetch_ok():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
    )
    tok = await get_access_token(
        connector_id=None, version=None, token_url="http://8.8.8.8/token",
        client_id="c", client_secret="s", transport=transport,
    )
    assert tok == "abc"


async def test_oauth_token_missing_access_token_is_auth_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ConnectorError) as ei:
        await get_access_token(
            connector_id=None, version=None, token_url="http://8.8.8.8/token",
            client_id="c", client_secret="s", transport=transport,
        )
    assert ei.value.kind == "auth"


async def test_oauth_token_401_is_auth_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(401))
    with pytest.raises(ConnectorError) as ei:
        await get_access_token(
            connector_id=None, version=None, token_url="http://8.8.8.8/token",
            client_id="c", client_secret="s", transport=transport,
        )
    assert ei.value.kind == "auth"


async def test_oauth_token_url_ssrf_blocked():
    with pytest.raises(ConnectorError) as ei:
        await get_access_token(
            connector_id=None, version=None, token_url="http://localhost/token",
            client_id="c", client_secret="s",
        )
    assert ei.value.kind == "connection"
