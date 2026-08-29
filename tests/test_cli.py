"""Tests for the CLI: argument parsing, report rendering, exit codes, and
end-to-end wiring against a mocked HTTP transport (no real network).
"""

from __future__ import annotations

import json

import httpx
import pytest

from async_crawler import cli
from async_crawler.crawler import CrawlReport
from async_crawler.fetcher import AsyncFetcher, FetchResult


def test_build_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["https://example.com/"])

    assert args.url == "https://example.com/"
    assert args.max_pages == 50
    assert args.max_concurrency == 10
    assert args.rate_limit == pytest.approx(1.0)
    assert args.timeout == pytest.approx(10.0)
    assert args.max_retries == 3
    assert args.ignore_robots is False
    assert args.json is False


def test_build_parser_overrides() -> None:
    args = cli.build_parser().parse_args(
        [
            "https://example.com/",
            "--max-pages",
            "5",
            "--max-concurrency",
            "2",
            "--rate-limit",
            "0.1",
            "--timeout",
            "3.0",
            "--max-retries",
            "0",
            "--user-agent",
            "test-bot",
            "--ignore-robots",
            "--json",
        ]
    )

    assert args.max_pages == 5
    assert args.max_concurrency == 2
    assert args.rate_limit == pytest.approx(0.1)
    assert args.timeout == pytest.approx(3.0)
    assert args.max_retries == 0
    assert args.user_agent == "test-bot"
    assert args.ignore_robots is True
    assert args.json is True


def _make_report(broken: bool) -> CrawlReport:
    checked = {
        "https://example.com/": FetchResult(
            url="https://example.com/", status_code=200, elapsed=0.01
        )
    }
    if broken:
        checked["https://example.com/dead"] = FetchResult(
            url="https://example.com/dead", status_code=404, elapsed=0.02
        )
    return CrawlReport(seed_url="https://example.com/", pages_crawled=1, links_checked=checked)


def test_main_exits_zero_when_nothing_broken(monkeypatch, capsys) -> None:
    async def fake_run_crawl(args):
        return _make_report(broken=False)

    monkeypatch.setattr(cli, "run_crawl", fake_run_crawl)

    exit_code = cli.main(["https://example.com/"])

    assert exit_code == 0
    assert "Broken links:      0" in capsys.readouterr().out


def test_main_exits_nonzero_when_links_are_broken(monkeypatch, capsys) -> None:
    async def fake_run_crawl(args):
        return _make_report(broken=True)

    monkeypatch.setattr(cli, "run_crawl", fake_run_crawl)

    exit_code = cli.main(["https://example.com/"])

    assert exit_code == 1
    assert "[404] https://example.com/dead" in capsys.readouterr().out


def test_main_json_output_is_valid_and_matches_report(monkeypatch, capsys) -> None:
    async def fake_run_crawl(args):
        return _make_report(broken=True)

    monkeypatch.setattr(cli, "run_crawl", fake_run_crawl)

    exit_code = cli.main(["https://example.com/", "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["seed_url"] == "https://example.com/"
    assert payload["pages_crawled"] == 1
    assert len(payload["broken_links"]) == 1
    assert payload["broken_links"][0]["status_code"] == 404


class _RobotsAwareTransport(httpx.AsyncBaseTransport):
    """Serves a real robots.txt (disallow everything) and a trivial HTML
    page for everything else — enough to test the CLI's actual wiring
    without hitting the network.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="User-agent: *\nDisallow: /\n",
                request=request,
            )
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text="<p>hi</p>", request=request
        )


def _patch_fetcher_to_use_transport(monkeypatch, client: httpx.AsyncClient) -> None:
    def factory(**kwargs):
        kwargs["client"] = client
        return AsyncFetcher(**kwargs)

    monkeypatch.setattr(cli, "AsyncFetcher", factory)


async def test_run_crawl_wires_fetcher_robots_and_crawler_together(monkeypatch) -> None:
    async with httpx.AsyncClient(transport=_RobotsAwareTransport()) as client:
        _patch_fetcher_to_use_transport(monkeypatch, client)

        args = cli.build_parser().parse_args(["https://example.com/", "--rate-limit", "0"])
        report = await cli.run_crawl(args)

    # robots.txt disallows everything, and it's honored by default.
    assert report.pages_crawled == 0
    assert report.skipped_by_robots == ["https://example.com/"]


async def test_ignore_robots_flag_bypasses_robots_txt(monkeypatch) -> None:
    async with httpx.AsyncClient(transport=_RobotsAwareTransport()) as client:
        _patch_fetcher_to_use_transport(monkeypatch, client)

        args = cli.build_parser().parse_args(
            ["https://example.com/", "--rate-limit", "0", "--ignore-robots"]
        )
        report = await cli.run_crawl(args)

    assert report.pages_crawled == 1
    assert report.skipped_by_robots == []
