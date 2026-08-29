"""Tests for RateLimiter. Uses a fake clock/sleep so timing assertions are
exact and the suite doesn't burn wall-clock time waiting.
"""

from __future__ import annotations

import asyncio

import pytest

from async_crawler.ratelimit import RateLimiter


class _FakeClock:
    """A controllable monotonic clock paired with a sleep() that advances it
    instantly instead of actually waiting.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


async def test_first_request_to_a_host_never_waits() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(min_interval=1.0, time_func=clock.time, sleep_func=clock.sleep)

    await limiter.wait("https://example.com/a")

    assert clock.sleeps == []


async def test_second_request_within_interval_waits_the_remainder() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(min_interval=1.0, time_func=clock.time, sleep_func=clock.sleep)

    await limiter.wait("https://example.com/a")
    clock.now += 0.4  # only 0.4s elapsed since the last request
    await limiter.wait("https://example.com/b")

    assert clock.sleeps == [pytest.approx(0.6)]


async def test_no_wait_once_enough_time_has_already_passed() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(min_interval=1.0, time_func=clock.time, sleep_func=clock.sleep)

    await limiter.wait("https://example.com/a")
    clock.now += 2.0  # plenty of time has passed
    await limiter.wait("https://example.com/b")

    assert clock.sleeps == []


async def test_different_hosts_do_not_wait_on_each_other() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(min_interval=5.0, time_func=clock.time, sleep_func=clock.sleep)

    await limiter.wait("https://a.example.com/")
    await limiter.wait("https://b.example.com/")

    assert clock.sleeps == []


async def test_min_interval_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        RateLimiter(min_interval=-1.0)


async def test_concurrent_requests_to_same_host_are_serialized() -> None:
    """Two `wait()` calls fired at once for the same host, with no gap
    between them, must still end up min_interval apart in real time — the
    per-host lock must prevent both from reading "no last request yet"
    simultaneously and skipping the wait.
    """
    min_interval = 0.05
    limiter = RateLimiter(min_interval=min_interval)

    start = asyncio.get_running_loop().time()
    await asyncio.gather(
        limiter.wait("https://example.com/"),
        limiter.wait("https://example.com/"),
    )
    elapsed = asyncio.get_running_loop().time() - start

    assert elapsed >= min_interval
