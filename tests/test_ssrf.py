"""SSRF guard — resolve-and-validate blocks internal targets (CI gate for [IMP-SEC-5])."""

from __future__ import annotations

import pytest

from app.core.ssrf import SSRFBlocked, ip_is_blocked, resolve_and_validate


def test_private_and_special_ips_are_blocked():
    for ip in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"]:
        assert ip_is_blocked(ip) is True


def test_public_ip_is_allowed():
    assert ip_is_blocked("8.8.8.8") is False
    assert ip_is_blocked("1.1.1.1") is False


def test_localhost_url_is_rejected():
    # localhost resolves to a loopback address -> blocked (no network needed).
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("http://localhost/admin")
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("http://127.0.0.1:5432/")


def test_non_http_scheme_rejected():
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("file:///etc/passwd")
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("gopher://internal/")
