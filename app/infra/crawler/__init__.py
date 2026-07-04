"""URL crawler for KB ingestion. Produces one ``ParseResult`` per crawled page (text +
source_url). Security-critical: every fetch (and every redirect hop) is SSRF-revalidated."""

from app.infra.crawler.crawl import crawl_url

__all__ = ["crawl_url"]
