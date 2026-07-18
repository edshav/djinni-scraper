# djinni-scraper

Polite scraper for [djinni.co](https://djinni.co) job listings. Paginates a
search URL, reads each posting from the page's embedded JSON-LD (no detail-page
requests, no browser), and writes everything into one Markdown file per run for
AI-assisted analysis.

## Install

    python3 -m venv .venv
    .venv/bin/pip install -e .

## Usage

    .venv/bin/djinni-scraper "https://djinni.co/jobs/?primary_keyword=Fullstack&salary=3000"

Options:

- `--out-dir DIR`   where the `.md` file is written (default `./output`)
- `--max-jobs N`    cap on total postings in the file (default `1000`)
- `--max-pages N`   cap on listing pages fetched (default: until last page)
- `--delay S`       base seconds between requests, ±50% jitter (default `4.0`)
- `--overwrite`     ignore an existing run file and scrape fresh

## Politeness / avoiding blocks

djinni will IP-block aggressive scrapers. This tool is sequential, waits
`--delay` (±50% jitter) between every request, honors `Retry-After` and backs
off with retries on `429`, and **stops immediately** on `403` or a detected
Cloudflare challenge. Because postings are appended live and deduped by job id,
re-running later resumes where it stopped. Raise `--delay` for large runs.
