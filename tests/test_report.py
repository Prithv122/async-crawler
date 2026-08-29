"""Tests for report formatting/serialization."""

from __future__ import annotations

from async_crawler.crawler import CrawlReport
from async_crawler.fetcher import FetchResult
from async_crawler.report import format_report, report_to_dict


def _clean_report() -> CrawlReport:
    checked = {
        "https://example.com/": FetchResult(
            url="https://example.com/", status_code=200, elapsed=0.05
        )
    }
    return CrawlReport(seed_url="https://example.com/", pages_crawled=1, links_checked=checked)


def _broken_report() -> CrawlReport:
    checked = {
        "https://example.com/": FetchResult(
            url="https://example.com/", status_code=200, elapsed=0.05
        ),
        "https://example.com/dead": FetchResult(
            url="https://example.com/dead", status_code=404, elapsed=0.02
        ),
    }
    return CrawlReport(
        seed_url="https://example.com/",
        pages_crawled=1,
        links_checked=checked,
        skipped_by_robots=["https://example.com/private"],
    )


def test_format_report_summary_counts() -> None:
    text = format_report(_clean_report(), elapsed=1.234)

    assert "Crawled: https://example.com/" in text
    assert "Pages crawled:     1" in text
    assert "Links checked:     1" in text
    assert "Broken links:      0" in text
    assert "Skipped (robots):  0" in text
    assert "Elapsed:           1.23s" in text
    assert "Broken links:\n" not in text  # no detail section when nothing's broken


def test_format_report_lists_broken_links_with_status() -> None:
    text = format_report(_broken_report(), elapsed=0.5)

    assert "Broken links:      1" in text
    assert "Skipped (robots):  1" in text
    assert "Broken links:\n  [404] https://example.com/dead" in text


def test_format_report_shows_error_instead_of_status_for_connection_failures() -> None:
    checked = {
        "https://example.com/": FetchResult(
            url="https://example.com/",
            status_code=None,
            elapsed=1.0,
            error="ConnectError: refused",
        )
    }
    report = CrawlReport(seed_url="https://example.com/", pages_crawled=1, links_checked=checked)

    text = format_report(report, elapsed=1.0)

    assert "[ERROR] https://example.com/ - ConnectError: refused" in text


def test_report_to_dict_matches_summary_fields() -> None:
    payload = report_to_dict(_broken_report(), elapsed=0.3)

    assert payload["seed_url"] == "https://example.com/"
    assert payload["pages_crawled"] == 1
    assert payload["links_checked"] == 2
    assert payload["skipped_by_robots"] == ["https://example.com/private"]
    assert payload["elapsed_seconds"] == 0.3
    assert len(payload["broken_links"]) == 1


def test_report_to_dict_broken_link_entries_omit_body_and_include_ok_flag() -> None:
    checked = {
        "https://example.com/dead": FetchResult(
            url="https://example.com/dead",
            status_code=500,
            elapsed=0.2,
            content_type="text/html",
            text="<html>a whole error page nobody needs in a report</html>",
        )
    }
    report = CrawlReport(seed_url="https://example.com/", pages_crawled=1, links_checked=checked)

    payload = report_to_dict(report, elapsed=0.2)

    link = payload["broken_links"][0]
    assert link["status_code"] == 500
    assert link["ok"] is False
    assert "text" not in link


def test_report_to_dict_is_json_serializable() -> None:
    import json

    json.dumps(report_to_dict(_broken_report(), elapsed=0.1))
