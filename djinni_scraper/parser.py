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
