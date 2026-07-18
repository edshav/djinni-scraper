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
            value = addr.get("addressLocality") or addr.get("addressCountry")
            # Normalize list-valued locality/country to comma-joined string
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v)
            return value or None
    return None


def _format_domain(industry) -> Optional[str]:
    if not industry or industry == "other":
        return None
    return str(industry)


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
