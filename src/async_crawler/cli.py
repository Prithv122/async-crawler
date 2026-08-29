"""Command-line entry point: crawl a site, print a summary report.

Exits 0 if every checked link was fine, 1 if any were broken — so this can
be dropped straight into a CI job as a link-checking gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence

from async_crawler.crawler import Crawler, CrawlReport
from async_crawler.fetcher import AsyncFetcher
from async_crawler.ratelimit import RateLimiter
from async_crawler.report import format_report, report_to_dict
from async_crawler.retry import RetryPolicy
from async_crawler.robots import RobotsCache

DEFAULT_USER_AGENT = "async-crawler/0.1 (+https://github.com/Prithv122/async-crawler)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="async-crawler",
        description="Crawl a site and check every discovered link (internal + external).",
    )
    parser.add_argument("url", help="Seed URL to start crawling from")
    parser.add_argument(
        "--max-pages", type=int, default=50, help="max same-domain pages to crawl (default: 50)"
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=10,
        help="max in-flight requests at once (default: 10)",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="min seconds between requests to the same host (default: 1.0)",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="per-request timeout in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="retries for 429/5xx/timeouts, exponential backoff (default: 3)",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header sent, and the product token matched against robots.txt",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="skip robots.txt checks entirely (off by default - opt in explicitly)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the report as JSON instead of plain text"
    )
    return parser


async def run_crawl(args: argparse.Namespace) -> CrawlReport:
    rate_limiter = RateLimiter(min_interval=args.rate_limit)
    retry_policy = RetryPolicy(max_retries=args.max_retries)

    async with AsyncFetcher(
        max_concurrency=args.max_concurrency,
        timeout=args.timeout,
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        user_agent=args.user_agent,
    ) as fetcher:
        robots = None if args.ignore_robots else RobotsCache(fetcher.client, args.user_agent)
        crawler = Crawler(fetcher, robots=robots, max_pages=args.max_pages)
        return await crawler.crawl(args.url)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    start = time.monotonic()
    report = asyncio.run(run_crawl(args))
    elapsed = time.monotonic() - start

    if args.json:
        print(json.dumps(report_to_dict(report, elapsed), indent=2))
    else:
        print(format_report(report, elapsed))

    return 1 if report.broken_links else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
