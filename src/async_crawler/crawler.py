"""Top-level crawl orchestration: breadth-first over same-domain pages,
checking the status of every discovered link — internal and external —
along the way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urldefrag, urlsplit

from async_crawler.fetcher import AsyncFetcher, FetchResult
from async_crawler.links import extract_links
from async_crawler.robots import RobotsCache


@dataclass(slots=True)
class CrawlReport:
    seed_url: str
    pages_crawled: int
    links_checked: dict[str, FetchResult]
    skipped_by_robots: list[str] = field(default_factory=list)

    @property
    def broken_links(self) -> dict[str, FetchResult]:
        return {url: result for url, result in self.links_checked.items() if not result.ok}


def _normalize(url: str) -> str:
    """Dedup key for a URL: the fragment doesn't change what gets fetched."""
    without_fragment, _fragment = urldefrag(url)
    return without_fragment


class Crawler:
    """Crawls same-domain pages breadth-first, fetching one level (batch) at
    a time so requests within a level run concurrently under the fetcher's
    own bounds. Links to other domains are checked (fetched once, status
    recorded) but never followed further — only pages on the seed's domain
    are parsed for more links.

    `max_pages` caps how many same-domain pages get crawled. It's a safety
    limit, not a completeness guarantee: once it's reached the crawl stops
    immediately, so links discovered on the last processed page (and not
    yet fetched) are simply never checked.
    """

    def __init__(
        self,
        fetcher: AsyncFetcher,
        robots: RobotsCache | None = None,
        max_pages: int = 50,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        self._fetcher = fetcher
        self._robots = robots
        self.max_pages = max_pages

    async def crawl(self, seed_url: str) -> CrawlReport:
        origin = urlsplit(seed_url).netloc.lower()
        seen: set[str] = {_normalize(seed_url)}
        checked: dict[str, FetchResult] = {}
        skipped: list[str] = []
        pages_crawled = 0

        frontier = [seed_url]
        while frontier:
            allowed = []
            for url in frontier:
                if self._robots is not None and not await self._robots.can_fetch(url):
                    skipped.append(url)
                    continue
                allowed.append(url)

            if not allowed:
                break

            results = await self._fetcher.fetch_many(allowed)
            next_frontier: list[str] = []

            for url, result in zip(allowed, results, strict=True):
                checked[_normalize(url)] = result
                is_internal = urlsplit(url).netloc.lower() == origin
                if is_internal:
                    pages_crawled += 1

                should_recurse = (
                    is_internal and result.ok and result.is_html and pages_crawled <= self.max_pages
                )
                if not should_recurse:
                    continue

                for link in extract_links(result.text or "", base_url=url):
                    key = _normalize(link)
                    if key in seen:
                        continue
                    seen.add(key)
                    next_frontier.append(link)

            if pages_crawled >= self.max_pages:
                break

            frontier = next_frontier

        return CrawlReport(
            seed_url=seed_url,
            pages_crawled=pages_crawled,
            links_checked=checked,
            skipped_by_robots=skipped,
        )
