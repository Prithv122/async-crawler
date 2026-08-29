"""Tests for RobotsCache. All HTTP is mocked — no real network calls."""

from __future__ import annotations

import httpx
import pytest

from async_crawler.robots import RobotsCache

# stdlib RobotFileParser matches rules in file order (first match wins), not
# by longest-path-wins like Google's spec — the Allow must precede the
# broader Disallow it's meant to override.
_ROBOTS_TXT = """
User-agent: *
Allow: /private/public-page
Disallow: /private/

User-agent: nosy-bot
Disallow: /
"""


class _RobotsTransport(httpx.AsyncBaseTransport):
    """Serves canned robots.txt responses keyed by host, and counts how many
    times each robots.txt URL was actually requested (to verify caching).
    """

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.responses = responses
        self.request_count: dict[str, int] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.request_count[url] = self.request_count.get(url, 0) + 1
        if url in self.responses:
            return self.responses[url]
        return httpx.Response(200, text="", request=request)


class _RaisingTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)


def _client(responses: dict[str, httpx.Response]) -> tuple[httpx.AsyncClient, _RobotsTransport]:
    transport = _RobotsTransport(responses)
    return httpx.AsyncClient(transport=transport), transport


async def test_disallowed_path_is_blocked() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(200, text=_ROBOTS_TXT)})
    async with client:
        cache = RobotsCache(client, user_agent="async-crawler")
        assert not await cache.can_fetch("https://example.com/private/secret")


async def test_allowed_path_is_permitted() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(200, text=_ROBOTS_TXT)})
    async with client:
        cache = RobotsCache(client, user_agent="async-crawler")
        assert await cache.can_fetch("https://example.com/about")


async def test_more_specific_allow_overrides_disallow() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(200, text=_ROBOTS_TXT)})
    async with client:
        cache = RobotsCache(client, user_agent="async-crawler")
        assert await cache.can_fetch("https://example.com/private/public-page")


async def test_rule_only_applies_to_its_named_user_agent() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(200, text=_ROBOTS_TXT)})
    async with client:
        blocked_agent = RobotsCache(client, user_agent="nosy-bot")
        our_agent = RobotsCache(client, user_agent="async-crawler")
        assert not await blocked_agent.can_fetch("https://example.com/about")
        assert await our_agent.can_fetch("https://example.com/about")


async def test_missing_robots_txt_allows_everything() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(404, text="not found")})
    async with client:
        cache = RobotsCache(client)
        assert await cache.can_fetch("https://example.com/anything")


@pytest.mark.parametrize("status_code", [401, 403])
async def test_access_denied_robots_txt_disallows_everything(status_code: int) -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(status_code, text="")})
    async with client:
        cache = RobotsCache(client)
        assert not await cache.can_fetch("https://example.com/anything")


async def test_server_error_fails_closed() -> None:
    client, _ = _client({"https://example.com/robots.txt": httpx.Response(500, text="")})
    async with client:
        cache = RobotsCache(client)
        assert not await cache.can_fetch("https://example.com/anything")


async def test_network_error_fails_closed() -> None:
    async with httpx.AsyncClient(transport=_RaisingTransport()) as client:
        cache = RobotsCache(client)
        assert not await cache.can_fetch("https://example.com/anything")


async def test_robots_txt_is_fetched_once_per_host() -> None:
    responses = {"https://example.com/robots.txt": httpx.Response(200, text=_ROBOTS_TXT)}
    client, transport = _client(responses)
    async with client:
        cache = RobotsCache(client)
        await cache.can_fetch("https://example.com/about")
        await cache.can_fetch("https://example.com/other-page")
        await cache.can_fetch("https://example.com/private/secret")

    assert transport.request_count["https://example.com/robots.txt"] == 1


async def test_different_hosts_get_independent_parsers() -> None:
    client, transport = _client(
        {
            "https://allowed.example.com/robots.txt": httpx.Response(404, text=""),
            "https://blocked.example.com/robots.txt": httpx.Response(
                200, text="User-agent: *\nDisallow: /"
            ),
        }
    )
    async with client:
        cache = RobotsCache(client)
        assert await cache.can_fetch("https://allowed.example.com/page")
        assert not await cache.can_fetch("https://blocked.example.com/page")

    assert transport.request_count["https://allowed.example.com/robots.txt"] == 1
    assert transport.request_count["https://blocked.example.com/robots.txt"] == 1
