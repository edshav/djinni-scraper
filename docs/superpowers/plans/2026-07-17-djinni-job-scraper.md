# Djinni Job Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A polite Python CLI that paginates a djinni.co listing URL and writes every posting into one combined Markdown file named by date + search URL, for AI-assisted analysis.

**Architecture:** Small modular package. `parser` reads each server-rendered listing page's embedded schema.org JSON-LD (all fields + full description) and enriches English level + geography from the matching HTML card. `storage` appends postings as Markdown sections to a single per-run file, deduping/resuming by numeric job id. `fetcher` owns all anti-block behavior. `cli` orchestrates pagination. No detail-page requests; no browser.

**Tech Stack:** Python 3.9+, `requests`, `beautifulsoup4` + `lxml`, stdlib (`argparse`, `urllib.parse`, `json`, `re`, `pathlib`, `datetime`, `random`, `time`, `logging`). Tests: `pytest`.

## Global Constraints

Every task's requirements implicitly include these (copied from the spec):

- **Anti-block is the top priority** (user was IP-blocked for a day). Sequential requests only — no threads/async. Default `--delay 4.0` s with ±50% jitter (≈2–6 s actual). Realistic Chrome `User-Agent` + `Accept-Language`. On `429`/`503` honor `Retry-After`, else exponential backoff with bounded retries. **Stop-on-block:** `429`/`403`/Cloudflare challenge → raise `BlockedError` and halt the whole run gracefully.
- **No detail-page requests.** Everything is parsed from listing pages. Total requests ≈ number of listing pages.
- **Parser is JSON-LD-first.** Parse the `<script type="application/ld+json">` array; enrich English level + geography from the HTML card matched by `id="job-item-<id>"`; fall back to HTML-card parsing only when a posting is absent from the JSON-LD.
- **Output:** one combined `.md` file per run, in `--out-dir` (default `./output`), named `YYYY-MM-DD__<sanitized-listing-url>.md`. Postings are appended live as `## ` sections; missing fields render as `N/A`.
- **Dedup/resume by numeric job id.** Each section carries a `<!-- job-id: N -->` marker. On open, read existing ids and the header `source_url`; a header URL mismatch aborts; `--overwrite` truncates and starts fresh.
- **`--max-jobs` default `1000`** = cap on total postings in the file (existing + new).
- **Dependencies:** only `requests`, `beautifulsoup4`, `lxml`; standard library otherwise.

## File Structure

- `pyproject.toml` — package metadata, deps, pytest config.
- `djinni_scraper/__init__.py` — package marker + version.
- `djinni_scraper/models.py` — `JobPosting` dataclass + `job_id_from_url`.
- `djinni_scraper/parser.py` — `parse_listing` (JSON-LD + HTML enrichment + card fallback).
- `djinni_scraper/storage.py` — `run_filename`, `render_section`, `MarkdownStore`, `SourceMismatch`.
- `djinni_scraper/fetcher.py` — `Fetcher`, `BlockedError`.
- `djinni_scraper/cli.py` — `build_page_url`, `run`, `main`.
- `djinni_scraper/__main__.py` — `python -m djinni_scraper` entry.
- `tests/__init__.py`, `tests/test_models.py`, `tests/test_parser.py`, `tests/test_storage.py`, `tests/test_fetcher.py`, `tests/test_cli.py`.
- `tests/fixtures/listing_fullstack.html` — **already committed** (real page, 15 postings).
- `README.md` — usage.

---

### Task 1: Project scaffold + `JobPosting` model

**Files:**
- Create: `pyproject.toml`, `djinni_scraper/__init__.py`, `djinni_scraper/models.py`, `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `JobPosting` dataclass, fields: `url: str`, `id: int`, and optional `title, company, salary, location, experience, english, domain, posted, description` (all `Optional[str] = None`).
  - `job_id_from_url(url: str) -> Optional[int]` — extracts the integer after `/jobs/`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "djinni-scraper"
version = "0.1.0"
description = "Polite scraper for djinni.co job listings"
requires-python = ">=3.9"
dependencies = ["requests>=2.31", "beautifulsoup4>=4.12", "lxml>=5.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
djinni-scraper = "djinni_scraper.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["djinni_scraper"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: Create the venv and install (one-time setup)**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
```
Expected: installs `djinni-scraper`, `requests`, `beautifulsoup4`, `lxml`, `pytest`.

- [ ] **Step 3: Create `djinni_scraper/__init__.py` and `tests/__init__.py`**

`djinni_scraper/__init__.py`:
```python
"""Polite scraper for djinni.co job listings."""

__version__ = "0.1.0"
```
`tests/__init__.py`: empty file.

- [ ] **Step 4: Write the failing test** — `tests/test_models.py`

```python
from djinni_scraper.models import JobPosting, job_id_from_url


def test_job_id_from_url_extracts_integer():
    url = "https://djinni.co/jobs/837890-senior-full-stack-or-integration-engineer-go-/"
    assert job_id_from_url(url) == 837890


def test_job_id_from_url_returns_none_without_id():
    assert job_id_from_url("https://djinni.co/jobs/") is None
    assert job_id_from_url("") is None


def test_job_posting_optional_fields_default_none():
    p = JobPosting(url="https://djinni.co/jobs/1-x/", id=1)
    assert p.title is None
    assert p.salary is None
    assert p.description is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'djinni_scraper.models'`.

- [ ] **Step 6: Write minimal implementation** — `djinni_scraper/models.py`

```python
"""Data model for a single job posting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_JOB_ID_RE = re.compile(r"/jobs/(\d+)")


def job_id_from_url(url: str) -> Optional[int]:
    """Return the integer job id embedded in a djinni job URL, or None."""
    match = _JOB_ID_RE.search(url or "")
    return int(match.group(1)) if match else None


@dataclass
class JobPosting:
    """One djinni job posting. Content fields are optional so a page missing a
    field never crashes the run."""

    url: str
    id: int
    title: Optional[str] = None
    company: Optional[str] = None
    salary: Optional[str] = None       # display, e.g. "$3000–5000/mo"
    location: Optional[str] = None     # remote type + geography, e.g. "Remote · Worldwide"
    experience: Optional[str] = None   # e.g. "5 years"
    english: Optional[str] = None      # e.g. "B2"
    domain: Optional[str] = None       # industry slug, e.g. "fintech"
    posted: Optional[str] = None       # ISO date, e.g. "2026-07-17"
    description: Optional[str] = None   # full description text
```

- [ ] **Step 7: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml djinni_scraper/__init__.py djinni_scraper/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: project scaffold and JobPosting model"
```

---

### Task 2: Parser — JSON-LD extraction + formatting helpers

**Files:**
- Create: `djinni_scraper/parser.py`
- Test: `tests/test_parser.py`
- Uses fixture: `tests/fixtures/listing_fullstack.html`

**Interfaces:**
- Consumes: `JobPosting`, `job_id_from_url` from Task 1.
- Produces:
  - `parse_listing(html: str, base_url: str = "https://djinni.co") -> list[JobPosting]` (JSON-LD only in this task; HTML enrichment added in Task 3).
  - Module-private helpers `_format_salary`, `_format_experience`, `_format_posted`, `_format_location`, `_format_domain`, `_parse_jsonld` used by later tasks' code in the same file.

- [ ] **Step 1: Write the failing test** — `tests/test_parser.py`

```python
from pathlib import Path

import pytest

from djinni_scraper.parser import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "listing_fullstack.html"


@pytest.fixture(scope="module")
def postings():
    html = FIXTURE.read_text(encoding="utf-8")
    return parse_listing(html, base_url="https://djinni.co")


def by_id(postings, job_id):
    return next(p for p in postings if p.id == job_id)


def test_parses_all_fifteen_postings(postings):
    assert len(postings) == 15


def test_jsonld_core_fields(postings):
    p = by_id(postings, 837890)
    assert p.title == "Senior full-stack or integration engineer (Go, React) for PropTech"
    assert p.company == "Upstaff"
    assert p.salary == "$3000–5000/mo"
    assert p.experience == "5 years"
    assert p.domain == "proptech"
    assert p.posted == "2026-07-17"
    assert p.url == (
        "https://djinni.co/jobs/837890-senior-full-stack-or-integration-engineer-go-/"
    )


def test_full_description_from_jsonld(postings):
    p = by_id(postings, 837890)
    assert p.description.startswith("We are looking for experienced software")
    assert "SAP" in p.description
    assert len(p.description) > 2000


def test_missing_salary_is_none(postings):
    # id 827322 has no baseSalary in the JSON-LD
    p = by_id(postings, 827322)
    assert p.salary is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'djinni_scraper.parser'`.

- [ ] **Step 3: Write minimal implementation** — `djinni_scraper/parser.py`

```python
"""Parse a djinni listing page into JobPosting objects.

Primary source is the embedded schema.org JSON-LD array (all fields + full
description). English level and geography are enriched from the HTML card in
Task 3; here we build postings from JSON-LD only.
"""

from __future__ import annotations

import json
from typing import Optional

from bs4 import BeautifulSoup

from .models import JobPosting, job_id_from_url

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "UAH": "₴"}
_UNIT_SUFFIX = {"MONTH": "/mo", "YEAR": "/yr", "HOUR": "/hr", "DAY": "/day"}


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_salary(base_salary) -> Optional[str]:
    if not isinstance(base_salary, dict):
        return None
    value = base_salary.get("value") or {}
    low, high = value.get("minValue"), value.get("maxValue")
    currency = base_salary.get("currency") or ""
    symbol = _CURRENCY_SYMBOLS.get(currency, (currency + " ") if currency else "")
    unit = _UNIT_SUFFIX.get(str(value.get("unitText") or "").upper(), "")
    if low and high and low != high:
        return f"{symbol}{_num(low)}–{_num(high)}{unit}"
    single = low or high
    return f"{symbol}{_num(single)}{unit}" if single else None


def _format_experience(exp_req) -> Optional[str]:
    if not isinstance(exp_req, dict):
        return None
    months = exp_req.get("monthsOfExperience")
    if months is None:
        return None
    if months == 0:
        return "No experience"
    years = months / 12
    if float(years).is_integer():
        whole = int(years)
        return f"{whole} year" + ("s" if whole != 1 else "")
    return f"{years:.1f} years"


def _format_posted(date_posted) -> Optional[str]:
    if not date_posted:
        return None
    return str(date_posted)[:10]  # "2026-07-17T15:03:23" -> "2026-07-17"


def _format_location(location_type, job_location) -> Optional[str]:
    mapping = {"TELECOMMUTE": "Remote"}
    if location_type:
        return mapping.get(location_type, str(location_type).replace("_", " ").title())
    if isinstance(job_location, dict):
        addr = job_location.get("address") or {}
        if isinstance(addr, dict):
            return addr.get("addressLocality") or addr.get("addressCountry")
    return None


def _format_domain(industry) -> Optional[str]:
    if not industry or industry == "other":
        return None
    return str(industry)


def _parse_jsonld(soup: BeautifulSoup) -> list[JobPosting]:
    postings: list[JobPosting] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for obj in items:
            if not isinstance(obj, dict) or obj.get("@type") != "JobPosting":
                continue
            url = obj.get("url") or ""
            job_id = obj.get("identifier")
            job_id = int(job_id) if isinstance(job_id, (int, str)) and str(job_id).isdigit() else job_id_from_url(url)
            if job_id is None:
                continue
            org = obj.get("hiringOrganization") or {}
            description = (obj.get("description") or "").strip() or None
            postings.append(
                JobPosting(
                    url=url,
                    id=int(job_id),
                    title=obj.get("title"),
                    company=org.get("name") if isinstance(org, dict) else None,
                    salary=_format_salary(obj.get("baseSalary")),
                    location=_format_location(obj.get("jobLocationType"), obj.get("jobLocation")),
                    experience=_format_experience(obj.get("experienceRequirements")),
                    english=None,
                    domain=_format_domain(obj.get("industry")),
                    posted=_format_posted(obj.get("datePosted")),
                    description=description,
                )
            )
    return postings


def parse_listing(html: str, base_url: str = "https://djinni.co") -> list[JobPosting]:
    """Parse one listing page into JobPosting objects (JSON-LD only for now)."""
    soup = BeautifulSoup(html, "lxml")
    return _parse_jsonld(soup)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add djinni_scraper/parser.py tests/test_parser.py
git commit -m "feat: parse postings from listing-page JSON-LD"
```

---

### Task 3: Parser — HTML enrichment (English + geography) + card fallback

**Files:**
- Modify: `djinni_scraper/parser.py` (add `_enrich_from_cards`, `_parse_cards`; wire into `parse_listing`)
- Modify test: `tests/test_parser.py` (add enrichment + fallback assertions)

**Interfaces:**
- Consumes: everything from Task 2 in the same file.
- Produces: final `parse_listing` behavior — JSON-LD + English/geo enrichment, with card fallback when JSON-LD is empty.

- [ ] **Step 1: Add failing tests** — append to `tests/test_parser.py`

```python
def test_english_and_geography_enriched_from_card(postings):
    p = by_id(postings, 837890)
    assert p.english == "B2"
    assert p.location == "Remote · Worldwide"


def test_fallback_parses_cards_when_jsonld_absent():
    html = FIXTURE.read_text(encoding="utf-8")
    # Remove all JSON-LD to force the HTML-card fallback path.
    import re as _re
    stripped = _re.sub(
        r'<script type="application/ld\+json">.*?</script>', "", html, flags=_re.S
    )
    postings = parse_listing(stripped, base_url="https://djinni.co")
    assert len(postings) == 15
    p = next(x for x in postings if x.id == 837890)
    assert p.title and "integration engineer" in p.title.lower()
    assert p.english == "B2"
    assert p.description and "SAP" in p.description
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: `test_english_and_geography_enriched_from_card` FAILS (english is None) and `test_fallback_parses_cards_when_jsonld_absent` FAILS (0 postings).

- [ ] **Step 3: Implement enrichment + fallback** — edit `djinni_scraper/parser.py`

Add these functions above `parse_listing`:

```python
def _card_english(card) -> Optional[str]:
    for span in card.select("span.text-nowrap"):
        text = span.get_text(" ", strip=True)
        if text.startswith("English"):
            return text.split("-", 1)[1].strip() if "-" in text else text
    return None


def _card_geography(card) -> Optional[str]:
    node = card.select_one(".location-text")
    return node.get_text(strip=True) if node else None


def _card_description(card) -> Optional[str]:
    original = card.select_one(".js-original-text")
    node = original or card.select_one(".js-truncated-text")
    if node is None:
        return None
    text = node.get_text("\n", strip=True)
    return text or None


def _enrich_from_cards(postings: list[JobPosting], soup: BeautifulSoup) -> None:
    by_id = {p.id: p for p in postings}
    for card in soup.select("div.job-item[id^='job-item-']"):
        raw_id = (card.get("id") or "").rsplit("-", 1)[-1]
        if not raw_id.isdigit():
            continue
        posting = by_id.get(int(raw_id))
        if posting is None:
            continue
        english = _card_english(card)
        if english and not posting.english:
            posting.english = english
        geography = _card_geography(card)
        if geography:
            if posting.location and geography.lower() not in posting.location.lower():
                posting.location = f"{posting.location} · {geography}"
            elif not posting.location:
                posting.location = geography


def _parse_cards(soup: BeautifulSoup, base_url: str) -> list[JobPosting]:
    from urllib.parse import urljoin

    postings: list[JobPosting] = []
    for card in soup.select("div.job-item[id^='job-item-']"):
        raw_id = (card.get("id") or "").rsplit("-", 1)[-1]
        if not raw_id.isdigit():
            continue
        link = card.select_one("a.job_item__header-link[href]") or card.select_one("a[href^='/jobs/']")
        url = urljoin(base_url, link["href"]) if link else f"{base_url}/jobs/{raw_id}/"
        title_node = card.select_one("h2.job-item__position")
        company_node = card.select_one("span.text-gray-800")
        salary_node = card.select_one(".text-success")
        postings.append(
            JobPosting(
                url=url,
                id=int(raw_id),
                title=title_node.get_text(" ", strip=True) if title_node else None,
                company=company_node.get_text(" ", strip=True) if company_node else None,
                salary=salary_node.get_text(" ", strip=True) if salary_node else None,
                location=None,
                experience=None,
                english=None,
                domain=None,
                posted=None,
                description=_card_description(card),
            )
        )
    return postings
```

Then replace the body of `parse_listing`:

```python
def parse_listing(html: str, base_url: str = "https://djinni.co") -> list[JobPosting]:
    """Parse one listing page into JobPosting objects.

    JSON-LD is the primary source; English level and geography are enriched from
    the HTML card. If the JSON-LD is missing, fall back to HTML-card parsing.
    An empty result signals the last page.
    """
    soup = BeautifulSoup(html, "lxml")
    postings = _parse_jsonld(soup)
    if not postings:
        postings = _parse_cards(soup, base_url)
    _enrich_from_cards(postings, soup)
    return postings
```

- [ ] **Step 4: Run the full parser test file**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add djinni_scraper/parser.py tests/test_parser.py
git commit -m "feat: enrich English/geography from HTML card, add card fallback"
```

---

### Task 4: Storage — filename, render, append, dedup, resume, header verify

**Files:**
- Create: `djinni_scraper/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `JobPosting`, `job_id_from_url` from Task 1.
- Produces:
  - `run_filename(listing_url: str, when: datetime.date) -> str`
  - `render_section(posting: JobPosting) -> str`
  - `class SourceMismatch(Exception)`
  - `class MarkdownStore` with:
    - `__init__(self, listing_url: str, out_dir, when, overwrite: bool = False)`
    - `path` (a `pathlib.Path`), `count` (int, postings already in file)
    - `open() -> None` (creates+header or resumes+verifies; raises `SourceMismatch`)
    - `has(job_id: int) -> bool`
    - `append(posting: JobPosting) -> bool` (writes + flush; returns False if duplicate/known id)
    - `close() -> None`; usable as a context manager.

- [ ] **Step 1: Write the failing test** — `tests/test_storage.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'djinni_scraper.storage'`.

- [ ] **Step 3: Write minimal implementation** — `djinni_scraper/storage.py`

```python
"""Write postings to one combined Markdown file per run, with resume/dedup."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Optional

from .models import JobPosting

_FIELD_ORDER = [
    ("Company", "company"),
    ("Salary", "salary"),
    ("Location/Remote", "location"),
    ("Experience", "experience"),
    ("English", "english"),
    ("Domain", "domain"),
    ("Posted", "posted"),
    ("URL", "url"),
]
_ID_MARKER_RE = re.compile(r"<!-- job-id:\s*(\d+)\s*-->")
_HEADER_URL_RE = re.compile(r"source_url:\s*(\S+)")


class SourceMismatch(Exception):
    """Existing output file was created for a different listing URL."""


def run_filename(listing_url: str, when: dt.date) -> str:
    from urllib.parse import urlsplit

    parts = urlsplit(listing_url)
    raw = parts.netloc + parts.path
    if parts.query:
        raw += "_" + parts.query
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    safe = re.sub(r"_+", "_", safe)
    if len(safe) > 120:
        safe = safe[:120].rstrip("_")
    return f"{when.isoformat()}__{safe}.md"


def render_section(posting: JobPosting) -> str:
    lines = [f"<!-- job-id: {posting.id} -->", f"## {posting.title or 'N/A'}", ""]
    for label, attr in _FIELD_ORDER:
        value = getattr(posting, attr, None)
        lines.append(f"- **{label}:** {value if value else 'N/A'}")
    lines.append("- **Scraped-at:** " + dt.date.today().isoformat())
    lines.append("")
    lines.append(posting.description or "N/A")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


class MarkdownStore:
    def __init__(self, listing_url: str, out_dir, when: dt.date, overwrite: bool = False):
        self._source_url = listing_url
        self._out_dir = Path(out_dir)
        self._when = when
        self._overwrite = overwrite
        self.path = self._out_dir / run_filename(listing_url, when)
        self._ids: set[int] = set()
        self._handle = None

    @property
    def count(self) -> int:
        return len(self._ids)

    def has(self, job_id: int) -> bool:
        return job_id in self._ids

    def open(self) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self._overwrite:
            existing = self.path.read_text(encoding="utf-8")
            match = _HEADER_URL_RE.search(existing)
            if match and match.group(1) != self._source_url:
                raise SourceMismatch(
                    f"{self.path} was created for {match.group(1)!r}, not "
                    f"{self._source_url!r}. Use --overwrite or a different --out-dir."
                )
            self._ids = {int(m) for m in _ID_MARKER_RE.findall(existing)}
            self._handle = self.path.open("a", encoding="utf-8")
        else:
            self._handle = self.path.open("w", encoding="utf-8")
            self._handle.write(self._header())
            self._handle.flush()

    def _header(self) -> str:
        return (
            "<!-- djinni-scraper\n"
            f"source_url: {self._source_url}\n"
            f"scraped_at: {self._when.isoformat()}\n"
            "-->\n"
            f"# Djinni postings — {self._source_url}\n\n"
        )

    def append(self, posting: JobPosting) -> bool:
        if posting.id in self._ids:
            return False
        assert self._handle is not None, "open() must be called first"
        self._handle.write(render_section(posting))
        self._handle.flush()
        self._ids.add(posting.id)
        return True

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "MarkdownStore":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add djinni_scraper/storage.py tests/test_storage.py
git commit -m "feat: combined Markdown storage with resume, dedup, source verify"
```

---

### Task 5: Fetcher — anti-block HTTP client

**Files:**
- Create: `djinni_scraper/fetcher.py`
- Test: `tests/test_fetcher.py`

**Interfaces:**
- Produces:
  - `class BlockedError(Exception)`
  - `class Fetcher` with `__init__(self, delay=4.0, jitter=0.5, user_agent=DEFAULT_UA, timeout=30, max_retries=3, session=None, sleep=time.sleep, monotonic=time.monotonic, rng=None)` and `get(self, url: str) -> str`.
- Design notes: sequential; a delay (with jitter) is enforced before every request; `429`/`403` or a Cloudflare challenge body → `BlockedError`; `429`/`503` honor `Retry-After` then retry up to `max_retries`; `>=500` → exponential backoff retry; network exceptions → backoff retry; exhaustion → `BlockedError`/last exception.

- [ ] **Step 1: Write the failing test** — `tests/test_fetcher.py`

```python
import pytest

from djinni_scraper.fetcher import BlockedError, Fetcher


class FakeResponse:
    def __init__(self, status_code=200, text="<html>ok</html>", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def make_fetcher(session, **kw):
    slept = []
    fetcher = Fetcher(
        delay=4.0,
        jitter=0.0,
        session=session,
        sleep=lambda s: slept.append(s),
        monotonic=lambda: 1000.0,
        **kw,
    )
    return fetcher, slept


def test_get_returns_text_on_200():
    session = FakeSession([FakeResponse(200, "<html>hello</html>")])
    fetcher, slept = make_fetcher(session)
    assert fetcher.get("https://djinni.co/jobs/") == "<html>hello</html>"


def test_delay_enforced_before_request():
    session = FakeSession([FakeResponse(200, "ok")])
    fetcher, slept = make_fetcher(session)
    fetcher.get("https://djinni.co/jobs/")
    assert slept and slept[0] == pytest.approx(4.0)


def test_429_raises_blocked():
    session = FakeSession([FakeResponse(429, "Too Many Requests", {"Retry-After": "0"})] * 5)
    fetcher, _ = make_fetcher(session, max_retries=2)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_403_raises_blocked():
    session = FakeSession([FakeResponse(403, "Forbidden")])
    fetcher, _ = make_fetcher(session)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_cloudflare_challenge_body_raises_blocked():
    body = "<html><title>Just a moment...</title></html>"
    session = FakeSession([FakeResponse(200, body)])
    fetcher, _ = make_fetcher(session)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_500_retries_then_succeeds():
    session = FakeSession([FakeResponse(500, "err"), FakeResponse(200, "recovered")])
    fetcher, _ = make_fetcher(session, max_retries=3)
    assert fetcher.get("https://djinni.co/jobs/") == "recovered"
    assert session.calls == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'djinni_scraper.fetcher'`.

- [ ] **Step 3: Write minimal implementation** — `djinni_scraper/fetcher.py`

```python
"""HTTP fetching with all anti-block behavior (the project's top priority)."""

from __future__ import annotations

import random
import time
from typing import Optional

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_BLOCK_STATUSES = {403, 429}
_BACKOFF_STATUSES = {429, 500, 502, 503, 504}
_CHALLENGE_MARKERS = ("just a moment", "attention required", "cf-chl", "cf-browser-verification")


class BlockedError(Exception):
    """Raised when djinni appears to be throttling or blocking us."""


class Fetcher:
    def __init__(
        self,
        delay: float = 4.0,
        jitter: float = 0.5,
        user_agent: str = DEFAULT_UA,
        timeout: int = 30,
        max_retries: int = 3,
        session=None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        rng: Optional[random.Random] = None,
    ):
        self._delay = delay
        self._jitter = jitter
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._rng = rng or random.Random()
        self._last_request_at: Optional[float] = None
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def _wait_before_request(self) -> None:
        factor = 1.0 + self._rng.uniform(-self._jitter, self._jitter)
        target = max(0.0, self._delay * factor)
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            target = max(0.0, target - elapsed)
        if target > 0:
            self._sleep(target)
        self._last_request_at = self._monotonic()

    @staticmethod
    def _is_challenge(text: str) -> bool:
        head = (text or "")[:2000].lower()
        return any(marker in head for marker in _CHALLENGE_MARKERS)

    def get(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            self._wait_before_request()
            try:
                resp = self._session.get(url, headers=self._headers, timeout=self._timeout)
            except Exception as exc:  # network error -> backoff and retry
                last_exc = exc
                self._sleep(2 ** attempt)
                continue

            status = resp.status_code
            if status in _BLOCK_STATUSES:
                if status == 429 and attempt < self._max_retries:
                    self._sleep(self._retry_after(resp, attempt))
                    continue
                raise BlockedError(f"Blocked by djinni (HTTP {status}) at {url}")
            if status in _BACKOFF_STATUSES:
                if attempt < self._max_retries:
                    self._sleep(self._retry_after(resp, attempt))
                    continue
                raise BlockedError(f"Repeated HTTP {status} at {url}; stopping to avoid a block")
            if status >= 400:
                raise BlockedError(f"Unexpected HTTP {status} at {url}")
            if self._is_challenge(resp.text):
                raise BlockedError(f"Cloudflare challenge detected at {url}")
            return resp.text

        raise BlockedError(f"Giving up after retries at {url}: {last_exc}")

    def _retry_after(self, resp, attempt: int) -> float:
        header = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return 2 ** attempt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fetcher.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add djinni_scraper/fetcher.py tests/test_fetcher.py
git commit -m "feat: anti-block fetcher with delay, backoff, stop-on-block"
```

---

### Task 6: CLI — pagination orchestration + entry point + README

**Files:**
- Create: `djinni_scraper/cli.py`, `djinni_scraper/__main__.py`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `parse_listing` (Task 2/3), `MarkdownStore`/`SourceMismatch` (Task 4), `Fetcher`/`BlockedError` (Task 5).
- Produces:
  - `build_page_url(listing_url: str, page: int) -> str`
  - `run(listing_url, out_dir, max_pages, max_jobs, delay, overwrite, fetcher=None, when=None) -> int` (returns count written this run)
  - `main(argv=None) -> int` (exit code)

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'djinni_scraper.cli'`.

- [ ] **Step 3: Write minimal implementation** — `djinni_scraper/cli.py`

```python
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

    if "djinni.co" not in urlsplit(args.listing_url).netloc:
        parser.error("listing_url must be a djinni.co URL")

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
```

- [ ] **Step 4: Create `djinni_scraper/__main__.py`**

```python
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Write `README.md`**

```markdown
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
`--delay` (±50% jitter) between every request, honors `Retry-After`, and **stops
immediately** on `429`/`403`/Cloudflare challenge. Because postings are appended
live and deduped by job id, re-running later resumes where it stopped. Raise
`--delay` for large runs.
```

- [ ] **Step 7: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all tests green: models 3, parser 7, storage 7, fetcher 6, cli 4).

- [ ] **Step 8: Commit**

```bash
git add djinni_scraper/cli.py djinni_scraper/__main__.py README.md tests/test_cli.py
git commit -m "feat: CLI pagination orchestration and entry point"
```

---

### Task 7: End-to-end smoke run (single real page, polite)

**Files:** none (manual verification only).

This is the only step that touches the live site. Do it **once**, with a tight cap, to confirm the tool works end-to-end against real djinni HTML. Respect the block risk.

- [ ] **Step 1: Run one page, capped**

Run:
```bash
.venv/bin/djinni-scraper "https://djinni.co/jobs/?primary_keyword=Fullstack&salary=3000" --max-jobs 15 --delay 5
```
Expected: prints `Wrote N new postings.` and creates one file under `./output/` named `<today>__djinni.co_jobs_*.md` containing `## ` sections with fields + descriptions.

- [ ] **Step 2: Verify resume is a no-op**

Run the same command again.
Expected: `Wrote 0 new postings.` (all ids already present) and the file is unchanged in count.

- [ ] **Step 3: Do NOT commit `output/`** (it is git-ignored). Done.

---

## Self-Review

**1. Spec coverage:**
- Server-rendered HTTP scraping, no browser → Fetcher (Task 5), no Playwright. ✓
- JSON-LD-first parser + English/geo HTML enrichment + card fallback → Tasks 2–3. ✓
- Single combined Markdown file, filename = date + sanitized listing URL → `run_filename` (Task 4). ✓
- Append live, sections with `<!-- job-id -->`, `N/A` for missing → `render_section`/`MarkdownStore` (Task 4). ✓
- Dedup + resume by numeric id, header source-URL verify, `--overwrite` → Task 4. ✓
- Pagination merging `page=N` while preserving filters; stop on empty/`--max-pages`/`--max-jobs` → `build_page_url`/`run` (Task 6). ✓
- Anti-block: sequential, delay+jitter, Retry-After, backoff, stop-on-block `BlockedError` → Task 5. ✓
- `--max-jobs` default 1000; `--out-dir` default `./output`; `--delay` 4.0 → `main` (Task 6). ✓
- Error handling: BlockedError halts gracefully & reports resume; non-djinni host fails fast; SourceMismatch aborts → Tasks 5–6. ✓
- TDD parser against committed fixture → Task 2/3 use `tests/fixtures/listing_fullstack.html`. ✓

**2. Placeholder scan:** No TBD/TODO; every code step contains complete code and exact commands. ✓

**3. Type consistency:** `parse_listing(html, base_url) -> list[JobPosting]`, `JobPosting.id: int`, `MarkdownStore.append -> bool`, `Fetcher.get(url) -> str`, `build_page_url(url, page) -> str`, `run(...) -> int` are used identically across Tasks 2–7. ✓

**Known simplification (intentional, YAGNI):** a per-card parse failure is not individually wrapped in try/except within `_parse_jsonld`; JSON-LD is uniform so a single malformed object is skipped by the `@type`/id guards. If real runs surface malformed cards, add per-item `try/except` around the `postings.append(...)` block.
