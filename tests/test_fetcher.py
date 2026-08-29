"""Tests for the core async fetcher. All HTTP is mocked — no real network calls."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from async_crawler.fetcher import AsyncFetcher, FetchResult
from async_crawler.ratelimit import RateLimiter
from async_crawler.retry import RetryPolicy


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


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Fails with a retryable status the first `fail_times` requests, then
    succeeds. Counts total requests received.
    """

    def __init__(self, fail_times: int, failure_status: int = 503) -> None:
        self.fail_times = fail_times
        self.failure_status = failure_status
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            return httpx.Response(self.failure_status, request=request)
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


def test_client_property_raises_before_entering_context_manager() -> None:
    fetcher = AsyncFetcher()
    with pytest.raises(RuntimeError):
        _ = fetcher.client


@pytest.mark.asyncio
async def test_client_property_exposes_the_underlying_httpx_client() -> None:
    async with AsyncFetcher() as fetcher:
        assert fetcher.client is fetcher._client


@pytest.mark.asyncio
async def test_owned_client_sends_configured_user_agent_header() -> None:
    async with AsyncFetcher(user_agent="test-crawler/1.0") as fetcher:
        assert fetcher.client.headers["User-Agent"] == "test-crawler/1.0"


@pytest.mark.asyncio
async def test_owned_client_falls_back_to_httpx_default_user_agent() -> None:
    async with AsyncFetcher() as fetcher:
        assert "python-httpx" in fetcher.client.headers["User-Agent"]


@pytest.mark.asyncio
async def test_fetch_retries_retryable_failures_then_succeeds() -> None:
    transport = _FlakyTransport(fail_times=2, failure_status=503)
    policy = RetryPolicy(max_retries=3, base_delay=0.001, max_delay=0.01, jitter=0.0)

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client, retry_policy=policy) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/")

    assert result.ok
    assert result.status_code == 200
    assert transport.call_count == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_fetch_gives_up_after_max_retries() -> None:
    transport = _FlakyTransport(fail_times=999, failure_status=500)
    policy = RetryPolicy(max_retries=2, base_delay=0.001, max_delay=0.01, jitter=0.0)

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client, retry_policy=policy) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/")

    assert not result.ok
    assert result.status_code == 500
    assert transport.call_count == 3  # 1 initial try + 2 retries, then give up


@pytest.mark.asyncio
async def test_fetch_without_retry_policy_never_retries() -> None:
    transport = _FlakyTransport(fail_times=999, failure_status=503)

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/")

    assert result.status_code == 503
    assert transport.call_count == 1


@pytest.mark.asyncio
async def test_fetch_does_not_retry_non_retryable_status() -> None:
    transport = _StatusTransport(status_code=404)
    policy = RetryPolicy(max_retries=3, base_delay=0.001)

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client, retry_policy=policy) as fetcher,
    ):
        result = await fetcher.fetch("https://example.com/missing")

    assert result.status_code == 404


@pytest.mark.asyncio
async def test_fetch_consults_rate_limiter_before_each_request() -> None:
    transport = _StatusTransport(status_code=200)
    waited_urls: list[str] = []

    class _RecordingLimiter(RateLimiter):
        async def wait(self, url: str) -> None:
            waited_urls.append(url)

    async with (
        httpx.AsyncClient(transport=transport) as client,
        AsyncFetcher(client=client, rate_limiter=_RecordingLimiter()) as fetcher,
    ):
        await fetcher.fetch("https://example.com/a")
        await fetcher.fetch("https://example.com/b")

    assert waited_urls == ["https://example.com/a", "https://example.com/b"]
