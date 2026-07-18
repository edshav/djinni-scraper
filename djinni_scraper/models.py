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
