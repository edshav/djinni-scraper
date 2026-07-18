import datetime as dt
from pathlib import Path

from djinni_scraper.cli import build_page_url, main, run
from djinni_scraper.fetcher import BlockedError
from djinni_scraper.storage import run_filename

FIXTURE = Path(__file__).parent / "fixtures" / "listing_fullstack.html"
URL = "https://djinni.co/jobs/?primary_keyword=Fullstack&salary=3000"


def test_build_page_url_sets_page_and_keeps_filters():
    out = build_page_url(URL, 2)
    assert "page=2" in out
    assert "primary_keyword=Fullstack" in out
    assert "salary=3000" in out
    assert out.count("page=") == 1


def test_build_page_url_replaces_existing_page():
    out = build_page_url("https://djinni.co/jobs/?page=5&salary=3000", 3)
    assert "page=3" in out and "page=5" not in out


class FakeFetcher:
    """Returns the fixture for page 1, then an empty page (last page)."""

    def __init__(self):
        self.urls = []
        self._html = FIXTURE.read_text(encoding="utf-8")

    def get(self, url):
        self.urls.append(url)
        if "page=1" in url:
            return self._html
        return "<html><body>no jobs</body></html>"


def test_run_writes_combined_file(tmp_path):
    fetcher = FakeFetcher()
    written = run(
        listing_url=URL,
        out_dir=tmp_path,
        max_pages=None,
        max_jobs=1000,
        delay=0.0,
        overwrite=False,
        fetcher=fetcher,
        when=dt.date(2026, 7, 17),
    )
    assert written == 15
    files = list(tmp_path.glob("2026-07-17__*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert content.count("<!-- job-id:") == 15
    assert "## Senior full-stack or integration engineer" in content


def test_run_respects_max_jobs(tmp_path):
    fetcher = FakeFetcher()
    written = run(
        listing_url=URL,
        out_dir=tmp_path,
        max_pages=None,
        max_jobs=5,
        delay=0.0,
        overwrite=False,
        fetcher=fetcher,
        when=dt.date(2026, 7, 17),
    )
    assert written == 5
    # Should stop after page 1 without fetching page 2.
    assert fetcher.urls == [build_page_url(URL, 1)]


class BlockedAfterFirstPageFetcher:
    """Returns the fixture for page 1 (15 postings), then raises BlockedError
    on page 2 -- simulating djinni throttling us mid-run. No real network."""

    def __init__(self):
        self.urls = []
        self._html = FIXTURE.read_text(encoding="utf-8")

    def get(self, url):
        self.urls.append(url)
        if "page=1" in url:
            return self._html
        raise BlockedError("blocked at page 2")


def test_run_stops_on_blocked_error(tmp_path):
    fetcher = BlockedAfterFirstPageFetcher()
    written = run(
        listing_url=URL,
        out_dir=tmp_path,
        max_pages=None,
        max_jobs=1000,
        delay=0.0,
        overwrite=False,
        fetcher=fetcher,
        when=dt.date(2026, 7, 17),
    )
    # The BlockedError must be caught inside run(), not propagated: partial
    # progress (page 1's postings) is preserved and reported as an int.
    assert isinstance(written, int)
    assert written == 15
    # The store must have been closed (via the `finally` clause) so the file
    # is fully flushed and readable, even though the run stopped early.
    files = list(tmp_path.glob("2026-07-17__*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert content.count("<!-- job-id:") == 15


class ClampedFetcher:
    """Simulates a site that clamps an out-of-range page=N to the last page:
    every page returns the SAME non-empty postings, forever. Capped to a
    small number of calls and raises past that -- so a still-broken
    implementation fails loudly (assertion error) instead of hanging."""

    def __init__(self, max_calls=5):
        self.urls = []
        self._html = FIXTURE.read_text(encoding="utf-8")
        self._max_calls = max_calls

    def get(self, url):
        self.urls.append(url)
        if len(self.urls) > self._max_calls:
            raise AssertionError(
                "fetcher called too many times; clamped pagination did not stop"
            )
        return self._html


def test_run_stops_on_clamped_pagination(tmp_path):
    fetcher = ClampedFetcher()
    written = run(
        listing_url=URL,
        out_dir=tmp_path,
        max_pages=None,
        max_jobs=1000,
        delay=0.0,
        overwrite=False,
        fetcher=fetcher,
        when=dt.date(2026, 7, 17),
    )
    assert written == 15
    files = list(tmp_path.glob("2026-07-17__*.md"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert content.count("<!-- job-id:") == 15
    # Page 1 appends 15 postings; page 2 repeats the same id-set -> stop.
    assert fetcher.urls == [build_page_url(URL, 1), build_page_url(URL, 2)]


def test_main_rejects_non_djinni_host(capsys, tmp_path):
    # --max-jobs 0 makes run() (if it's ever reached) stop before the very
    # first fetch, so this test cannot make a real network request even if
    # the host check under test were buggy and wrongly let a bad host through.
    safe_args = ["--max-jobs", "0", "--out-dir", str(tmp_path)]

    assert main(["https://notdjinni.co/jobs", *safe_args]) == 2
    assert "djinni.co" in capsys.readouterr().err

    # Spoofed subdomain-looking host: real host is "djinni.co.evil.com".
    assert main(["https://djinni.co.evil.com/jobs", *safe_args]) == 2
    assert "djinni.co" in capsys.readouterr().err

    # Userinfo spoofing: netloc is "djinni.co:x@evil.com", real host is "evil.com".
    assert main(["https://djinni.co:x@evil.com/jobs", *safe_args]) == 2
    assert "djinni.co" in capsys.readouterr().err

    # A genuine djinni.co host must NOT be rejected for the host reason.
    assert main(["https://djinni.co/jobs/", *safe_args]) == 0


def test_main_reports_source_mismatch(tmp_path, capsys):
    real_url = URL
    different_url = "https://djinni.co/jobs/?primary_keyword=Backend"
    when = dt.date.today()

    existing_path = tmp_path / run_filename(real_url, when)
    existing_path.write_text(
        "<!-- djinni-scraper\n"
        f"source_url: {different_url}\n"
        f"scraped_at: {when.isoformat()}\n"
        "-->\n"
        f"# Djinni postings — {different_url}\n\n",
        encoding="utf-8",
    )

    # No fetcher is injected: this relies on store.open() raising
    # SourceMismatch before run() ever constructs/calls a real Fetcher.get().
    result = main([real_url, "--out-dir", str(tmp_path)])

    assert result == 2
    err = capsys.readouterr().err
    assert "was created for" in err
