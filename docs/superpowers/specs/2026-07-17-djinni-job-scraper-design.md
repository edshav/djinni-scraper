# djinni.co Job Scraper — Design

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation plan

## Purpose

Collect job postings from a djinni.co job-board listing URL for later analysis.
Given a listing URL (no authentication required), the tool paginates through the
whole listing, follows each posting to its detail page, extracts the full
un-truncated content, and saves one Markdown file per posting. Each filename
contains the scrape date and the posting URL.

## Key facts established during research

- **Server-side rendered.** All job data (titles, metadata, truncated
  descriptions) is present in the initial HTML. No headless browser is required;
  a plain HTTP client + HTML parser is sufficient.
- **Two-level structure.** A paginated listing (`/jobs/?page=N`) whose cards link
  to detail pages (`/jobs/<id>-<slug>/`) that hold the full description.
  "Expanding" a posting means following that link and scraping the detail page.
- **robots.txt allows `/jobs/`.** Disallowed paths are only `/jobs2`, `/q`,
  `/developers`, `/free-jobs`, `/set_lang`. No `Crawl-delay` directive is
  specified, so the tool self-imposes a polite delay.
- **Hard constraint — IP-block risk.** The user was previously IP-blocked for a
  full day by djinni for scraping too aggressively. Avoiding a block is the top
  priority, ranked above speed.

## Non-goals (YAGNI)

- No headless browser / JavaScript execution.
- No concurrency or parallel requests.
- No database; output is flat Markdown files.
- No login/authenticated scraping.
- No scheduling/daemonizing; it is a single run-to-completion CLI.

## Architecture

Language/runtime: **Python 3**. Run as `python -m djinni_scraper "<listing_url>" [flags]`.

```
djinni-scrapper/
  djinni_scraper/
    __init__.py
    models.py     # JobPosting dataclass
    fetcher.py    # HTTP + all anti-block logic
    parser.py     # HTML -> JobPosting / listing HTML -> job URLs
    storage.py    # JobPosting -> .md, skip-existing
    cli.py        # arg parsing, orchestration, progress, block handling
  tests/
    fixtures/     # saved real HTML (a job detail page + a listing page)
    test_parser.py
    test_storage.py
  pyproject.toml  # deps: requests, beautifulsoup4, lxml
  README.md
```

Each unit has one purpose and a narrow interface:

- **`models.JobPosting`** — dataclass holding one posting's fields. All content
  fields optional (`None`/empty allowed) so a page missing a field never crashes.
- **`fetcher.Fetcher`** — owns a `requests.Session` and *all* politeness/anti-block
  behavior. Interface: `get(url) -> str` (HTML). Raises `BlockedError` when a block
  is detected. Depends on: `requests`, config (delay, jitter, user-agent).
- **`parser`** — pure functions over HTML strings, no I/O.
  - `parse_listing(html, base_url) -> list[str]` — absolute job-detail URLs on a
    listing page (empty list signals "no more results / last page").
  - `parse_job(html, url) -> JobPosting`.
- **`storage`** — `JobPosting` -> `.md` file; filename building; skip-existing check.
  Depends on: filesystem, out-dir.
- **`cli`** — wires the above, prints progress, enforces limits, handles
  `BlockedError` by stopping the whole run gracefully.

## Data flow

1. CLI parses `listing_url` (positional) and flags.
2. **Paginate the listing.** For `page = 1, 2, ...`, build the page URL by merging
   a `page=N` query parameter into `listing_url` (preserving any existing filter
   params via `urllib.parse`), fetch it, and `parse_listing` it into job-detail
   URLs. Stop when: the page yields no job URLs (last page), OR `--max-pages` is
   reached, OR the cumulative jobs collected reaches `--max-jobs`.
3. **Per job URL.** If a file for that job already exists in the out-dir (matched
   by job id/slug, ignoring the date prefix) → **skip** (resumable). Otherwise
   `get` the detail page, `parse_job`, and write the `.md`.
4. A polite delay (with jitter) precedes **every** HTTP request (both listing and
   detail fetches).

## Fetcher — anti-block behavior (primary requirement)

- **Sequential only.** No threads/async; parallel requests are the top block
  trigger.
- **Generous randomized delay.** Default `--delay 4.0` seconds with ±50% jitter
  (actual ≈ 2–6 s per request), so cadence is not robotic. Raise for large runs.
- **Realistic headers.** A current Chrome `User-Agent` and `Accept-Language`,
  sent on a persistent `requests.Session`.
- **Server-respecting backoff.** On `429`/`503`, honor the `Retry-After` header;
  otherwise exponential backoff with bounded retries for transient network errors.
- **Stop-on-block.** On `429`, `403`, or a detected Cloudflare challenge page,
  raise `BlockedError` to halt the entire run gracefully with a clear message
  ("you may be throttled — wait and re-run later"). Because per-job files are
  already saved, re-running later resumes from where it stopped. The tool
  deliberately does **not** keep requesting once flagged.

## Storage & filename

- One `.md` file per job posting, written to `--out-dir` (default `./output`).
- **Filename** contains the scrape date and the URL, sanitized to be
  filesystem-safe (scheme stripped, non-`[A-Za-z0-9._-]` chars replaced with `_`):
  `2026-07-17__djinni.co_jobs_123456-senior-python-engineer.md`
  - Date = scrape date, `YYYY-MM-DD`.
- **Skip-existing** matches on the job's id/slug portion (ignoring the date
  prefix), so a re-run on a later date does not re-fetch already-saved jobs.
- **File contents** — labeled fields followed by the full description:
  - `Title`, `Company`, `Salary`, `Location/Remote`, `Experience`, `English`,
    `Company type/Domain`, `Posted`, `URL`, `Scraped-at`, then the full
    description text.
  - Missing fields are written as `N/A` (kept, for consistent structure).

## Error handling

- Transient network error → bounded retry with exponential backoff (in fetcher).
- A single job fails to parse → log a warning, skip **that job**, continue the
  run (one bad page never kills the whole run).
- Block detected → stop the **entire** run gracefully (see Fetcher).
- Invalid `listing_url` / non-djinni host → fail fast with a clear message before
  any scraping.

## Testing strategy

- **TDD the parser** (the fragile boundary). `test_parser.py` runs against a real
  saved HTML fixture (`tests/fixtures/`) and asserts each extracted field for a
  job page, and asserts the job-URL list for a listing page. When djinni changes
  markup, a failing test points straight at the fix.
- **`test_storage.py`** — filename sanitization (URL → safe filename containing
  date + URL) and skip-existing logic (a matching file causes a skip).
- Fetcher is **not** tested against the live site (flaky and impolite). Its delay
  math may optionally be unit-tested with an injected clock, but that is optional.

## CLI flags (summary)

| Flag | Default | Purpose |
|------|---------|---------|
| `listing_url` (positional) | — | djinni listing URL to scrape |
| `--out-dir` | `./output` | where `.md` files are written |
| `--max-pages` | unlimited | cap listing pages fetched |
| `--max-jobs` | unlimited | cap total jobs fetched |
| `--delay` | `4.0` | base seconds between requests (±50% jitter applied) |

## Dependencies

- `requests` — HTTP client + Session.
- `beautifulsoup4` + `lxml` — HTML parsing.
- Standard library for everything else (`argparse`, `urllib.parse`, `pathlib`,
  `random`, `datetime`, `re`, `logging`).
