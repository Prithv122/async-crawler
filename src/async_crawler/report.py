"""Format a CrawlReport as human-readable text or as a JSON-serializable dict."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from async_crawler.crawler import CrawlReport
from async_crawler.fetcher import FetchResult


def _link_summary(result: FetchResult) -> dict[str, Any]:
    data = asdict(result)
    data.pop("text", None)  # HTML bodies aren't meaningful in a report
    data["ok"] = result.ok
    return data


def report_to_dict(report: CrawlReport, elapsed: float) -> dict[str, Any]:
    return {
        "seed_url": report.seed_url,
        "pages_crawled": report.pages_crawled,
        "links_checked": len(report.links_checked),
        "broken_links": [_link_summary(result) for result in report.broken_links.values()],
        "skipped_by_robots": list(report.skipped_by_robots),
        "elapsed_seconds": round(elapsed, 3),
    }


def format_report(report: CrawlReport, elapsed: float) -> str:
    broken = report.broken_links
    lines = [
        f"Crawled: {report.seed_url}",
        f"  Pages crawled:     {report.pages_crawled}",
        f"  Links checked:     {len(report.links_checked)}",
        f"  Broken links:      {len(broken)}",
        f"  Skipped (robots):  {len(report.skipped_by_robots)}",
        f"  Elapsed:           {elapsed:.2f}s",
    ]
    if broken:
        lines.append("")
        lines.append("Broken links:")
        for url, result in sorted(broken.items()):
            status = result.status_code if result.status_code is not None else "ERROR"
            detail = f" - {result.error}" if result.error else ""
            lines.append(f"  [{status}] {url}{detail}")
    return "\n".join(lines)
