import datetime as dt

import pytest

from djinni_scraper.models import JobPosting
from djinni_scraper.storage import MarkdownStore, SourceMismatch, render_section, run_filename

WHEN = dt.date(2026, 7, 17)
URL = "https://djinni.co/jobs/?primary_keyword=Fullstack&salary=3000"


def sample(job_id=837890):
    return JobPosting(
        url=f"https://djinni.co/jobs/{job_id}-x/",
        id=job_id,
        title="Senior Full Stack",
        company="Upstaff",
        salary="$3000–5000/mo",
        location="Remote · Worldwide",
        experience="5 years",
        english="B2",
        domain="proptech",
        posted="2026-07-17",
        description="Full description here.",
    )


def test_run_filename_contains_date_and_sanitized_url():
    name = run_filename(URL, WHEN)
    assert name.startswith("2026-07-17__")
    assert name.endswith(".md")
    assert "djinni.co_jobs" in name
    assert "Fullstack" in name
    assert "/" not in name and "?" not in name and "&" not in name


def test_render_section_has_marker_heading_and_fields():
    text = render_section(sample())
    assert "<!-- job-id: 837890 -->" in text
    assert text.count("## Senior Full Stack") == 1
    assert "**Company:** Upstaff" in text
    assert "**Salary:** $3000–5000/mo" in text
    assert "Full description here." in text
    assert text.rstrip().endswith("---")


def test_render_section_missing_fields_become_na():
    bare = JobPosting(url="https://djinni.co/jobs/1-x/", id=1, title="X")
    text = render_section(bare)
    assert "**Salary:** N/A" in text


def test_append_writes_and_dedupes(tmp_path):
    store = MarkdownStore(URL, tmp_path, WHEN)
    store.open()
    assert store.append(sample(837890)) is True
    assert store.append(sample(837890)) is False  # duplicate id
    assert store.append(sample(827322)) is True
    store.close()
    content = store.path.read_text(encoding="utf-8")
    assert content.count("<!-- job-id:") == 2
    assert store.count == 2


def test_resume_reads_existing_ids(tmp_path):
    first = MarkdownStore(URL, tmp_path, WHEN)
    first.open()
    first.append(sample(837890))
    first.close()

    resumed = MarkdownStore(URL, tmp_path, WHEN)
    resumed.open()
    assert resumed.has(837890) is True
    assert resumed.count == 1
    assert resumed.append(sample(837890)) is False
    assert resumed.append(sample(999001)) is True
    resumed.close()
    assert resumed.path.read_text(encoding="utf-8").count("<!-- job-id:") == 2


def test_source_url_mismatch_aborts(tmp_path):
    # Write a file whose header records URL.
    store = MarkdownStore(URL, tmp_path, WHEN)
    store.open()
    store.append(sample())
    store.close()
    # A second store lands on the SAME filename (sanitization collision) but was
    # built for a different source URL -> must abort rather than mix searches.
    other = MarkdownStore(URL, tmp_path, WHEN)
    other._source_url = "https://djinni.co/jobs/?primary_keyword=Python"  # simulate collision
    with pytest.raises(SourceMismatch):
        other.open()


def test_open_aborts_on_headerless_file(tmp_path):
    # Non-empty existing file with no recognizable djinni-scraper header --
    # e.g. a previous run killed between opening the file and flushing the
    # header, or an unrelated file that happens to share the computed name.
    store = MarkdownStore(URL, tmp_path, WHEN)
    store.path.write_text("garbage\n", encoding="utf-8")
    with pytest.raises(SourceMismatch):
        store.open()


def test_open_treats_empty_existing_file_as_new(tmp_path):
    store = MarkdownStore(URL, tmp_path, WHEN)
    store.path.write_text("", encoding="utf-8")
    store.open()
    assert store.count == 0
    store.close()
    content = store.path.read_text(encoding="utf-8")
    assert content.startswith("<!-- djinni-scraper")
    assert f"source_url: {URL}" in content


def test_overwrite_starts_fresh(tmp_path):
    first = MarkdownStore(URL, tmp_path, WHEN)
    first.open()
    first.append(sample(837890))
    first.close()

    fresh = MarkdownStore(URL, tmp_path, WHEN, overwrite=True)
    fresh.open()
    assert fresh.count == 0
    assert fresh.has(837890) is False
    fresh.close()
