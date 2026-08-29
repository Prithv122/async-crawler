"""Async web crawler and link checker."""

from async_crawler.crawler import Crawler, CrawlReport
from async_crawler.fetcher import AsyncFetcher, FetchResult
from async_crawler.links import extract_links
from async_crawler.ratelimit import RateLimiter
from async_crawler.retry import RetryPolicy
from async_crawler.robots import RobotsCache

__version__ = "0.1.0"
__all__ = [
    "AsyncFetcher",
    "CrawlReport",
    "Crawler",
    "FetchResult",
    "RateLimiter",
    "RetryPolicy",
    "RobotsCache",
    "extract_links",
]
