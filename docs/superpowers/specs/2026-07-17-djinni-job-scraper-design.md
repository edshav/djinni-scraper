# djinni.co Job Scraper — Design

**Date:** 2026-07-17
**Status:** Approved (design), pending implementation plan

## Purpose

Collect job postings from a djinni.co job-board listing URL for later analysis
**with an AI assistant (e.g. Claude Code)**. Given a listing URL (no
authentication required), the tool paginates through the whole listing and saves
all postings into **a single combined Markdown file** named for the scrape date
and the listing/search URL. **The full posting content lives on the listing page
itself** — no detail-page visits are needed. Expected volume is hundreds of
postings per run, which fits comfortably in one file.

## Key facts established during research

- **Server-side rendered.** All job data (titles, metadata, and the *full*
  descriptions) is present in the initial listing-page HTML. No headless browser
  is required; a plain HTTP client + HTML parser is sufficient.
- **Full description is on the listing page.** Each job card contains two copies
  of the description: `js-truncated-text` (the snippet shown) and
  `js-original-text description-expandable d-none` — the **complete** description,
  already in the HTML but hidden with `d-none` and revealed by the "More" link via
  JavaScript. Because we parse HTML directly (not a browser), we read the full
  hidden text straight from the DOM. **We do not fetch detail pages.** Verified:
  the hidden blocks hold complete ~2,000–2,800-character descriptions.
- **Card container.** Each posting is a `<... class="job-item card-link ...">`
  element inside `<ul class="list-unstyled list-jobs ...">`. A page of this
  listing has 15 cards. The title is in `job-item__position`, tag metadata in
  `job-item__tags`, salary in a `text-success` element, and the card's anchor
  `href="/jobs/<id>-<slug>/"` gives the posting URL and numeric id.
- **Short-description edge case.** One card on the sample page had **no**
  `js-original-text` block — its description was short enough not to be truncated.
  Rule: per card, description = `js-original-text` if present, else
  `js-truncated-text` (the visible text is already complete).
- **robots.txt allows `/jobs/`.** Disallowed paths are only `/jobs2`, `/q`,
  `/developers`, `/free-jobs`, `/set_lang`. No `Crawl-delay` directive, so the
  tool self-imposes a polite delay.
- **Hard constraint — IP-block risk.** The user was previously IP-blocked for a
  full day by djinni for scraping too aggressively. Avoiding a block is the top
  priority, ranked above speed. Not fetching detail pages cuts request volume by
  ~15× (one request per ~15 postings), which materially lowers block risk.

## Non-goals (YAGNI)

- **No detail-page requests** — everything is parsed from listing pages.
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
    parser.py     # listing HTML -> list[JobPosting]
    storage.py    # append JobPostings to one combined .md, dedup by id
    cli.py        # arg parsing, orchestration, progress, block handling
  tests/
    fixtures/     # saved real listing-page HTML
    test_parser.py
    test_storage.py
  pyproject.toml  # deps: requests, beautifulsoup4, lxml
  README.md
```

Each unit has one purpose and a narrow interface:

- **`models.JobPosting`** — dataclass holding one posting's fields. All content
  fields optional (`None`/empty allowed) so a card missing a field never crashes.
- **`fetcher.Fetcher`** — owns a `requests.Session` and *all* politeness/anti-block
  behavior. Interface: `get(url) -> str` (HTML). Raises `BlockedError` when a block
  is detected. Depends on: `requests`, config (delay, jitter, user-agent).
- **`parser`** — pure functions over HTML strings, no I/O:
  - `parse_listing(html, base_url) -> list[JobPosting]` — one `JobPosting` per
    `job-item` card. An empty list signals "no more results / last page".
- **`storage`** — appends `JobPosting`s to the single combined `.md` file;
  builds the run filename from the listing URL + date; on open, reads back already
  saved job ids for skip/dedup. Depends on: filesystem, out-dir.
- **`cli`** — wires the above, prints progress, enforces limits, handles
  `BlockedError` by stopping the whole run gracefully.

## Data flow

1. CLI parses `listing_url` (positional) and flags.
2. **Paginate the listing.** For `page = 1, 2, ...`, build the page URL by merging
   a `page=N` query parameter into `listing_url` (preserving existing filter
   params such as `primary_keyword`, `salary`, `search_type` via
   `urllib.parse`), fetch it, and `parse_listing` it into a list of `JobPosting`.
   Stop when: the page yields **no** cards (last page), OR `--max-pages` is
   reached, OR cumulative postings reach `--max-jobs`.
3. **Per posting (already fully parsed from the page).** If the posting's numeric
   job id was already saved to this run's combined file (read back on open — the
   id is the stable identifier, independent of date or slug) → **skip**.
   Otherwise **append** the posting as a Markdown section to the combined file and
   flush. No additional HTTP request is made per posting. Appending live means a
   mid-run block loses no already-collected postings, and a re-run resumes by
   skipping ids already present.
4. A polite delay (with jitter) precedes **every** listing-page request. Since
   postings need no requests of their own, total requests ≈ number of listing
   pages.

## Fetcher — anti-block behavior (primary requirement)

- **Sequential only.** No threads/async; parallel requests are the top block
  trigger.
- **Minimal request volume.** Only listing pages are fetched (~1 request per 15
  postings), the single biggest reduction in block risk.
- **Generous randomized delay.** Default `--delay 4.0` seconds with ±50% jitter
  (actual ≈ 2–6 s per request), so cadence is not robotic. Raise for large runs.
- **Realistic headers.** A current Chrome `User-Agent` and `Accept-Language`,
  sent on a persistent `requests.Session`.
- **Server-respecting backoff.** On `429`/`503`, honor the `Retry-After` header;
  otherwise exponential backoff with bounded retries for transient network errors.
- **Stop-on-block.** On `429`, `403`, or a detected Cloudflare challenge page,
  raise `BlockedError` to halt the entire run gracefully with a clear message
  ("you may be throttled — wait and re-run later"). Because postings are appended
  to the combined file as they are scraped, re-running later resumes from where it
  stopped. The tool deliberately does **not** keep requesting once flagged.

## Storage & filename

- **One combined `.md` file per run**, written to `--out-dir` (default `./output`).
- **Filename** contains the scrape date and the **listing/search URL**, sanitized
  to be filesystem-safe (scheme stripped, non-`[A-Za-z0-9._-]` chars collapsed to
  `_`, length-bounded):
  `2026-07-17__djinni.co_jobs_Fullstack_salary-3000.md`
  - Date = scrape date, `YYYY-MM-DD`. Re-running the same search on the same day
    reuses/extends the same file (append + skip); a different day starts a new file.
- **File structure** — a short run header (source listing URL, scrape date), then
  one `##` section per posting separated by `---`. Each section has labeled fields
  followed by the full description:
  - `Title` (as the `##` heading), `Company`, `Salary`, `Location/Remote`,
    `Experience`, `English`, `Company type/Domain`, `Posted`, `URL` (the posting's
    detail URL, for reference and as the id source), `Scraped-at`, then the full
    description text.
  - Missing fields are written as `N/A` (kept, for consistent structure).
- **Skip / dedup** matches on the numeric job id parsed from each posting's URL
  (the stable identifier). On open, the storage layer reads back ids already
  present in the file so appends never duplicate — covering both cross-page
  duplicates (e.g. featured + normal listing) and resumed runs.

## Error handling

- Transient network error → bounded retry with exponential backoff (in fetcher).
- A single card fails to parse → log a warning, skip **that card**, continue the
  run (one malformed card never kills the whole run).
- Block detected → stop the **entire** run gracefully (see Fetcher).
- Invalid `listing_url` / non-djinni host → fail fast with a clear message before
  any scraping.

## Testing strategy

- **TDD the parser** (the fragile boundary). `test_parser.py` runs against a real
  saved listing-page fixture (`tests/fixtures/`) and asserts: the expected number
  of `JobPosting` objects, the full-vs-truncated description fallback (including
  the one short card with no `js-original-text`), and each extracted field for a
  known card. When djinni changes markup, a failing test points straight at the
  fix.
- **`test_storage.py`** — run-filename building from a listing URL (date + safe
  sanitized search URL); appending a posting produces a well-formed `##` section;
  and read-back dedup (a posting whose id is already in the file is skipped, so a
  second append of the same id does not duplicate).
- Fetcher is **not** tested against the live site (flaky and impolite). Its delay
  math may optionally be unit-tested with an injected clock.

## CLI flags (summary)

| Flag | Default | Purpose |
|------|---------|---------|
| `listing_url` (positional) | — | djinni listing URL to scrape |
| `--out-dir` | `./output` | where `.md` files are written |
| `--max-pages` | unlimited | cap listing pages fetched |
| `--max-jobs` | unlimited | cap total postings saved |
| `--delay` | `4.0` | base seconds between requests (±50% jitter applied) |

## Dependencies

- `requests` — HTTP client + Session.
- `beautifulsoup4` + `lxml` — HTML parsing.
- Standard library for everything else (`argparse`, `urllib.parse`, `pathlib`,
  `random`, `datetime`, `re`, `logging`).
