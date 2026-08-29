"""Retry policy for transient HTTP failures: exponential backoff with jitter."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Import only for type checking: fetcher.py imports this module, so a
    # runtime import here would be circular.
    from async_crawler.fetcher import FetchResult

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_ERROR_MARKERS = (
    "Timeout",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "PoolTimeout",
    "NetworkError",
)


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """`max_retries` counts attempts *after* the first try — 0 means never retry."""

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.2  # +/- this fraction of the computed delay


def is_retryable(result: FetchResult) -> bool:
    """429/5xx (server said "try again") and connection/timeout errors are
    retried. 4xx client errors (404, 403, ...) are not — retrying a broken
    link doesn't fix it.
    """
    if result.status_code in _RETRYABLE_STATUS_CODES:
        return True
    if result.error is not None:
        return any(marker in result.error for marker in _RETRYABLE_ERROR_MARKERS)
    return False


def compute_delay(attempt: int, policy: RetryPolicy) -> float:
    """`attempt` is 0-indexed: 0 = the delay before the first retry."""
    delay = min(policy.base_delay * (2**attempt), policy.max_delay)
    jitter_amount = delay * policy.jitter
    return max(0.0, delay + random.uniform(-jitter_amount, jitter_amount))
