# Interview Prep — Async Crawler

**Five questions, five answers.** An unanswered question means this project is not shipped.

If you can't answer one, you don't understand that part of your own project yet — go back and understand it. This file is the difference between a portfolio that survives a technical screen and one that collapses in it.

---

### Q1. Walk me through the architecture in 90 seconds.

_A:_ The CLI parses arguments and wires four independent pieces together: `AsyncFetcher` does
the actual HTTP work — one `httpx.AsyncClient`, concurrency bounded by an `asyncio.Semaphore`.
`RateLimiter` and `RetryPolicy` are composed *into* `fetch()` as optional collaborators — the
rate limiter waits inside the semaphore (so pacing and concurrency both apply to the same
request), the retry backoff sleeps outside it (so a request that's backing off doesn't hold a
concurrency slot idle). `RobotsCache` fetches and caches one `robots.txt` parser per host and
gates every URL before it's fetched — including the seed URL itself. `Crawler.crawl()` does
breadth-first traversal one *level* at a time: it fetches an entire frontier concurrently via
`fetch_many()`, and for any result that's a same-domain HTML page it parses out more links with
stdlib `html.parser` and adds new ones to the next level. External links get checked (fetched
once, status recorded) but never recursed into. The result is a `CrawlReport`, formatted as text
or JSON, and the process exits 1 if anything came back broken — so it's usable as a CI gate.

### Q2. Why did you choose GET over HEAD for checking every link?

_A:_ A `HEAD`-first strategy is more bandwidth-efficient and is what I'd build at scale (it's in
"what I'd change" in the README). I didn't build it here because it trades away correctness for
speed in a way that's easy to get subtly wrong: a meaningful number of real servers either don't
implement `HEAD` at all (405), implement it incorrectly (returning 200 for a URL that 404s on
`GET`), or return a different status than `GET` would for authentication or redirect edge cases.
For a tool whose entire job is "tell me the truth about whether this link works," using the
request type that's actually authoritative was the right default. The optimization is a real,
known tradeoff — I just didn't want a correctness bug hiding behind a speed win in v1.

### Q3. What's the weakest part of this, and what would break first under load?

_A:_ The crawl frontier and the "seen" dedup set both live in one process's memory inside a
single `asyncio` event loop. That's fine for the tens-to-low-hundreds of pages this is scoped
for, but it caps out hard: no persistence (a crash loses the whole crawl), no way to split work
across processes or machines, and `RateLimiter`'s per-host state is process-local — run two
instances of this tool against the same site at once and they have no idea about each other's
pacing, so the "politeness" guarantee quietly stops being true. At real scale I'd move the
frontier to a durable queue and the rate-limit state to something shared like Redis. I know
exactly where this breaks because I designed the components (`RateLimiter`, `RetryPolicy`,
`RobotsCache`) to be swappable pieces specifically so that's a config change, not a rewrite.

### Q4. How do you know it works? What did you measure, and against what baseline?

_A:_ 82 tests, 100% statement coverage, all against mocked HTTP (custom
`httpx.AsyncBaseTransport` subclasses) so the suite has zero network dependency and zero
flakiness. But tests only prove the code does what I told it to — they don't prove the design
choices actually deliver what I claimed, so I also built `scripts/demo.py`: a small local site
(two `http.server` instances, no real network) that lets me measure real behavior. Against it:
the crawler correctly found the one deliberately-broken link and skipped the one
robots.txt-disallowed page; a deliberately flaky endpoint was hit 3 times by the server's own
count (2 failures + 1 success), proving the retry/backoff loop actually executes and not just
the happy path; and running the same site with `--max-concurrency 1` versus the default 10
measured 3.4s vs 0.64s — a real, reproducible ~5.3× speedup, not a claimed one. I also ran the
CLI against `example.com` for real (not mocked) to confirm the whole thing works outside tests
too.

### Q5. Two pages on the same site both link to the same third page. How do you know it only gets fetched once — and how would that answer change if the crawler were multi-process instead of single-process?

_A:_ Within one process it's straightforward: the crawler only adds a URL to the next BFS
frontier if it isn't already in a `seen` set, and that set is checked and updated synchronously
in a single-threaded event loop before any `await` — there's no `await` between the membership
check and the insert, so there's no window for two "discoveries" of the same link within one
batch to both pass the check. (This is also why the cycle test — a page linking back to the
seed — only shows one request for the seed URL in the whole crawl.) The harder version of this
question is the rate limiter, which *does* have concurrent access from multiple in-flight
requests: `RateLimiter.wait()` reads "time since last request to this host" and then decides
whether to sleep, and if two coroutines for the same host both read that state before either
writes it back, they'd both conclude "no wait needed" and both fire immediately. I fixed that
with a per-host `asyncio.Lock` around the whole read-decide-write sequence, and there's a test
(`test_concurrent_requests_to_same_host_are_serialized`) that fires two requests at once and
asserts on real elapsed time that the second one actually waited — not just that the code has a
lock in it. If this became multi-process, that in-memory lock stops being enough — I'd need a
shared, atomic "check-and-set last-request-time" operation, which is exactly the kind of thing
Redis's `SET key value NX` / Lua scripting is built for.

---

## 30-second pitch

Dead links are invisible until someone hits one, and checking for them by hand doesn't scale.
I built an async link checker that crawls a site concurrently — bounded by a semaphore, paced
per-host by a rate limiter, and retried with exponential backoff on 429s and 5xx errors — while
staying inside `robots.txt` for every request, including the seed page itself. It's a CLI that
exits non-zero when it finds a broken link, so it drops straight into CI. On a local benchmark
site, bounding concurrency at 10 instead of running serially cut a 20-link crawl from 3.4s to
0.64s — a measured 5.3× speedup, not a claimed one.
