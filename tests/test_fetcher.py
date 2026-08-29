"""Tests for the core async fetcher. All HTTP is mocked — no real network calls."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from async_crawler.fetcher import AsyncFetcher, FetchResult


class _StatusTransport(httpx.AsyncBaseTransport):
    """Returns a fixed status code for every request."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self.status_code, request=request)


class _RaisingTransport(httpx.AsyncBaseTransport):
    """Simulates a connection failure for every request."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)


class _ConcurrencyTrackingTransport(httpx.AsyncBaseTransport):
    """Records how many requests are in flight at once, to verify the
    fetcher's semaphore actually bounds concurrency rather than just
    accepting a max_concurrency argument it ignores.
    """

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self.delay)
        async with self._lock:
            self.active -= 1
        return httpx.Response(200, request=request)


@pytest.mark.asyncio
async def test_fetch_returns_status_code() -> None:
    transport = _StatusTransport(status_code=200)
    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/")

    expected = FetchResult(url="https://example.com/", status_code=200, elapsed=result.elapsed)
    assert result == expected
    assert result.ok


@pytest.mark.asyncio
async def test_fetch_reports_4xx_as_not_ok() -> None:
    transport = _StatusTransport(status_code=404)
    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/missing")

    assert result.status_code == 404
    assert not result.ok


@pytest.mark.asyncio
async def test_fetch_captures_connection_error_instead_of_raising() -> None:
    transport = _RaisingTransport()
    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/")

    assert result.status_code is None
    assert result.error is not None
    assert "ConnectError" in result.error
    assert not result.ok


@pytest.mark.asyncio
async def test_fetch_many_bounds_concurrency() -> None:
    transport = _ConcurrencyTrackingTransport(delay=0.05)
    urls = [f"https://example.com/{i}" for i in range(20)]

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(max_concurrency=4, client=client) as fetcher,
    ):
        results = await fetcher.fetch_many(urls)

    assert len(results) == 20
    assert all(r.ok for r in results)
    assert transport.max_active <= 4


@pytest.mark.asyncio
async def test_fetch_without_context_manager_raises() -> None:
    fetcher = AsyncFetcher()
    with pytest.raises(RuntimeError):
        await fetcher.fetch("https://example.com/")


def test_max_concurrency_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AsyncFetcher(max_concurrency=0)


@pytest.mark.asyncio
async def test_fetcher_owns_and_closes_its_own_client() -> None:
    async with AsyncFetcher(max_concurrency=2) as fetcher:
        assert fetcher._client is not None
        assert not fetcher._client.is_closed
    assert fetcher._client.is_closed
