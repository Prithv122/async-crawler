"""Tests for extract_links: HTML anchor parsing and URL resolution."""

from __future__ import annotations

from async_crawler.links import extract_links


def test_extracts_absolute_links() -> None:
    html = '<a href="https://example.com/a">A</a> <a href="https://other.com/b">B</a>'
    links = extract_links(html, base_url="https://example.com/")
    assert links == ["https://example.com/a", "https://other.com/b"]


def test_resolves_relative_links_against_base_url() -> None:
    html = '<a href="/about">About</a> <a href="contact.html">Contact</a>'
    links = extract_links(html, base_url="https://example.com/blog/post")
    assert links == ["https://example.com/about", "https://example.com/blog/contact.html"]


def test_strips_url_fragments() -> None:
    html = '<a href="/page#section-2">Jump</a>'
    links = extract_links(html, base_url="https://example.com/")
    assert links == ["https://example.com/page"]


def test_drops_non_http_schemes() -> None:
    html = """
    <a href="mailto:hello@example.com">Email</a>
    <a href="tel:+15551234">Call</a>
    <a href="javascript:void(0)">Nothing</a>
    <a href="/real-page">Real</a>
    """
    links = extract_links(html, base_url="https://example.com/")
    assert links == ["https://example.com/real-page"]


def test_fragment_only_href_resolves_to_the_current_page() -> None:
    # #top has no path of its own — it resolves to the page it's on.
    html = '<a href="#top">Top</a>'
    links = extract_links(html, base_url="https://example.com/page")
    assert links == ["https://example.com/page"]


def test_drops_empty_and_missing_hrefs() -> None:
    html = '<a href="">Empty</a> <a>No href</a>'
    links = extract_links(html, base_url="https://example.com/page")
    assert links == []


def test_deduplicates_repeated_links_preserving_first_order() -> None:
    html = """
    <a href="/a">First</a>
    <a href="/b">Middle</a>
    <a href="/a">Repeat</a>
    """
    links = extract_links(html, base_url="https://example.com/")
    assert links == ["https://example.com/a", "https://example.com/b"]


def test_ignores_non_anchor_tags() -> None:
    html = '<link href="/style.css" rel="stylesheet"> <a href="/page">Page</a>'
    links = extract_links(html, base_url="https://example.com/")
    assert links == ["https://example.com/page"]


def test_empty_html_yields_no_links() -> None:
    assert extract_links("", base_url="https://example.com/") == []
