import datetime as dt
from pathlib import Path

from djinni_scraper.cli import build_page_url, run

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
