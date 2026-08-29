"""robots.txt compliance: one parser per host, fetched once and cached."""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlsplit, urlunsplit

import httpx


class RobotsCache:
    """Fetches robots.txt per host on first use, caches the parsed result,
    and answers can_fetch() for subsequent URLs on that host without
    re-fetching.

    Fetching is deliberately decoupled from parsing: `RobotFileParser.read()`
    does a blocking `urlopen()`, which would stall the event loop, so this
    fetches through the shared async httpx client and hands the body to
    `parse()` instead.
    """

    def __init__(self, client: httpx.AsyncClient, user_agent: str = "async-crawler") -> None:
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    @staticmethod
    def _host_key(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc.lower(), "", "", ""))

    async def _get_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        host = self._host_key(url)
        if host in self._parsers:
            return self._parsers[host]

        parser = urllib.robotparser.RobotFileParser()

        try:
            response = await self._client.get(f"{host}/robots.txt")
        except httpx.HTTPError:
            # Unreachable for an unknown reason (network/server issue): fail
            # closed rather than assume the site permits everything.
            parser.disallow_all = True
        else:
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            elif response.status_code in (401, 403):
                # Per RFC 9309 / common crawler convention: an access-denied
                # robots.txt means "assume full disallow", not "no robots.txt".
                parser.disallow_all = True
            elif 400 <= response.status_code < 500:
                pass  # confirmed absent (e.g. 404): no restrictions apply
            else:
                # 5xx: robots.txt exists but is temporarily unreachable —
                # fail closed rather than crawl a site that may be trying
                # to tell us not to.
                parser.disallow_all = True

        # can_fetch() refuses every URL until the parser has been marked as
        # checked (it's a guard against querying before a real read/parse
        # happened) — parse() alone doesn't set this, only read() does.
        parser.modified()

        self._parsers[host] = parser
        return parser

    async def can_fetch(self, url: str) -> bool:
        parser = await self._get_parser(url)
        return parser.can_fetch(self._user_agent, url)
