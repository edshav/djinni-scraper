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
