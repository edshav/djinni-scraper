"""Command-line entry point and pagination orchestration."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetcher import BlockedError, Fetcher
from .parser import parse_listing
from .storage import MarkdownStore, SourceMismatch

log = logging.getLogger("djinni_scraper")


def build_page_url(listing_url: str, page: int) -> str:
    parts = urlsplit(listing_url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
    query.append(("page", str(page)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def run(
    listing_url: str,
    out_dir,
    max_pages: Optional[int],
    max_jobs: Optional[int],
    delay: float,
    overwrite: bool,
    fetcher=None,
    when: Optional[dt.date] = None,
) -> int:
    when = when or dt.date.today()
    fetcher = fetcher or Fetcher(delay=delay)
    store = MarkdownStore(listing_url, out_dir, when, overwrite=overwrite)
    store.open()

    written = 0
    page = 1
    try:
        while True:
            if max_pages is not None and page > max_pages:
                log.info("Reached --max-pages=%s", max_pages)
                break
            if max_jobs is not None and store.count >= max_jobs:
                log.info("Reached --max-jobs=%s", max_jobs)
                break

            html = fetcher.get(build_page_url(listing_url, page))
            postings = parse_listing(html)
            if not postings:
                log.info("No postings on page %s; done.", page)
                break

            for posting in postings:
                if max_jobs is not None and store.count >= max_jobs:
                    break
                if store.append(posting):
                    written += 1
            log.info("Page %s: file now holds %s postings.", page, store.count)
            page += 1
    except BlockedError as exc:
        log.warning("%s", exc)
        log.warning("Saved %s new postings to %s. Wait a while and re-run to resume.", written, store.path)
    finally:
        store.close()

    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="djinni-scraper", description="Scrape djinni.co job listings.")
    parser.add_argument("listing_url", help="djinni listing/search URL")
    parser.add_argument("--out-dir", default="./output")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-jobs", type=int, default=1000)
    parser.add_argument("--delay", type=float, default=4.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    host = urlsplit(args.listing_url).netloc.lower().split(":")[0]
    if host != "djinni.co" and not host.endswith(".djinni.co"):
        print(
            f"error: listing_url host must be djinni.co (or a djinni.co subdomain), got {host!r}",
            file=sys.stderr,
        )
        return 2

    try:
        written = run(
            listing_url=args.listing_url,
            out_dir=args.out_dir,
            max_pages=args.max_pages,
            max_jobs=args.max_jobs,
            delay=args.delay,
            overwrite=args.overwrite,
        )
    except SourceMismatch as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {written} new postings.")
    return 0
