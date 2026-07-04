"""URL crawler unit tests (M3, §4.6) — offline via httpx.MockTransport.

Uses a public test IP (8.8.8.8) so the SSRF guard genuinely passes; localhost must be blocked.
Covers same-site link following, off-site exclusion, auth-gated (401) + login-page skipping.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.ssrf import SSRFBlocked
from app.infra.crawler import crawl_url


def _html(body: str) -> httpx.Response:
    return httpx.Response(200, content=f"<html><body>{body}</body></html>".encode(),
                          headers={"content-type": "text/html; charset=utf-8"})


async def test_crawl_blocks_localhost_seed():
    with pytest.raises(SSRFBlocked):
        await crawl_url("http://localhost/")


async def test_crawl_follows_same_site_and_skips_offsite():
    pages = {
        "/": '<p>Return policy: 30 days.</p><a href="/page2">more</a><a href="http://evil.example/x">bad</a>',
        "/page2": "<p>Shipping takes three business days.</p>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        return _html(pages[path]) if path in pages else httpx.Response(404)

    segments = await crawl_url("http://8.8.8.8/", transport=httpx.MockTransport(handler))
    urls = {s.source_url for s in segments}
    assert "http://8.8.8.8/" in urls
    assert "http://8.8.8.8/page2" in urls
    assert not any("evil.example" in (s.source_url or "") for s in segments)  # off-site not followed
    home = next(s for s in segments if s.source_url == "http://8.8.8.8/")
    assert "Return policy" in home.text and "30 days" in home.text


async def test_crawl_skips_auth_gated_and_login_pages():
    pages = {
        "/": '<p>Public info on returns.</p><a href="/secret">s</a><a href="/login">l</a>',
        "/login": "<form><input type=\"password\" name=\"pw\"></form>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/secret":
            return httpx.Response(401)  # auth-gated
        return _html(pages[path]) if path in pages else httpx.Response(404)

    segments = await crawl_url("http://8.8.8.8/", transport=httpx.MockTransport(handler))
    joined = " ".join(s.text for s in segments)
    assert "Public info" in joined
    assert "password" not in joined  # login page yields no text
    assert not any((s.source_url or "").endswith("/secret") for s in segments)  # 401 skipped
