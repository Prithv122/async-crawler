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

## Rejected approaches

| Approach | Why rejected |
|---|---|
| | |

## Open questions

- [ ]
