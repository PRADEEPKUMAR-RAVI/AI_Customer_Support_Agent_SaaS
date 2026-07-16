"""ApiResolver — fetch a record live from a tenant's own HTTP endpoint ([T4]).

Security ([IMP-SEC-5]): the URL is SSRF-validated before every request (blocks localhost /
private / cloud-metadata); auto-redirects are disabled and each redirect hop is re-validated
(bounded) so a tenant URL can't bounce into internal services. TLS required in prod. Fetch only.

Config (non-secret) on the connector: ``base_url``, ``method`` (GET), ``path_template`` (``/orders/
{key}``), optional ``response_path`` (dotted path to the record object, e.g. ``data.order``), and an
``auth`` block. The ONE secret (the decrypted credential) is merged into the in-memory ``auth`` dict
by ``get_resolver`` under ``secret``. Supported ``auth.type``: ``none``, ``api_key`` (header|query),
``bearer``, ``basic``, ``oauth2_client_credentials``. ``field_map`` maps response JSON keys -> schema
fields. The legacy ``auth_header``/``auth_scheme``/``auth_secret`` params still work (auth=None).
"""

from __future__ import annotations

import base64

import httpx

from app.core.config import TenantDefaults
from app.core.ssrf import SSRFBlocked, resolve_and_validate
from app.infra.connectors.base import NOT_FOUND, ConnectorError, RawRecord, _NotFound
from app.infra.connectors.oauth import get_access_token

_MAX_REDIRECTS = 2


def _extract_path(body: object, path: str | None) -> object:
    """Walk a dotted path (``data.order``) into a parsed JSON body. Blank path -> body unchanged.
    Returns ``None`` if any segment is missing so the caller maps it to NOT_FOUND."""
    if not path:
        return body
    cur = body
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class ApiResolver:
    def __init__(
        self,
        *,
        base_url: str,
        path_template: str,
        field_map: dict[str, str],
        method: str = "GET",
        auth: dict | None = None,
        response_path: str | None = None,
        connector_id: str | None = None,
        version: int | None = None,
        # legacy single-header auth (kept for back-compat with existing connectors + tests):
        auth_header: str | None = None,
        auth_scheme: str | None = None,
        auth_secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._path_template = path_template
        self._field_map = field_map
        self._method = method.upper()
        self._auth = auth
        self._response_path = response_path
        self._connector_id = connector_id
        self._version = version
        self._auth_header = auth_header
        self._auth_scheme = auth_scheme
        self._auth_secret = auth_secret
        self._transport = transport  # test seam; None -> real network

    async def _authenticate(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (headers, query_params) to attach to the request. May fetch an OAuth token."""
        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        if self._auth is None:
            # Legacy path: a single static header.
            if self._auth_header and self._auth_secret:
                value = (
                    f"{self._auth_scheme} {self._auth_secret}"
                    if self._auth_scheme
                    else self._auth_secret
                )
                headers[self._auth_header] = value
            return headers, params

        atype = self._auth.get("type") or "none"
        secret = self._auth.get("secret") or ""
        if atype == "none":
            return headers, params
        if atype == "api_key":
            name = self._auth.get("name") or "X-API-Key"
            if self._auth.get("in") == "query":
                params[name] = secret
            else:
                headers[name] = secret
        elif atype == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        elif atype == "basic":
            raw = f"{self._auth.get('username', '')}:{secret}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        elif atype in ("oauth2", "oauth2_client_credentials"):
            token = await get_access_token(
                connector_id=self._connector_id,
                version=self._version,
                token_url=self._auth["token_url"],
                client_id=self._auth.get("client_id", ""),
                client_secret=secret,
                scope=self._auth.get("scope"),
                transport=self._transport,
            )
            headers["Authorization"] = f"Bearer {token}"
        else:
            raise ConnectorError("auth", f"unsupported auth type: {atype}")
        return headers, params

    async def fetch(self, tenant_id: str, record_type: str, key: str) -> RawRecord | _NotFound:
        url = self._base_url + self._path_template.replace("{key}", str(key))
        timeout = TenantDefaults.CONNECTOR_TIMEOUT_SECONDS
        try:
            headers, params = await self._authenticate()  # may raise ConnectorError (oauth)
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=timeout, transport=self._transport
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    resolve_and_validate(url)  # re-validate every hop
                    resp = await client.request(self._method, url, headers=headers, params=params)
                    if resp.is_redirect and resp.headers.get("location"):
                        url = str(httpx.URL(url).join(resp.headers["location"]))
                        continue
                    break
                else:
                    raise ConnectorError("connection", "too many redirects")
        except SSRFBlocked as exc:
            raise ConnectorError("connection", f"blocked URL: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ConnectorError("timeout", "API request timed out") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError("connection", str(exc)[:200]) from exc

        if resp.status_code in (401, 403):
            raise ConnectorError("auth", f"tenant API returned {resp.status_code}")
        if resp.status_code == 404:
            return NOT_FOUND
        if resp.status_code >= 400:
            raise ConnectorError("connection", f"tenant API returned {resp.status_code}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ConnectorError("connection", "non-JSON response") from exc
        record = _extract_path(body, self._response_path)
        if not isinstance(record, dict):
            return NOT_FOUND
        return {sf: record[src] for src, sf in self._field_map.items() if src in record}
