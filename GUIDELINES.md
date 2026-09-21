# Async Crawler — A4

**Tier:** 1 · **Category:** A — Simple Python · **Wave:** 1

Root rules in `../GUIDELINES.md` apply. This file is project-specific only — keep it under 40 lines.

## What this is

Async web scraper and link checker: crawls a site with `httpx.AsyncClient`, respects
`robots.txt`, rate-limits and retries with exponential backoff, and reports broken links.

## Stack

Python 3.13, `httpx` (async HTTP), stdlib `urllib.robotparser` (decoupled from its blocking
`read()`), `asyncio.Semaphore` for concurrency, stdlib `html.parser` for link extraction, stdlib
`argparse` for the CLI.

## Acceptance criteria

- [x] Async scraper + link checker (httpx, rate limiting, backoff, robots.txt) — from CATALOG.md
- [x] Proves: asyncio, ethical scraping
- [ ] Ship gate passes

## Project-specific notes

No external accounts/services needed — crawl targets are public sites (or a local test
fixture server for tests, so the suite doesn't depend on network access). Respect robots.txt
by default; add an explicit override flag rather than defaulting to ignore it.
