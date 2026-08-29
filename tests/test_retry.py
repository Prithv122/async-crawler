"""Tests for retry policy: which failures are retryable, and backoff math."""

from __future__ import annotations

import pytest

from async_crawler.fetcher import FetchResult
from async_crawler.retry import RetryPolicy, compute_delay, is_retryable


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_server_and_rate_limit_statuses_are_retryable(status_code: int) -> None:
    result = FetchResult(url="https://example.com/", status_code=status_code, elapsed=0.01)
    assert is_retryable(result)


@pytest.mark.parametrize("status_code", [200, 301, 404, 403, 410])
def test_success_and_client_error_statuses_are_not_retryable(status_code: int) -> None:
    result = FetchResult(url="https://example.com/", status_code=status_code, elapsed=0.01)
    assert not is_retryable(result)


def test_timeout_error_is_retryable() -> None:
    result = FetchResult(
        url="https://example.com/",
        status_code=None,
        elapsed=10.0,
        error="ReadTimeout: timed out",
    )
    assert is_retryable(result)


def test_connect_error_is_retryable() -> None:
    result = FetchResult(
        url="https://example.com/",
        status_code=None,
        elapsed=0.01,
        error="ConnectError: connection refused",
    )
    assert is_retryable(result)


def test_connect_timeout_error_is_retryable() -> None:
    result = FetchResult(
        url="https://example.com/",
        status_code=None,
        elapsed=0.01,
        error="ConnectTimeout: name resolution failed",
    )
    assert is_retryable(result)


def test_unrecognized_error_is_not_retryable() -> None:
    result = FetchResult(
        url="https://example.com/",
        status_code=None,
        elapsed=0.01,
        error="ValueError: malformed URL",
    )
    assert not is_retryable(result)


def test_compute_delay_grows_exponentially_before_jitter() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.0)

    assert compute_delay(0, policy) == pytest.approx(1.0)
    assert compute_delay(1, policy) == pytest.approx(2.0)
    assert compute_delay(2, policy) == pytest.approx(4.0)


def test_compute_delay_is_capped_at_max_delay() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=5.0, jitter=0.0)

    assert compute_delay(10, policy) == pytest.approx(5.0)


def test_compute_delay_jitter_stays_within_bounds_and_non_negative() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=0.5)

    for attempt in range(5):
        delay = compute_delay(attempt, policy)
        base = min(policy.base_delay * (2**attempt), policy.max_delay)
        assert 0.0 <= delay <= base * 1.5
