"""Async web crawler and link checker."""

from async_crawler.fetcher import AsyncFetcher, FetchResult
from async_crawler.robots import RobotsCache

__version__ = "0.1.0"
__all__ = ["AsyncFetcher", "FetchResult", "RobotsCache"]
