"""Extract <a href> links from an HTML page, resolved to absolute URLs.

Uses stdlib html.parser rather than a third-party HTML library — a link
checker only needs href attribute values, not a DOM.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit


class _AnchorHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def extract_links(html: str, base_url: str) -> list[str]:
    """Resolve every `<a href>` in `html` to an absolute URL relative to
    `base_url`, in document order with duplicates removed. Fragment-only
    links, empty hrefs, and non-http(s) schemes (mailto:, tel:,
    javascript:) are dropped — none of them are fetchable pages.
    """
    parser = _AnchorHrefParser()
    parser.feed(html)

    links: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        if not absolute or absolute in seen:
            continue
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        seen.add(absolute)
        links.append(absolute)
    return links
