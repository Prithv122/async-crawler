"""Tests for Crawler: BFS over same-domain pages, checking every discovered
link (internal + external) without recursing into external sites. All HTTP
is mocked — no real network calls.
"""

from __future__ import annotations

import httpx
import pytest

from async_crawler.crawler import Crawler
from async_crawler.fetcher import AsyncFetcher
from async_crawler.robots import RobotsCache

_SEED_HTML = """
<a href="/about">About</a>
<a href="/broken">Broken</a>
<a href="/private/secret">Private</a>
<a href="https://external.com/page">External</a>
"""

_ABOUT_HTML = """
<a href="/contact">Contact</a>
<a href="/">Home (cycle back to seed)</a>
"""

_CONTACT_HTML = "<p>No outgoing links here.</p>"

_EXTERNAL_HTML = '<a href="/should-not-be-followed">Not followed</a>'

_ROBOTS_TXT = "User-agent: *\nDisallow: /private/\n"

_PAGES: dict[str, tuple[int, str, str]] = {
    "https://example.com/": (200, "text/html", _SEED_HTML),
    "https://example.com/about": (200, "text/html", _ABOUT_HTML),
    "https://example.com/contact": (200, "text/html", _CONTACT_HTML),
    "https://example.com/broken": (404, "text/plain", "not found"),
    "https://example.com/robots.txt": (200, "text/plain", _ROBOTS_TXT),
    "https://external.com/page": (200, "text/html", _EXTERNAL_HTML),
}


class _FixtureTransport(httpx.AsyncBaseTransport):
    """Serves a small canned site graph and records every URL requested."""

    def __init__(self, pages: dict[str, tuple[int, str, str]]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        if url in self.pages:
            status, content_type, body = self.pages[url]
            return httpx.Response(
                status, headers={"content-type": content_type}, text=body, request=request
            )
        return httpx.Response(404, text="not found", request=request)


def _build(pages: dict[str, tuple[int, str, str]] = _PAGES):
    transport = _FixtureTransport(pages)
    client = httpx.AsyncClient(transport=transport)
    return client, transport


async def test_crawl_follows_internal_links_and_checks_external() -> None:
    client, _transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        report = await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    # seed, /about, /contact, /broken — pages_crawled counts every
    # same-domain URL actually fetched, including ones that 404.
    assert report.pages_crawled == 4
    checked_urls = set(report.links_checked)
    assert checked_urls == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/broken",
        "https://external.com/page",
    }
    assert "https://example.com/private/secret" in report.skipped_by_robots


async def test_crawl_reports_broken_links() -> None:
    client, _transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        report = await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    assert set(report.broken_links) == {"https://example.com/broken"}
    assert report.broken_links["https://example.com/broken"].status_code == 404


async def test_crawl_does_not_recurse_into_external_pages() -> None:
    client, transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    assert "https://external.com/should-not-be-followed" not in transport.requested


async def test_crawl_respects_robots_txt_disallow() -> None:
    client, transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    assert "https://example.com/private/secret" not in transport.requested


async def test_crawl_without_robots_cache_checks_disallowed_paths_too() -> None:
    client, _transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        report = await Crawler(fetcher, robots=None).crawl("https://example.com/")

    assert report.skipped_by_robots == []
    assert "https://example.com/private/secret" in report.links_checked


async def test_crawl_avoids_refetching_a_page_reached_by_a_cycle() -> None:
    client, transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    seed_requests = [u for u in transport.requested if u == "https://example.com/"]
    assert len(seed_requests) == 1


async def test_max_pages_stops_the_crawl_and_leaves_its_links_unchecked() -> None:
    client, _transport = _build()
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        report = await Crawler(fetcher, robots=robots, max_pages=1).crawl("https://example.com/")

    assert report.pages_crawled == 1
    assert set(report.links_checked) == {"https://example.com/"}


async def test_crawl_stops_cleanly_when_seed_itself_is_disallowed() -> None:
    pages = dict(_PAGES)
    pages["https://example.com/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /\n")
    client, transport = _build(pages)
    async with client, AsyncFetcher(client=client) as fetcher:
        robots = RobotsCache(client)
        report = await Crawler(fetcher, robots=robots).crawl("https://example.com/")

    assert report.pages_crawled == 0
    assert report.links_checked == {}
    assert report.skipped_by_robots == ["https://example.com/"]
    assert transport.requested == ["https://example.com/robots.txt"]


def test_max_pages_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Crawler(AsyncFetcher(), max_pages=0)
