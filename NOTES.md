# Build Notes — Async Crawler

Working notes: what broke, what you tried, why you chose X over Y.
Not for recruiters — for you, six months from now, in an interview.

Keep it rough. Rough is the point.

---

## Log

### 2026-08-29 — Stage 2: robots.txt
- **Tried:** feed fetched robots.txt text to `RobotFileParser.parse()` instead of the blocking
  `.read()`, so the fetch can go through the async httpx client.
- **Broke:** every `can_fetch()` call returned `False`, even for a 404 (no robots.txt → should
  allow everything) and for URLs a rule explicitly `Allow`s.
- **Fixed by:** two separate stdlib quirks, both non-obvious from the docs:
  1. `can_fetch()` returns `False` unconditionally until `self.last_checked` is truthy — a guard
     against querying before `read()`/`modified()` ran. `parse()` alone never sets it. Fix: call
     `parser.modified()` explicitly after every fetch outcome (200, 4xx-absent, or the
     disallow_all branches).
  2. stdlib's rule matching is **first-match-in-file-order**, not Google's "longest path wins."
     An `Allow` meant to override a broader `Disallow` must be written *before* it in the
     robots.txt, or it never gets checked.
- **Learned:** stdlib `urllib.robotparser` is a thin, literal implementation — it does not
  implement the de facto robots.txt semantics (longest-match-wins) that Google's parser and RFC
  9309 examples assume. Fine for this project's scope (it's still spec-compliant on order),
  but worth knowing before trusting it against real-world robots.txt files that rely on
  longest-match precedence.

---

### 2026-08-29 — Stage 3: rate limiting + backoff
- **Tried:** `retry.py` imports `FetchResult` from `fetcher.py` for `is_retryable()`'s type hint,
  while `fetcher.py` imports `retry.py` to call `is_retryable()`/`compute_delay()` inside `fetch()`.
- **Broke:** `ImportError: cannot import name 'FetchResult' from partially initialized module` —
  a straightforward circular import between the two modules.
- **Fixed by:** moved the `FetchResult` import in `retry.py` behind `if TYPE_CHECKING:`. Works
  for free because `from __future__ import annotations` (PEP 563) already makes every annotation
  a lazily-evaluated string — the name never needs to exist at runtime, only when a type checker
  reads the file.
- **Learned:** composing two modules that reference each other's types is fine as long as at
  most one side needs the reference at *runtime* (not just for a type hint). Worth remembering
  before reaching for a shared "types" module as the default fix.

### 2026-08-29 — Stage 4: link checker / crawler
- **Tried:** wrote `extract_links` test expecting `href="#top"` to be dropped as "fragment-only."
- **Broke:** it resolved to `https://example.com/page` (the current page, minus the fragment) —
  not empty. `urljoin(base, "#top")` legitimately produces the base URL; `urldefrag` then strips
  the fragment, leaving a real, fetchable URL.
- **Fixed by:** realized this is correct, not a bug — a fragment-only href really does point back
  at the page it's on. Split the test into "fragment-only resolves to the current page" (kept)
  vs. "truly empty/missing href" (dropped, since `handle_starttag` only records `href` when its
  value is truthy).
- **Also hit:** first draft of a crawl test asserted `pages_crawled == 3` for a fixture with one
  internal 404 (`/broken`) among three good pages, expecting only *successful* pages to count.
  Actual count was 4. **Learned:** `pages_crawled` counts every same-domain URL the crawler
  actually fetched, not just ones that returned HTML successfully — a broken internal link still
  used a `max_pages` slot. Worth stating explicitly in the crawler's docstring/README, since
  "pages crawled" reads as "pages successfully parsed" if you don't think about it.

### 2026-08-29 — Stage 5: CLI + report
- **Tried:** used an em dash (`—`) in the `--ignore-robots` argparse help string and in the
  broken-links report line, then ran `uv run async-crawler --help > file.txt` to smoke-test it.
- **Broke:** the redirected output contained byte `\x97` where the em dash should be — that's
  the em dash in **Windows-1252**, not UTF-8 (`\xe2\x80\x94`). Any tool expecting UTF-8 (a CI
  log viewer, a non-Windows reader, `python -c "...decode('utf-8')..."`) would mangle or fail on
  it. Confirmed by reading the raw bytes rather than trusting what the terminal displayed — the
  terminal itself was rendering it as `?`, which looked like it might just be a display quirk,
  not a real bug.
- **Fixed by:** replaced both em dashes with a plain hyphen. Root cause: Python on Windows uses
  the Windows console API for UTF-8-safe output only when stdout is an actual interactive
  console; the moment it's redirected/piped (a file, `| grep`, CI capturing output), it falls
  back to `locale.getpreferredencoding()`, which on this machine is cp1252.
- **Learned:** don't put non-ASCII characters in anything a CLI actually prints (argparse help
  text, report output) — even though this project already prints em dashes just fine when run
  interactively, "works in an interactive terminal" and "works when redirected" are genuinely
  different guarantees on Windows. Non-ASCII in source comments/docstrings is fine; the line is
  whether the string reaches `print()`.

## Rejected approaches

| Approach | Why rejected |
|---|---|
| | |

## Open questions

- [ ]
