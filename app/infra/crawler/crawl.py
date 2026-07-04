"""Bounded, SSRF-safe URL crawler (M3, §4.6).

BFS from a seed URL, same registrable-site only, honoring robots.txt, skipping auth-gated pages,
bounded by depth/pages/bytes/timeout (``TenantDefaults.CRAWL_*``). Every request — including each
redirect hop — is re-validated with the shared SSRF guard so a tenant URL can't bounce into
internal services ([IMP-SEC-5]). Returns one ``ParseResult`` per page with ``source_url`` set for
citations; an empty result lets the ingest worker mark the source ``failed``.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.core.config import TenantDefaults
from app.core.ssrf import SSRFBlocked, resolve_and_validate
from app.infra.parsers.base import ParseResult

_USER_AGENT = "cs-agent-crawler"
_MAX_REDIRECTS = 3


def _registrable(host: str) -> str:
    return ".".join(host.split(".")[-2:]) if host else ""


def _same_site(seed: str, candidate: str) -> bool:
    a, b = urlsplit(seed).hostname or "", urlsplit(candidate).hostname or ""
    return bool(a) and _registrable(a) == _registrable(b)


def _extract_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "lxml")
    # Auth-gated heuristic: a password field means a login page — skip it.
    if soup.find("input", attrs={"type": "password"}):
        return ""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _links(seed: str, page_url: str, html: bytes) -> list[str]:
    out: list[str] = []
    for anchor in BeautifulSoup(html, "lxml").find_all("a", href=True):
        link = urljoin(page_url, anchor["href"]).split("#", 1)[0]
        if link.startswith(("http://", "https://")) and _same_site(seed, link):
            out.append(link)
    return out


async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """Fetch with manual, SSRF-revalidated redirects. Returns the final response, or None if the
    redirect chain is too long. Raises ``SSRFBlocked`` if any hop resolves to a non-public host."""
    for _ in range(_MAX_REDIRECTS + 1):
        resolve_and_validate(url)  # re-validate EVERY hop
        resp = await client.get(url)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            url = urljoin(url, location)
            continue
        return resp
    return None


async def crawl_url(start_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> list[ParseResult]:
    resolve_and_validate(start_url)  # fail fast on the seed (raises SSRFBlocked)

    max_depth = TenantDefaults.CRAWL_MAX_DEPTH
    max_pages = TenantDefaults.CRAWL_MAX_PAGES
    max_bytes = TenantDefaults.CRAWL_MAX_BYTES_PER_PAGE
    timeout = TenantDefaults.CRAWL_FETCH_TIMEOUT_SECONDS

    parts = urlsplit(start_url)
    robots = RobotFileParser()
    segments: list[ParseResult] = []
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(start_url, 0)]

    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout, transport=transport,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        try:
            robots_resp = await client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
            robots.parse(robots_resp.text.splitlines() if robots_resp.status_code == 200 else [])
        except (httpx.HTTPError, SSRFBlocked):
            robots.parse([])  # unreachable robots -> permissive (POC)

        while queue and len(segments) < max_pages:
            url, depth = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not robots.can_fetch(_USER_AGENT, url):
                continue
            try:
                resp = await _fetch(client, url)
            except (SSRFBlocked, httpx.HTTPError):
                continue  # skip a page that blocks/redirects into an internal host or errors
            if resp is None or resp.status_code in (401, 403) or resp.status_code >= 400:
                continue  # auth-gated / error
            if "html" not in resp.headers.get("content-type", ""):
                continue
            body = resp.content[:max_bytes]
            text = _extract_text(body)
            if text.strip():
                segments.append(ParseResult(text=text, source_url=url))
            if depth < max_depth:
                queue.extend((link, depth + 1) for link in _links(start_url, url, body) if link not in seen)

    return segments
