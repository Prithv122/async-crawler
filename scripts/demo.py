"""Runs the crawler against a small local fixture site and prints real,
reproducible numbers for the README: correctness (broken links found,
robots.txt respected, a flaky endpoint retried and eventually succeeding)
and a concurrency benchmark (same site, --max-concurrency 1 vs the default).

Everything here is served locally - no real network traffic, no dependence
on any external site staying up or reachable.
"""

from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from async_crawler.crawler import Crawler
from async_crawler.fetcher import AsyncFetcher
from async_crawler.ratelimit import RateLimiter
from async_crawler.report import format_report
from async_crawler.retry import RetryPolicy
from async_crawler.robots import RobotsCache

NUM_EXTERNAL_LEAVES = 20
EXTERNAL_LEAF_DELAY = 0.15  # seconds, simulates real-world network latency

_flaky_lock = threading.Lock()
_flaky_request_count = 0


def _external_leaf_links(external_origin: str) -> str:
    return "\n".join(
        f'<a href="{external_origin}/leaf-{i}">leaf {i}</a>' for i in range(NUM_EXTERNAL_LEAVES)
    )


class MainSiteHandler(BaseHTTPRequestHandler):
    external_origin = ""  # set by make_main_server before the server starts

    def log_message(self, log_format: str, *args: object) -> None:
        pass  # keep demo output focused on the crawl report, not access logs

    def _send(self, status: int, content_type: str, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        global _flaky_request_count

        if self.path == "/robots.txt":
            self._send(200, "text/plain", "User-agent: *\nDisallow: /private/\n")
        elif self.path == "/":
            links = _external_leaf_links(self.external_origin)
            self._send(
                200,
                "text/html",
                f"""<html><body>
                <a href="/about">About</a>
                <a href="/contact">Contact</a>
                <a href="/broken">Broken link (expect 404)</a>
                <a href="/flaky">Flaky endpoint (expect retry)</a>
                <a href="/private/secret">Private (expect robots skip)</a>
                {links}
                </body></html>""",
            )
        elif self.path == "/about":
            self._send(200, "text/html", '<html><body><a href="/contact">Contact</a></body></html>')
        elif self.path == "/contact":
            self._send(200, "text/html", "<html><body>No outgoing links.</body></html>")
        elif self.path == "/flaky":
            with _flaky_lock:
                _flaky_request_count += 1
                count = _flaky_request_count
            if count <= 2:
                self._send(503, "text/plain", "Service Unavailable (temporary, by design)")
            else:
                self._send(200, "text/html", "<html><body>Recovered after retries.</body></html>")
        elif self.path.startswith("/leaf-"):
            time.sleep(EXTERNAL_LEAF_DELAY)
            self._send(200, "text/html", "<html><body>External leaf page.</body></html>")
        else:
            self._send(404, "text/plain", "Not Found")


class ExternalSiteHandler(BaseHTTPRequestHandler):
    def log_message(self, log_format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        time.sleep(EXTERNAL_LEAF_DELAY)
        body = "<html><body>External leaf page (never crawled further).</body></html>"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _start_server(handler_cls: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def run_crawl(seed_url: str, max_concurrency: int) -> tuple[float, object]:
    async with AsyncFetcher(
        max_concurrency=max_concurrency,
        rate_limiter=RateLimiter(min_interval=0.0),
        retry_policy=RetryPolicy(max_retries=3, base_delay=0.05, max_delay=0.2),
        user_agent="async-crawler-demo/1.0",
    ) as fetcher:
        robots = RobotsCache(fetcher.client, user_agent="async-crawler-demo/1.0")
        crawler = Crawler(fetcher, robots=robots, max_pages=10)
        start = time.monotonic()
        report = await crawler.crawl(seed_url)
        elapsed = time.monotonic() - start
        return elapsed, report


def main() -> None:
    global _flaky_request_count

    external_server = _start_server(ExternalSiteHandler)
    external_origin = f"http://127.0.0.1:{external_server.server_address[1]}"

    MainSiteHandler.external_origin = external_origin
    main_server = _start_server(MainSiteHandler)
    seed_url = f"http://127.0.0.1:{main_server.server_address[1]}/"

    print("=" * 70)
    print("PART 1 - correctness: broken links, robots.txt, retry/backoff")
    print("=" * 70)
    elapsed, report = asyncio.run(run_crawl(seed_url, max_concurrency=10))
    print(format_report(report, elapsed))
    print(f"\n/flaky was requested {_flaky_request_count} times by the server's own count")
    print("(2 failures + 1 success = the retry policy's backoff actually ran, not just")
    print(" the happy path).")

    print()
    print("=" * 70)
    print("PART 2 - concurrency benchmark: same site, max_concurrency 1 vs 10")
    print(
        f"({NUM_EXTERNAL_LEAVES} external links, each with a simulated "
        f"{EXTERNAL_LEAF_DELAY * 1000:.0f}ms network delay)"
    )
    print("=" * 70)

    _flaky_request_count = 0
    elapsed_serial, _ = asyncio.run(run_crawl(seed_url, max_concurrency=1))
    _flaky_request_count = 0
    elapsed_concurrent, _ = asyncio.run(run_crawl(seed_url, max_concurrency=10))

    speedup = elapsed_serial / elapsed_concurrent
    print(f"max_concurrency=1:  {elapsed_serial:.2f}s")
    print(f"max_concurrency=10: {elapsed_concurrent:.2f}s")
    print(f"speedup: {speedup:.1f}x")

    external_server.shutdown()
    main_server.shutdown()


if __name__ == "__main__":
    main()
