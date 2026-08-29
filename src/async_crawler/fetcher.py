"""Core async HTTP fetcher with bounded concurrency."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from types import TracebackType

import httpx

from async_crawler.ratelimit import RateLimiter
from async_crawler.retry import RetryPolicy, compute_delay, is_retryable


@dataclass(slots=True)
class FetchResult:
    """Outcome of fetching a single URL. `error` is set instead of raising."""

    url: str
    status_code: int | None
    elapsed: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and self.status_code < 400


class AsyncFetcher:
    """Fetches URLs concurrently, bounded by a semaphore so a crawl never opens
    more than `max_concurrency` requests at once regardless of how many URLs
    are queued.
    """

    def __init__(
        self,
        max_concurrency: int = 10,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._rate_limiter = rate_limiter
        self._retry_policy = retry_policy

    async def __aenter__(self) -> AsyncFetcher:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        if self._client is None:
            raise RuntimeError("AsyncFetcher must be used as an async context manager")

        attempt = 0
        while True:
            async with self._semaphore:
                if self._rate_limiter is not None:
                    await self._rate_limiter.wait(url)
                result = await self._request_once(url)

            if (
                self._retry_policy is None
                or attempt >= self._retry_policy.max_retries
                or not is_retryable(result)
            ):
                return result

            # Sleep outside the semaphore so a backing-off request doesn't
            # hold a concurrency slot idle while other URLs are ready to go.
            await asyncio.sleep(compute_delay(attempt, self._retry_policy))
            attempt += 1

    async def _request_once(self, url: str) -> FetchResult:
        assert self._client is not None
        start = time.monotonic()
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            return FetchResult(
                url=url,
                status_code=None,
                elapsed=time.monotonic() - start,
                error=f"{type(exc).__name__}: {exc}",
            )
        return FetchResult(
            url=url,
            status_code=response.status_code,
            elapsed=time.monotonic() - start,
        )

    async def fetch_many(self, urls: Iterable[str]) -> list[FetchResult]:
        return await asyncio.gather(*(self.fetch(url) for url in urls))
