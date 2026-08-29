"""Core async HTTP fetcher with bounded concurrency."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from types import TracebackType

import httpx


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
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

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

        async with self._semaphore:
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
