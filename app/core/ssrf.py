"""Shared SSRF egress guard — resolve-and-validate (audit [IMP-SEC-5]).

Used by the KB crawler AND the API/DB connectors. A blocklist on hostnames is NOT enough:
we resolve the host and reject if ANY resolved IP is loopback / private / link-local /
reserved / multicast (blocks 127.0.0.1, 169.254.169.254 cloud-metadata, 10/8, ::1, etc.),
then pin the connection to the validated IP and re-validate on every redirect hop.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlocked(Exception):
    pass


def ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> fail closed
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def resolve_and_validate(url: str) -> list[str]:
    """Validate a tenant-supplied URL. Returns the list of validated public IPs (pin the
    connection to one of these). Raises ``SSRFBlocked`` on scheme/host/IP problems."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlocked(f"scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SSRFBlocked("missing host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise SSRFBlocked(f"dns resolution failed: {exc}") from exc
    ips = {info[4][0] for info in infos}
    if not ips:
        raise SSRFBlocked("no addresses resolved")
    for ip in ips:
        if ip_is_blocked(ip):
            raise SSRFBlocked(f"resolved to a non-public address: {ip}")
    return sorted(ips)
