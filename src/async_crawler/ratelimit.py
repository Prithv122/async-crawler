"""Per-host rate limiting: enforces a minimum interval between requests to
the same host, independent of how many other hosts are being crawled.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

TimeFunc = Callable[[], float]
SleepFunc = Callable[[float], Awaitable[None]]


class RateLimiter:
    """Delays a request just long enough that consecutive requests to the
    same host are at least `min_interval` seconds apart. Different hosts
    never wait on each other.

    `time_func`/`sleep_func` are injectable so tests can assert timing
    behavior with a fake clock instead of burning wall-clock time.
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        time_func: TimeFunc = time.monotonic,
        sleep_func: SleepFunc = asyncio.sleep,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must be >= 0")
        self.min_interval = min_interval
        self._time = time_func
        self._sleep = sleep_func
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def _host_key(url: str) -> str:
        return urlsplit(url).netloc.lower()

    async def wait(self, url: str) -> None:
        host = self._host_key(url)
        async with self._locks[host]:
            last = self._last_request.get(host)
            if last is not None:
                remaining = self.min_interval - (self._time() - last)
                if remaining > 0:
                    await self._sleep(remaining)
            self._last_request[host] = self._time()
