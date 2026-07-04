"""ApiResolver — fetch a record live from a tenant's own HTTP endpoint ([T4]).

Security ([IMP-SEC-5]): the URL is SSRF-validated before every request (blocks localhost /
private / cloud-metadata); auto-redirects are disabled and each redirect hop is re-validated
(bounded) so a tenant URL can't bounce into internal services. TLS required in prod. Fetch only.

Config (non-secret) on the connector: ``base_url``, ``method`` (GET), ``path_template`` (``/orders/
{key}``), and optional ``auth_header``/``auth_scheme``; the auth secret is the decrypted credential.
``field_map`` maps response JSON keys -> schema fields.
"""

from __future__ import annotations

import httpx

from app.core.config import TenantDefaults
from app.core.ssrf import SSRFBlocked, resolve_and_validate
from app.infra.connectors.base import NOT_FOUND, ConnectorError, RawRecord, _NotFound

_MAX_REDIRECTS = 2


class ApiResolver:
    def __init__(
        self,
        *,
        base_url: str,
        path_template: str,
        field_map: dict[str, str],
        method: str = "GET",
        auth_header: str | None = None,
        auth_scheme: str | None = None,
        auth_secret: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._path_template = path_template
        self._field_map = field_map
        self._method = method.upper()
        self._auth_header = auth_header
        self._auth_scheme = auth_scheme
        self._auth_secret = auth_secret
        self._transport = transport  # test seam; None -> real network

    def _headers(self) -> dict[str, str]:
        if self._auth_header and self._auth_secret:
            value = f"{self._auth_scheme} {self._auth_secret}" if self._auth_scheme else self._auth_secret
            return {self._auth_header: value}
        return {}

    async def fetch(self, tenant_id: str, record_type: str, key: str) -> RawRecord | _NotFound:
        url = self._base_url + self._path_template.replace("{key}", str(key))
        timeout = TenantDefaults.CONNECTOR_TIMEOUT_SECONDS
        try:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=timeout, transport=self._transport
            ) as client:
                for _ in range(_MAX_REDIRECTS + 1):
                    resolve_and_validate(url)  # re-validate every hop
                    resp = await client.request(self._method, url, headers=self._headers())
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
        if not isinstance(body, dict):
            return NOT_FOUND
        return {sf: body[src] for src, sf in self._field_map.items() if src in body}
