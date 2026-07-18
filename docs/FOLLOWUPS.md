# Follow-ups (non-blocking)

These were surfaced by code review during the initial build (2026-07-17) and
triaged as safe to defer. None block use of the scraper. Ordered roughly by
value.

## Parser (`djinni_scraper/parser.py`)
- **Fallback path drops the Remote/On-site prefix.** When the JSON-LD is entirely
  absent (rare safety net), `location` is set from geography only — it loses the
  "Remote" qualifier that the JSON-LD path adds via `jobLocationType`. Cosmetic;
  to fix, capture the "Full Remote" `span.text-nowrap` in `_parse_cards`.
- **`_format_location` can crash on shapes not in the fixture.** A list-valued
  `jobLocationType` raises `TypeError`; a nested-object `addressLocality` returns
  a dict, which then makes `_enrich_from_cards` call `.lower()` on a non-str and
  abort the whole page (violating "skip one bad card, keep going"). Guard the
  types (`isinstance(location_type, str)`; coerce/skip non-str locality).
- **`_format_domain` "other" filter is case-sensitive** (`"Other"` would pass
  through). djinni emits lowercase slugs, so no live impact.
- **DRY / robustness polish:** `_parse_cards` and `_enrich_from_cards` duplicate
  the `job-item-<id>` card iteration (extract an `_iter_id_cards` helper); the
  fallback path walks the DOM twice; a couple of mid-function imports; the
  "English"/`.location-text` text heuristics and the card helpers lack isolated
  unit tests.

## Fetcher (`djinni_scraper/fetcher.py`)
- **Routine 4xx is reported as a block.** A 404/401/410 raises `BlockedError`
  with a "you may be throttled" message. No data loss (already-saved postings are
  flushed and skipped on resume), but the message misleads. Consider treating
  404/410 as "no more results / stop cleanly", distinct from a throttle.
- **HTTP-date `Retry-After` is ignored** (`_retry_after` only parses numeric
  seconds; a date-form header falls back to exponential backoff).
- **Cleanup:** `429` is a dead member of `_BACKOFF_STATUSES` (already fully
  handled by the `_BLOCK_STATUSES` branch) and the Retry-After retry logic is
  duplicated across the two branches.

## Storage (`djinni_scraper/storage.py`)
- **`Scraped-at` uses `date.today()`**, not the injected run date `when`, so it
  can diverge from the header's `scraped_at` on a multi-day resume and is
  non-deterministic/untested. Thread `when` through, or document it as an
  intentional per-posting timestamp.
- **Style nits:** unused `from typing import Optional`; `assert` used for an
  `open()` precondition (stripped under `python -O`); a mid-function import.

## CLI (`djinni_scraper/cli.py`)
- **Host-rejection message no longer echoes the rejected host**, a small
  debuggability regression for mistyped URLs.
- **Clamp backstop is single-page.** `run()` stops when a page's id-set exactly
  repeats the immediately preceding page's. A listing whose genuine last page
  duplicates the prior page's ids (unstable sort) would stop one page early — an
  accepted tradeoff favoring anti-block safety.
