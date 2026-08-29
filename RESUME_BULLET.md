# Resume Bullets — Async Crawler

Form: **action → technical specifics → measured outcome.** Numbers or it doesn't go on the resume.

---

## Bullets

- Built an async web crawler and link checker (Python, `asyncio`, `httpx`) with bounded
  concurrency, per-host rate limiting, and exponential backoff with jitter on 429/5xx/timeout
  responses; measured a 5.3× crawl speedup (3.4s → 0.64s on a 20-link benchmark) from
  semaphore-bounded concurrency alone.
- Implemented `robots.txt`-compliant crawling by decoupling async fetch from stdlib
  `urllib.robotparser` parsing (avoiding its blocking `read()`), with a documented fail-closed
  policy on 401/403/5xx per RFC 9309 and a per-host cache so each site's rules are fetched once.
- Shipped as a CLI (stdlib `argparse`) that exits non-zero on any broken link found, so it drops
  into a CI pipeline as a link-check gate; supports plain-text or JSON output.
- 82 tests, 100% statement coverage, entirely against mocked HTTP transports — zero network
  dependency and zero flakiness in CI.

## Which roles this supports

- [ ] Data Scientist / ML
- [x] AI Engineer (LLM/NLP/CV) — async data-collection pipeline, the kind that feeds a corpus
      into NLP/RAG projects
- [x] Data Engineer — concurrent ingestion, rate limiting, retry/backoff, CI-gated pipeline
- [x] Data Analyst / Python Developer — general Python engineering: CLI design, `asyncio`,
      stdlib-first architecture

## Keywords this project earns

`asyncio`, `httpx`, concurrent programming, semaphore-bounded concurrency, rate limiting,
exponential backoff with jitter, `robots.txt` / RFC 9309, web crawling, link checking, CLI design
(`argparse`), CI gating via process exit codes, mocked HTTP testing (`httpx.AsyncBaseTransport`),
100% test coverage.

---

### Bad vs good

❌ "Built a machine learning model to predict customer churn using Python."
✅ "Built a churn classifier on 240k accounts (LightGBM, 1:40 class imbalance) with isotonic calibration and cost-sensitive thresholding, lifting precision@10% from 0.31 to 0.58 over the business's existing rules baseline."

The second one is answerable in an interview. The first invites the question you can't answer.
